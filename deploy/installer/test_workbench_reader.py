"""Exercise the same input loop that owns the macOS/SSH terminal, including Enter."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.utils import get_cwidth

from chives_terminal import actions
from chives_terminal.pages import CONTENT, board_page, holdings, market_page, portrait, watchlist_page
from chives_terminal.workbench import Workbench


class FixtureAPI:
    def __init__(self):
        self.models = [dict(id="m1", model="first", active=True), dict(id="m2", model="second", active=False)]
        self.writes = []
        self.bots = [dict(id="operator", name="总调度", role="研究", model="default")]
        self.snapshot = {"boards":{"in":{"title":"资金流入榜","columns":["净流入占市值","五日涨幅"],
                            "rows":[dict(name="中A公司",code="000001",metric="3.2%",r5=-2.08)]}}}
        self.channels = [dict(id="telegram",enabled=False,configured=False)]

    def json(self, path, body=None, method=None):
        if body is not None:
            self.writes.append((path, dict(body)))
        if path.endswith("/models"):
            if body:
                for m in self.models:
                    m["active"] = m["id"] == body["id"]
            return self.models
        if path.endswith("/employment"):
            if body:
                for bot in self.bots:
                    bot["hired"] = bot["id"] in body["hiredIds"]
            return self.bots
        if path == "/api/bots":
            return self.bots
        if path.endswith("/hotspots"):
            return {"snapshot":self.snapshot}
        if path.endswith("/channels"):
            return self.channels if body is None else {"ok":True}
        if path.endswith("/watchlist"):
            return [dict(code="000001.SZ", name="测试关注", estimates=[
                dict(low=10, high=20, score=1, version=1, asOf="2026-11-23")])]
        if path.endswith("/holdings"):
            if body and body.get("action") == "quote":
                return {"price": 8}
            return {"positions":[dict(code="1",name="测试持仓",qty=30,cost_price=12.5)]}
        if path.endswith("/portfolio"):
            return {"positions":[],"summary":{}}
        if path.endswith("/assessment"):
            return {"result":{"report":{"match":{"people":[dict(name="人物文字",bio="人物生平")]}}}}
        if path.endswith("/market"):
            return {"indexes":[dict(code="001",name="测试指数",price=50.1,changePct=-0.8)]}
        raise AssertionError(path)


class KeyFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pipe = self.enterContext(create_pipe_input())
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.prefs = Path(folder) / "terminal.json"
        self.enterContext(patch.object(actions, "PREFS", self.prefs))
        self.api = FixtureAPI()
        self.desk = Workbench(self.api, self.api.bots, None, input=self.pipe, output=DummyOutput())
        self.desk.app.ttimeoutlen = .015
        self.desk.app.timeoutlen = .02
        self.task = asyncio.create_task(self.desk.app.run_async())
        await self.until(lambda: self.desk.boards)

    async def asyncTearDown(self):
        if self.desk.app.is_running:
            self.desk.app.exit()
        await self.task

    async def until(self, predicate):
        for _ in range(150):
            if predicate():
                return
            await asyncio.sleep(.01)
        self.fail(f"Unexpected screen {self.desk.column}, {self.desk.section_row}, {self.desk.panels.kind}, {self.desk.panels.title}")

    async def key(self, seq, predicate):
        self.pipe.send_text(seq)
        await self.until(predicate)

    def showing(self, title):
        return self.desk.in_dialog and self.desk.panels.title.startswith(title) and self.desk.panels.kind != "loading"

    def body(self):
        return "".join(t for _,t in self.desk.panels.render())

    async def test_employment_keyboard_operator_lock_and_cancel(self):
        desk = self.desk
        self.api.bots[0]["hired"] = True
        for n in range(1, 20):
            self.api.bots.append(dict(id=f"b{n}", name=f"同事{n}", role="研究", hired=n < 3))
        await desk.reload_bots()
        self.assertEqual(len(desk.matches()), 3)
        await self.key("\x1b[B"*3+"\r", lambda: desk.panels.kind=="checklist")
        self.assertEqual(len(desk.panels.options), 20)
        self.pipe.send_text(" " + "\x1b[B "*2 + "\r")
        await self.until(lambda: not desk.in_dialog)
        self.assertEqual([b["id"] for b in desk.bots], ["operator"])
        self.assertEqual(self.api.writes[-1][1]["hiredIds"], ["operator"])
        await self.key("\r", lambda: desk.panels.kind=="checklist")
        self.pipe.send_text("\x1b[B \x1b")
        await self.until(lambda: not desk.in_dialog)
        self.assertEqual(len(self.api.writes), 1)
        await self.key("\r", lambda: desk.panels.kind=="checklist")
        self.pipe.send_text("\x1b[B \r")
        await self.until(lambda: not desk.in_dialog)
        self.assertEqual([b["id"] for b in desk.bots], ["operator", "b1"])

    async def test_direct_board_market_holdings_full_profile(self):
        desk = self.desk
        await self.key("\t", lambda: desk.column == 1)
        await self.key("\r", lambda: self.showing("资金流入榜"))
        self.assertIn("中A公司", self.body())
        self.assertIn("-2.08%", self.body())
        for expected, text in [("行情看板","测试指数"),("用户持仓","测试持仓"),("用户关注","后市AI预测"),("风格评估","人物生平")]:
            await self.key("\x1b", lambda: not desk.in_dialog)
            await self.key("\x1b[B\r", lambda: self.showing(expected))
            self.assertIn(text, self.body())
            if expected == "行情看板":
                await self.key("\x1b[C", lambda: self.showing("行情看板 · 市场宽度"))

    async def test_save_default_quick_switch_and_flat_channel_form(self):
        d = self.desk
        await self.key("\t\t", lambda: d.column == 2)
        await self.key("\r", lambda: self.showing("全局默认模型"))
        await self.key("\x1b[B\r", lambda: d.default_model == "second")
        self.assertTrue(self.api.models[1]["active"])
        await self.until(lambda: not d.in_dialog)
        await self.key("\x1b[B\r", lambda: self.prefs.exists())
        self.assertTrue(json.loads(self.prefs.read_text())["compact"])
        await self.key("\x1b[B"*3+"\r", lambda: self.showing("更多设置"))
        self.assertIn("添加模型连接", dict(d.panels.options).values())
        ix = [k for k,_ in d.panels.options].index("channel/telegram")
        await self.key("\x1b[B"*ix+"\r", lambda: d.panels.kind=="form")
        await self.key("test-token\tchat-7\t\x1b[C\t\r", lambda: self.showing("更多设置") and len(self.api.writes)==2)
        body = self.api.writes[-1][1]
        self.assertEqual((body["key"],body["target"],body["enabled"]),("test-token","chat-7",True))
        self.assertEqual(d.panels.options[d.panels.index][0],"channel/telegram")
        await self.key("\x1b", lambda: not d.in_dialog)


class Reader(unittest.TestCase):
    def test_holdings_valuation_boundary(self):
        code = "600001.SH"
        book = {"positions": [dict(code=code, name="示例公司", qty=100, cost_price=10)]}
        valuations = {code: {"low": 10, "high": 20}}
        for price, expected in [(8, "现价低于估值下限 20%"), (25, "现价高于估值上限 25%"),
                                (15, None), (None, None)]:
            with self.subTest(price=price):
                quotes = {"positions": [dict(code=code, name="示例公司", price=price)]}
                lines = holdings(book, quotes, valuations).lines(160)
                screen = "\n".join("".join(value for _, value in line) for line in lines)
                if expected:
                    self.assertIn(expected, screen)
                else:
                    self.assertNotIn("估值下限", screen)
                    self.assertNotIn("估值上限", screen)

    def test_watchlist_band_boundaries_and_outlook(self):
        for price, score, value_style, direction_style, label in [
            (9, 5, "up", "up", "看涨"), (21, -5, "down", "down", "看跌"),
            (10, 0, "ink", "neutral", "中性"), (20, 0, "ink", "neutral", "中性"),
            (15, None, "ink", "ink", "依据不足"), (None, None, "ink", "ink", "依据不足"),
        ]:
            entry = dict(code="600000.SH", name="测试", estimates=[
                dict(low=10, high=20, score=score, version=1, asOf="2026-11-23")])
            lines = watchlist_page([entry], {entry["code"]: price}).lines(70)
            parts = [part for line in lines for part in line]
            self.assertTrue(any(style=="class:"+value_style and "¥10–20" in txt for style,txt in parts))
            self.assertTrue(any(style=="class:"+direction_style and "后市AI预测  "+label in txt for style,txt in parts))

    def test_width_direction_and_unknown_personal_report(self):
        api = FixtureAPI()
        _, paper = board_page(api.snapshot, "in")
        for width in (18,36,76,116):
            lines = paper.lines(width)
            self.assertTrue(all(sum(get_cwidth(text) for _,text in line)<=width for line in lines))
            self.assertIn(("class:down","-2.08%"), [part for line in lines for part in line])
        empty = portrait({"sample":{"overview":"虚构画像"}})
        self.assertNotIn("虚构画像", str(empty.lines(80)))

    def test_web_market_sections_follow_the_same_content_definition(self):
        import re
        web = Path(__file__).resolve().parents[2] / "apps/web/src/components"
        src = (web / "MarketBoard.tsx").read_text()
        content = src[src.index('<div className="mb-grid">'):]
        # MarketNews and the stock-rank tabs each contribute two sections.
        news = (web / "MarketNews.tsx").read_text()
        content = content.replace("<MarketNews ask={ask}/>", news[news.index("return <>"):])
        observed = re.findall(r"content\.market\.(\w+)", content)
        self.assertEqual(list(dict.fromkeys(observed)), list(CONTENT["market"]))
        for key in observed:
            self.assertTrue(market_page(key, {}).lines(38))

    def test_all_person_and_style_fields_survive_without_portrait_metadata(self):
        report = {"risk":{"grade":4, "flags":["风险提示甲"]}, "match":{"reason":"匹配依据",
            "people":[dict(name="投资人甲", bio="生平甲", reason="理由甲", evidence=["证据甲"], difference="差异甲", portrait="omit-image-path")]},
            "styleCards":{"clarify":["待澄清甲"], "items":[dict(id="C7",title="风格甲",reading="解读甲",position={"value":37,"label":"尺度甲"})]}}
        paper = portrait({"result":{"report":report,"overview":"综合甲"}})
        text = "\n".join("".join(t for _,t in row) for row in paper.lines(80))
        for fact in ("综合甲","风险提示甲","匹配依据","投资人甲","生平甲","理由甲","证据甲","差异甲","风格甲","解读甲","尺度甲","待澄清甲","37 / 100"):
            self.assertIn(fact, text)
        self.assertNotIn("omit-image-path", text)


class TerminalColors(unittest.TestCase):
    def test_host_theme_owns_background_and_reading_text(self):
        from prompt_toolkit.styles import default_ui_style, merge_styles
        from chives_terminal.screen import STYLE, TerminalTheme

        merged = merge_styles([default_ui_style(), STYLE])
        for contrast in (False, True):
            theme = TerminalTheme(lambda: contrast)

            def rendered(role):
                return theme.transform_attrs(merged.get_attrs_for_style_str("class:" + role))

            for role in ("ink", "dim", "reason", "line", "band", "text-area", "field",
                         "completion-menu", "completion-menu.meta.completion", "scrollbar.background"):
                attrs = rendered(role)
                self.assertFalse(attrs.color, role)
                self.assertFalse(attrs.bgcolor, role)
                self.assertFalse(attrs.reverse, role)
            for role, tone in (("up", "ansired"), ("down", "ansigreen"), ("selected", "ansigreen"),
                               ("completion-menu.completion.current", "ansigreen")):
                attrs = rendered(role)
                self.assertEqual(attrs.color, tone)
                self.assertFalse(attrs.bgcolor)
                self.assertFalse(attrs.reverse)
                self.assertTrue(attrs.bold)
