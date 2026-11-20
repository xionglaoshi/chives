from __future__ import annotations

from datetime import timedelta

import pytest

from chives_hub.calendar import TradingCalendar
from chives_hub.models import KIND_LABELS, Analysis, Plan
from chives_hub.signals import (
    analysis_sections,
    analysis_skipped,
    dedupe_key,
    expiry_signal,
    extract_conclusion,
    extract_detail,
    extract_direction,
    extract_points,
    is_false_positive,
    merge_since,
    plan_signal,
    resolve_snooze_until,
    signal_from_cn_alert,
    signal_from_market_alert,
    signal_payload,
    sort_signals,
)
from tests.support import NOW, at, cn_alert, market_alert


def analysis(markdown: str, status: str = "done", reason: str | None = None) -> Analysis:
    return Analysis(alert_id=1, status=status, reason=reason, file="analysis-1.md", markdown=markdown)


def test_extract_conclusion_bold() -> None:
    text = "## 分析\n\n**结论：这是误报，不包含方向信息。** 后面还有解释。\n"
    assert extract_conclusion(text) == "这是误报，不包含方向信息。"


def test_extract_conclusion_fallback_paragraph() -> None:
    text = "# 告警分析\n\n- 告警 ID：1\n\n第一段就是结论。\n\n第二段。\n"
    assert extract_conclusion(text) == "第一段就是结论。"


def test_extract_conclusion_empty() -> None:
    assert extract_conclusion("") == ""


def test_extract_conclusion_truncated() -> None:
    text = "**结论：" + ("很长" * 40) + "**"
    assert len(extract_conclusion(text)) <= 60


def test_extract_conclusion_unclosed_bold() -> None:
    text = "**结论：没有闭合的粗体\n\n后续"
    assert extract_conclusion(text).startswith("没有闭合")


def test_extract_direction_bull() -> None:
    assert extract_direction("**结论：偏多，站上均线。**") == "bull"


def test_extract_direction_bear() -> None:
    assert extract_direction("**结论：偏空，跌破支撑。**") == "bear"


def test_extract_direction_neutral() -> None:
    assert extract_direction("**结论：中性，等待方向。**") == "neutral"


def test_extract_direction_misreport_wins() -> None:
    assert extract_direction("**结论：这是误报。** 正文说偏空。") == "neutral"


def test_extract_points_skips_metadata() -> None:
    text = (
        "## 分析\n\n- 告警 ID：1\n- 代码：601099.SH\n"
        "- 关键点一\n- 关键点二\n- 关键点三\n- 关键点四\n- 关键点五\n- 关键点六\n"
    )
    points = extract_points(text)
    assert points == ["关键点一", "关键点二", "关键点三", "关键点四", "关键点五"]


def test_extract_points_empty() -> None:
    assert extract_points("没有列表") == []


def test_extract_detail_drops_conclusion() -> None:
    text = "**结论：一句话。**\n\n正文细节。"
    detail = extract_detail(text)
    assert "一句话" not in detail
    assert "正文细节" in detail


def test_analysis_sections_missing() -> None:
    payload = analysis_sections(None)
    assert payload["markdown"] == ""
    assert payload["sections"]["direction"] == "neutral"


def test_analysis_sections_present() -> None:
    payload = analysis_sections(analysis("**结论：偏多。**\n\n- 要点"))
    assert payload["sections"]["conclusion"] == "偏多。"
    assert payload["sections"]["points"] == ["要点"]


def test_analysis_skipped_dry_run() -> None:
    assert analysis_skipped(analysis("", status="skipped", reason="dry_run"))
    assert analysis_skipped(analysis("", status="done", reason="cooldown"))
    assert not analysis_skipped(analysis("", status="done"))


def test_is_false_positive() -> None:
    assert is_false_positive(analysis("**结论：误报。**"))
    assert not is_false_positive(analysis("**结论：偏多。**"))
    assert not is_false_positive(None)


def test_dedupe_key() -> None:
    assert dedupe_key("stock", "601099.SH", "r") == "stock|601099.SH|r"


