"""Read-only projections of live workbench snapshots, using the web content contract."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from importlib.resources import files

from .reader import Paper, cell
from .screen import one

CONTENT = json.loads(files(__package__).joinpath("workbench-content.json").read_text(encoding="utf-8"))
DESK = "/api/settings/desk/"
MARKET = "/api/dashboard/"
SESSIONS = dict(pre_open="盘前", auction="集合竞价", trading="交易中",
                lunch_break="午间休市", closed="已收盘", holiday="休市")
INSIGHTS = dict(philosophy="投资理念", style="决策风格", industries="偏好行业",
                analogy="相似投资人", riskBehavior="实际风险偏好", evidence="判断依据")


def number(value, unit="", digits=2, signed=False):
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return one(value)
    prefix = "+" if signed and value > 0 else ""
    text = f"{value:,.{digits}f}"
    if digits:
        text = text.rstrip("0").rstrip(".")
    return prefix + text + unit


def delta(value, unit="%"):
    style = "ink" if not value else "up" if value > 0 else "down"
    return cell(number(value, unit, signed=True), style)


def stamp(value):
    if not value:
        return "时间待更新"
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo:
            return date.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M 北京时间")
    except ValueError:
        pass
    return one(value).replace("T", " ")


def board_page(snapshot, key):
    paper = Paper()
    board = (snapshot.get("boards") or {}).get(key)
    if not board:
        paper.text("当前发布版本里没有这个榜单。返回后可重新选择。")
        return "热门榜单", paper
    title = one(board["title"])
    paper.text("数据日期  " + stamp(board.get("asOf")), "accent")
    paper.text("发布于  " + stamp(snapshot.get("publishedAt")) +
               ("  ·  沿用上期" if key in (snapshot.get("retained") or []) else ""), "dim")
    paper.text(board.get("note"))
    paper.heading("榜单明细")
    config = CONTENT["hotspots"]
    field = config["changeField"].get(key, config["defaultChangeField"])
    cols = board.get("columns") or ["指标", "涨跌幅"]
    rows = []
    for i, item in enumerate(board.get("rows") or [], 1):
        metric_style = {"in":"up", "out":"down", "private":"up"}.get(key, "ink")
        change = item.get(field)
        rows.append([cell(str(i), "dim"), cell(one(item["name"]), "strong"), cell(one(item.get("code") or "—")),
                     cell(one(item.get("metric") or "—"), metric_style),
                     delta(change) if change is not None else cell("待满五日" if key == "global" else "暂无数据", "dim")])
    if rows:
        paper.table(["排名", "板块" if key == "global" else "股票", "代码", *cols[:2]], rows)
    else:
        paper.text("该榜本期暂无条目。", "dim")
    return title, paper


def market_page(key, data):
    paper = Paper()
    if key in ("domestic", "global"):
        edition = data.get(key) or {}
        paper.text("更新于  " + stamp(edition.get("updatedAt")), "dim")
        entries = (edition.get("entries") or [])[:20]
        for n, item in enumerate(entries, 1):
            paper.heading(f"{n:02}  {one(item['title'])}")
            paper.text(" · ".join(filter(None, (item.get("source"), item.get("region"),
                                                 stamp(item.get("publishedAt") or item.get("day"))))), "dim")
        if not entries:
            paper.text("暂无已发布资讯。")
        return paper
    if key == "portfolio":
        portfolio(paper, data)
        return paper
    if data.get("asOf"):
        paper.text(stamp(data["asOf"]) + ("  ·  缓存快照" if data.get("stale") else ""), "dim")
    if key in ("market", "breadth"):
        paper.text(SESSIONS.get(data.get("session"), "交易状态待更新"), "accent")
        if key == "breadth":
            breadth, limit = data.get("breadth") or {}, data.get("limit") or {}
            paper.table(["指标", "数值"], [[cell(label), cell(number(value, unit), style)] for label, value, unit, style in (
                ("沪深成交额", data.get("amountYuan"), " 元", "strong"), ("上涨家数", breadth.get("up"), " 家", "up"),
                ("下跌家数", breadth.get("down"), " 家", "down"), ("上涨占比", breadth.get("upRatioPct"), "%", "ink"),
                ("涨停", limit.get("limitUp"), " 家", "up"), ("跌停", limit.get("limitDown"), " 家", "down"))])
        else:
            rows = [[cell(one(r["name"]), "strong"), cell(one(r.get("code") or "—")),
                     cell(number(r.get("price"))), delta(r.get("changePct"))] for r in data.get("indexes") or []]
            paper.table(["指数", "代码", "点位", "涨跌幅"], rows)
            if not rows:
                paper.text("暂无指数报价。")
        return paper
    rows = []
    for r in data.get("rows") or []:
        row = [cell(one(r["name"]), "strong")]
        if key == "world":
            row += [cell(one(r.get("market") or "—")), cell(number(r.get("price"))),
                    delta(r.get("changePct")), cell(one(r.get("time") or "待更新").replace("T", " "))]
        else:
            row += [delta(r.get("change_pct")), cell(number(r.get("amount_yuan"), " 元"))]
            if key == "sectors":
                leader = r.get("leader") or {}
                row += [cell(one(leader.get("name") or "—")), delta(leader.get("change_pct"))]
            else:
                row.insert(1, cell(one(r.get("code") or "—"), "dim"))
        rows.append(row)
    cols = {"world":["指数", "市场", "点位", "涨跌幅", "当地报价时间"],
            "sectors":["行业", "涨跌幅", "成交额", "领涨股", "领涨股涨幅"]}
    paper.table(cols.get(key, ["股票", "代码", "涨跌幅", "成交额"]), rows)
    if not rows:
        paper.text("本期暂无行情记录。")
    return paper


def portfolio(paper, quotes):
    summary = quotes.get("summary") or {}
    paper.text("估值时间  " + stamp(quotes.get("asOf")), "dim")
    if quotes.get("empty"):
        paper.text("账本暂无持仓。")
        return
    paper.table(["估值指标", "金额"], [
        [cell("持仓市值"), cell(number(summary.get("totalMarketValue"), " 元"))],
        [cell("今日估算盈亏"), delta(summary.get("todayPnl"), " 元")],
        [cell("累计浮盈亏"), delta(summary.get("totalPnl"), " 元")]])
    if summary.get("unpricedCount"):
        paper.text(f"缺少报价  {summary['unpricedCount']} 只", "dim")
    rows = sorted(quotes.get("positions") or [], key=lambda r: abs(r.get("todayPnl") or 0), reverse=True)
    if rows:
        paper.heading("持仓贡献")
    paper.table(["证券", "代码", "现价", "今日涨跌", "今日贡献", "累计浮盈亏"], [
        [cell(one(r["name"]), "strong"), cell(one(r["code"]), "dim"), cell(number(r.get("price"))),
         delta(r.get("changePct")), delta(r.get("todayPnl"), " 元"), delta(r.get("pnl"), " 元")] for r in rows])


def holdings(book, quotes=None):
    paper = Paper()
    rows = book.get("positions") or []
    paper.text(f"证券数量  {len(rows)} 只", "accent")
    paper.text("持仓成本合计  " + number(sum(r["qty"]*r["cost_price"] for r in rows), " 元"))
    paper.text("账本现金  " + number(book.get("cash"), " 元"))
    if not rows:
        paper.text("账本暂无持仓。")
        return paper
    paper.heading("持仓明细")
    paper.table(["证券", "代码", "数量", "可用", "平均成本价", "持仓成本"], [
        [cell(one(r["name"]), "strong"), cell(one(r["code"]), "dim"), cell(number(r["qty"])),
         cell(number(r.get("available_qty"))), cell(number(r["cost_price"], digits=4)),
         cell(number(r["qty"]*r["cost_price"], " 元"))] for r in rows])
    for r in rows:
        if r.get("note"):
            paper.text(one(r["name"]) + " · " + one(r["note"]), "dim")
    paper.heading("持仓估值")
    if isinstance(quotes, Exception):
        paper.text("暂时取不到报价，账本明细见上。", "dim")
    elif quotes is not None:
        portfolio(paper, quotes)
    else:
        paper.text("正在读取行情估值…", "dim")
    return paper


def scale(paper, item):
    paper.text(item.get("label"), "accent")
    if item.get("value") is not None:
        paper.text("问卷量表  " + number(item["value"]) + " / 100    " +
                   " → ".join(filter(None, [item.get("low"), item.get("high")])), "dim")
    c = item.get("comparison") or {}
    if c:
        paper.text(f"同组比较  {c.get('peerGroup','')} · 第 {number(c.get('percentile'))} 百分位"
                   f" · {c.get('period','')} · {number(c.get('n'))} 人", "dim")
        paper.text(c.get("source"), "dim")


def portrait(data):
    paper = Paper()
    result = data.get("result")
    if not result:
        paper.text("尚未保存个人风格评估。完成工作台问卷后，可在这里阅读个人报告。")
        return paper
    report = result.get("report") or {}
    risk = report.get("risk") or {}
    grade = risk.get("grade") or result.get("grade")
    paper.text("评估时间  " + stamp(result.get("updated")), "dim")
    if report.get("answered") is not None:
        paper.text(f"已作答 {report['answered']} 题", "dim")
    paper.heading("综合解读")
    paper.text("风险承受能力（Chives 研究参考）  " + (f"C{grade}" if str(grade).isdigit() else grade or "待补充"), "strong")
    paper.text(CONTENT["risk"]["explanation"], "dim")
    paper.text(report.get("investmentStyle"), "accent")
    paper.text(result.get("overview"))
    for flag in risk.get("flags") or []:
        paper.text(flag, "accent")
    for key, label in INSIGHTS.items():
        value = (result.get("summary") or {}).get(key)
        if value:
            paper.heading(label)
            paper.text(value)
    match = report.get("match") or {}
    if match:
        paper.heading("您像谁")
        paper.text(match.get("reason"))
        for p in match.get("people") or []:
            paper.heading(p["name"])
            for key in ("style","bio","reason"):
                paper.text(p.get(key))
            for evidence in p.get("evidence") or []:
                paper.text(evidence)
            if p.get("difference"):
                paper.text("差异  " + p["difference"])
            paper.text(p.get("baike"), "dim")
    cards = report.get("styleCards") or {}
    if cards.get("items"):
        paper.heading("风格解读")
        for card in cards["items"]:
            paper.heading(card["title"])
            paper.text(card.get("reading"))
            if isinstance(card.get("position"), dict):
                scale(paper, card["position"])
            else:
                paper.text("倾向暂不明确 · 中性位置", "dim")
            if card.get("id") == "C13":
                paper.text(CONTENT["survey"]["text"], "dim")
                paper.text(CONTENT["survey"]["url"], "dim")
    if cards.get("clarify"):
        paper.heading("待澄清")
        for note in cards["clarify"]:
            paper.text(note)
    if report.get("dimensions"):
        paper.heading("评估维度")
        dims = {d["id"]:d.get("value") for d in report["dimensions"] if d.get("id")}
        will, room = dims.get("riskAppetite"), dims.get("capitalFlexibility")
        if not cards and will is not None and room is not None:
            paper.heading("敢冒的险，和承担得起的险")
            paper.text(f"资金余地  {room}/100    波动接受度  {will}/100")
            relation = "higher" if will-room >= 20 else "lower" if room-will >= 20 else "similar"
            paper.text(CONTENT["risk"][relation])
        for d in report["dimensions"]:
            paper.heading(d["title"])
            paper.text(d.get("reading"))
            scale(paper, d)
            for evidence in d.get("evidence") or []:
                paper.text(evidence, "dim")
        if not cards:
            paper.text(CONTENT["survey"]["text"], "dim")
            paper.text(CONTENT["survey"]["url"], "dim")
    if result.get("materials"):
        paper.heading("本次评估资料")
        for name in result["materials"]:
            paper.text(name)
    paper.heading("风险评估参考文件")
    paper.text(CONTENT["risk"]["url"], "dim")
    return paper


async def browse(api, view, page, *, replace_page):
    if page.startswith("board/") or page == "trends":
        snapshot = (await api(DESK + "hotspots")).get("snapshot") or {}
        if page == "trends":
            return await view("热门榜单", "已重新读取，返回可选择最新榜单。" if snapshot.get("boards") else "等待首版榜单发布。")
        title, paper = board_page(snapshot, page.removeprefix("board/"))
        return await view(title, paper)
    if page == "market":
        sections = list(CONTENT["market"].items())
        i = 0
        while True:
            key, name = sections[i]
            path = "/market-news.json" if key in ("domestic", "global") else MARKET + ("market" if key == "breadth" else key)
            try:
                paper = market_page(key, await api(path))
            except (OSError, RuntimeError, ValueError) as err:
                paper = Paper()
                paper.text("暂未取得本栏数据。可以切换其他栏目，稍后再回来。", "accent")
                paper.text(one(err), "dim")
            change = await view(f"行情看板 · {name}  {i+1}/{len(sections)}", paper, paging=True)
            if change not in ("next", "prev"):
                return
            i = (i + (1 if change == "next" else -1)) % len(sections)
    if page == "holdings":
        book = await api(DESK+"holdings")
        first = holdings(book)
        if not book.get("positions"):
            return await view("用户持仓", first)

        async def enrich():
            try:
                quotes = await api(MARKET+"portfolio")
            except (OSError, RuntimeError, ValueError) as err:
                quotes = err
            replace_page(first, holdings(book, quotes))

        pending = asyncio.create_task(enrich())
        try:
            return await view("用户持仓", first)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    if page == "portrait":
        return await view("风格评估 · 用户画像", portrait(await api(DESK+"assessment")))