def test_merge_since_normal() -> None:
    assert merge_since("risk", False, NOW) == NOW - timedelta(minutes=30)


def test_merge_since_false_positive_day() -> None:
    assert merge_since("info", True, NOW) == at(0, 0)


def test_cn_pct_up_opportunity() -> None:
    alert = cn_alert(1, rule_id="pct_up_3", rule_type="pct_change", direction="up", change_pct=3.2)
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "opportunity"
    assert signal.direction == "bull"
    assert signal.decide is True
    assert signal.severity == "L2"
    assert signal.status == "new"


def test_cn_pct_down_risk() -> None:
    alert = cn_alert(1, rule_id="pct_down_3", rule_type="pct_change", direction="down", change_pct=-3.2)
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "risk"
    assert signal.direction == "bear"
    assert signal.decide is False


def test_cn_limit_up_is_l3_opportunity() -> None:
    alert = cn_alert(1, rule_id="near_up", rule_type="limit_proximity", direction="up")
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "opportunity"
    assert signal.severity == "L3"
    assert signal.decide is True


def test_cn_limit_down_is_risk() -> None:
    alert = cn_alert(1, rule_id="near_down", rule_type="limit_proximity", direction="down")
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "risk"
    assert signal.severity == "L3"


def test_cn_volume_surge_down() -> None:
    alert = cn_alert(1, change_pct=-1.2)
    assert signal_from_cn_alert(alert, None, now=NOW).kind == "risk"


def test_cn_volume_surge_up() -> None:
    alert = cn_alert(1, change_pct=1.2)
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "opportunity"
    assert signal.direction == "bull"


def test_cn_volume_surge_flat_is_info() -> None:
    alert = cn_alert(1, change_pct=0.0)
    assert signal_from_cn_alert(alert, None, now=NOW).kind == "info"


def test_cn_price_cross_down() -> None:
    alert = cn_alert(1, rule_id="cross_16", rule_type="price_cross", direction="down")
    assert signal_from_cn_alert(alert, None, now=NOW).kind == "risk"


def test_cn_vwap_up() -> None:
    alert = cn_alert(1, rule_id="vwap", rule_type="vwap_deviation", direction="up")
    assert signal_from_cn_alert(alert, None, now=NOW).kind == "opportunity"


def test_cn_unknown_rule_info() -> None:
    alert = cn_alert(1, rule_id="x", rule_type="unknown")
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.kind == "info"
    assert signal.severity == "L1"


def test_cn_title_contains_name() -> None:
    signal = signal_from_cn_alert(cn_alert(1), None, now=NOW)
    assert "太平洋" in signal.title


def test_cn_source_fields() -> None:
    signal = signal_from_cn_alert(cn_alert(7), None, now=NOW)
    assert signal.source["alert_ids"] == [7]
    assert signal.source["label"] == "cn-watch"
    assert signal.analysis_id is None


def test_cn_invalid_alert_id() -> None:
    assert signal_from_cn_alert({"id": "x"}, None, now=NOW) is None


def test_cn_missing_code() -> None:
    assert signal_from_cn_alert({"id": 1, "code": "", "rule_id": "x"}, None, now=NOW) is None


def test_cn_with_analysis_conclusion() -> None:
    alert = cn_alert(1)
    text = "**结论：偏空，量能异常。**\n\n- 价格跌破 VWAP\n- 距跌停 5%"
    signal = signal_from_cn_alert(alert, analysis(text), now=NOW)
    assert signal.conclusion == "偏空，量能异常。"
    assert signal.direction == "bear"
    assert signal.detail_available is True
    assert "价格跌破" in signal.brief


def test_cn_false_positive_info_done() -> None:
    alert = cn_alert(1)
    text = "**结论：这次告警属于误报，不包含方向信息。**\n\n正文。"
    signal = signal_from_cn_alert(alert, analysis(text), now=NOW)
    assert signal.kind == "info"
    assert signal.status == "done"
    assert signal.decide is False
    assert signal.direction == "neutral"


def test_cn_context_spark() -> None:
    alert = cn_alert(1)
    alert["payload"] = {"spark": [1, 2, 3]}
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.context == {"type": "spark", "points": [1.0, 2.0, 3.0], "label": "盘中走势"}


def test_cn_context_rank() -> None:
    alert = cn_alert(1)
    alert["payload"] = {"rank": 3, "rank_before": 20, "amount_share_pct": 4.5}
    signal = signal_from_cn_alert(alert, None, now=NOW)
    assert signal.context["from"] == 20
    assert signal.context["to"] == 3


def test_market_r1_market_risk() -> None:
    alert = market_alert(1, rule="R1", object_type="index", code="000001.SH", name="上证指数")
    signal = signal_from_market_alert(alert, now=NOW)
    assert signal.kind == "risk"
    assert signal.object_type == "market"
    assert signal.direction == "bear"
    assert signal.decide is False


def test_market_r3_sector_decide() -> None:
    signal = signal_from_market_alert(market_alert(1, rule="R3"), now=NOW)
    assert signal.kind == "sector"
    assert signal.object_type == "sector"
    assert signal.decide is True


def test_market_r5_l1_sector_not_decide() -> None:
    signal = signal_from_market_alert(market_alert(1, rule="R5", severity="L1"), now=NOW)
    assert signal.kind == "sector"
    assert signal.decide is False


def test_market_r6_down_risk() -> None:
    alert = market_alert(
        1, rule="R6", object_type="stock", code="601099.SH", name="太平洋",
        payload={"change_pct": -3.0},
    )
    signal = signal_from_market_alert(alert, now=NOW)
    assert signal.kind == "risk"
    assert signal.object_type == "stock"


def test_market_r6_up_opportunity() -> None:
    alert = market_alert(
        1, rule="R6", object_type="stock", code="601099.SH", name="太平洋",
        payload={"change_pct": 3.0},
    )
    assert signal_from_market_alert(alert, now=NOW).kind == "opportunity"


def test_market_invalid_severity_fallback() -> None:
    signal = signal_from_market_alert(market_alert(1, severity="X"), now=NOW)
    assert signal.severity == "L2"


def test_market_missing_code() -> None:
    alert = market_alert(1)
    alert["object"] = {"type": "sector", "code": "", "name": ""}
    assert signal_from_market_alert(alert, now=NOW) is None


def test_market_analysis_id() -> None:
    alert = market_alert(1)
    alert["analysis_id"] = 9
    signal = signal_from_market_alert(alert, now=NOW)
    assert signal.analysis_id == 9


def test_sort_signals() -> None:
    rows = [
        {"id": 1, "decide": False, "severity": "L3", "ts": at(10)},
        {"id": 2, "decide": True, "severity": "L1", "ts": at(9)},
        {"id": 3, "decide": True, "severity": "L3", "ts": at(9)},
        {"id": 4, "decide": True, "severity": "L3", "ts": at(10)},
    ]
    assert [row["id"] for row in sort_signals(rows)] == [4, 3, 2, 1]


def make_plan(**overrides) -> Plan:
    data = dict(
        id=3,
        code="601099.SH",
        name="太平洋",
        kind="entry",
        status="active",
        condition={"type": "price_cross", "direction": "up", "level": 4.0},
        stop=3.5,
        rationale="突破跟进",
        source={"analysis_id": None, "label": "user"},
        proposed_by="user",
        created_at=NOW,
        expires_at=at(15, day=11),
    )
    data.update(overrides)
    return Plan(**data)


def test_plan_signal_entry() -> None:
    signal = plan_signal(make_plan(), "plan_entry", now=NOW, price=4.1)
    assert signal.kind == "plan_entry"
    assert signal.decide is True
    assert signal.object_code == "601099.SH"
    assert signal.context["type"] == "range"
    assert signal.context["price"] == 4.1
    assert signal.context["giveup"] is False
    # a triggered plan is already confirmed: only a proposal offers "确认计划"
    assert signal.primary["action"] == "ack"


def test_plan_signal_giveup_context() -> None:
    signal = plan_signal(make_plan(kind="giveup"), "plan_giveup", now=NOW, price=3.4)
    assert signal.kind == "plan_giveup"
    assert signal.context["giveup"] is True
    assert signal.primary["action"] == "ack"


def test_plan_signal_other_not_decide() -> None:
    signal = plan_signal(make_plan(kind="watch"), "plan_other", now=NOW, price=None)
    assert signal.kind == "plan_other"
    assert signal.decide is False


def test_expiry_signal() -> None:
    signal = expiry_signal(make_plan(), now=NOW)
    assert signal.kind == "info"
    assert signal.decide is False
    assert "过期" in signal.title


def test_signal_payload_fields() -> None:
    signal = signal_from_cn_alert(cn_alert(1), None, now=NOW)
    payload = signal_payload(
        {
            "id": 1,
            "ts": signal.ts,
            "decide": signal.decide,
            "severity": signal.severity,
            "status": signal.status,
            "snooze_until": None,
            "object_type": signal.object_type,
            "object_code": signal.object_code,
            "object_name": signal.object_name,
            "title": signal.title,
            "direction": signal.direction,
            "conclusion": signal.conclusion,
            "brief": signal.brief,
            "context": signal.context,
            "source": signal.source,
            "merged_count": signal.merged_count,
            "primary": signal.primary,
            "detail_available": signal.detail_available,
            "kind": signal.kind,
        }
    )
    assert payload["kind_label"] == "风险"
    assert payload["direction_label"] == "偏空"
    assert payload["object"]["type"] == "stock"


def test_snooze_30m() -> None:
    assert resolve_snooze_until("30m", now=NOW, calendar=TradingCalendar.from_file(None)) == at(10, 30)


def test_snooze_close() -> None:
    assert resolve_snooze_until("close", now=NOW, calendar=TradingCalendar.from_file(None)) == at(15)


def test_snooze_next_open() -> None:
    assert resolve_snooze_until("next_open", now=NOW, calendar=TradingCalendar.from_file(None)) == at(
        9, 30, day=5
    )


def test_snooze_iso() -> None:
    target = "2026-11-04T11:00:00+08:00"
    assert resolve_snooze_until(target, now=NOW, calendar=TradingCalendar.from_file(None)) == at(11)


def test_snooze_past_iso() -> None:
    with pytest.raises(ValueError):
        resolve_snooze_until("2026-11-04T09:00:00+08:00", now=NOW, calendar=TradingCalendar.from_file(None))


def test_snooze_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_snooze_until("tomorrow", now=NOW, calendar=TradingCalendar.from_file(None))


def test_snooze_too_long() -> None:
    with pytest.raises(ValueError):
        resolve_snooze_until("2027-01-01T00:00:00+08:00", now=NOW, calendar=TradingCalendar.from_file(None))


def test_market_aggregated_r5_direction() -> None:
    alert = market_alert(
        1, rule="R5", object_type="sector", code="BK0479", name="钢铁",
        payload={"rule_id": "R5", "objects": [
            {"type": "sector", "code": "BK0479", "name": "钢铁",
             "metrics": {"direction": "下穿", "sector_change_pct": -1.2}}
        ]},
    )
    signal = signal_from_market_alert(alert, now=NOW)
    assert signal.direction == "bear"
    assert signal.kind == "sector"


def test_market_aggregated_r3_change() -> None:
    alert = market_alert(
        1, rule="R3", payload={"rule_id": "R3", "objects": [
            {"type": "sector", "code": "BK0486", "name": "传媒",
             "metrics": {"sector_change_pct": 1.7}}
        ]},
    )
    assert signal_from_market_alert(alert, now=NOW).direction == "bull"


def test_market_rank_context_from_metrics() -> None:
    alert = market_alert(
        1, rule="R3", payload={"rule_id": "R3", "objects": [
            {"type": "sector", "code": "BK0486", "name": "传媒",
             "metrics": {"rank": 1, "rank_30m_ago": 19, "change_pct": 1.69}}
        ]},
    )
    signal = signal_from_market_alert(alert, now=NOW)
    assert signal.context == {"type": "rank", "from": 19, "to": 1, "share_pct": None, "spark": []}


NEW_FORMAT = (
    "**结论：放量上冲但离涨停还远，暂不追，等回踩 VWAP 再看。**\n"
    "方向：中性\n"
    "要点：\n"
    "- 14:05 现价 11.2，相对 VWAP +1.8%\n"
    "- 距涨停 6.1%\n"
    "- 近 10 日无重大公告\n"
    "---\n"
    "## 触发了什么\n"
    "规则 R3 触发……\n"
    "\n"
    "## 关键数据\n"
    "| 指标 | 值 |\n"
    "|---|---|\n"
    "| 现价 | 11.2 |\n"
)


def test_new_format_conclusion_is_full_bold_sentence() -> None:
    assert extract_conclusion(NEW_FORMAT) == "放量上冲但离涨停还远，暂不追，等回踩 VWAP 再看。"


@pytest.mark.parametrize(
    ("word", "want"),
    [("偏多", "bull"), ("偏空", "bear"), ("中性", "neutral"), ("误报", "neutral")],
)
def test_new_format_direction_from_line(word: str, want: str) -> None:
    assert extract_direction(NEW_FORMAT.replace("方向：中性", f"方向：{word}")) == want


def test_new_format_explicit_direction_wins_over_conclusion_word() -> None:
    text = NEW_FORMAT.replace("暂不追", "偏空但暂不追").replace("方向：中性", "方向：偏多")
    assert extract_direction(text) == "bull"


def test_new_format_points_come_from_the_points_block_only() -> None:
    assert extract_points(NEW_FORMAT) == [
        "14:05 现价 11.2，相对 VWAP +1.8%",
        "距涨停 6.1%",
        "近 10 日无重大公告",
    ]


def test_new_format_points_stop_at_divider() -> None:
    text = NEW_FORMAT + "- 正文里的列表项不应成为要点\n"
    assert len(extract_points(text)) == 3


def test_new_format_bold_points_header() -> None:
    assert extract_points(NEW_FORMAT.replace("要点：", "**要点：**")) == extract_points(NEW_FORMAT)


def test_new_format_empty_points_block() -> None:
    text = NEW_FORMAT.replace(
        "- 14:05 现价 11.2，相对 VWAP +1.8%\n- 距涨停 6.1%\n- 近 10 日无重大公告\n", ""
    )
    assert extract_points(text) == []


def test_new_format_detail_is_after_divider() -> None:
    detail = extract_detail(NEW_FORMAT)
    assert "触发了什么" in detail
    assert "关键数据" in detail and "现价 | 11.2" in detail
    assert "方向：" not in detail and "要点" not in detail
    assert "结论" not in detail


def test_new_format_detail_truncated_to_4000() -> None:
    text = NEW_FORMAT + ("长" * 8000)
    assert len(extract_detail(text)) <= 4000


def test_old_format_without_direction_line_still_falls_back() -> None:
    text = "判断：不追。\n\n## 触发了什么\n规则触发……偏空\n"
    assert extract_direction(text) == "bear"
    assert extract_points(text) == []
    assert "不追" in extract_detail(text)


def test_analysis_sections_new_format() -> None:
    payload = analysis_sections(analysis(NEW_FORMAT))["sections"]
    assert payload["direction"] == "neutral"
    assert payload["conclusion"].startswith("放量上冲")
    assert payload["points"][0].startswith("14:05")
    assert "触发了什么" in payload["detail"]


# -- v1.1 kinds ----------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "decide", "action"),
    [
        ("card_proposal", True, "confirm_card"),
        ("card_state", True, "open_card"),
        ("review_ready", False, "open_review"),
        ("discipline", True, "ack"),
    ],
)
def test_v11_kind_mapping(kind: str, decide: bool, action: str) -> None:
    from chives_hub.signals import _decide, _primary

    assert _decide(kind, "L2") is decide
    assert _primary(kind)["action"] == action
    assert KIND_LABELS[kind]
