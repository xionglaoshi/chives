from __future__ import annotations

import json
from pathlib import Path

from strategy_hub.db import AlertStore
from strategy_hub.service import StrategyNotFound

from .support import build_service


def test_pools_and_round_use_engine_rows_and_daily_names(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    pools = service.pools("zhushenglang")
    assert pools["date"] == "2026-11-17"
    assert pools["status"] == "已计算"
    assert pools["counts"] == {"first": 1, "main": 1}
    assert pools["pools"]["first"][0]["name"] == "贵州茅台"
    assert pools["pools"]["first"][0]["priority"] == "p1"
    assert pools["pools"]["main"][0]["gain"] == 0.63

    detail = service.round("zhushenglang", "600519.SH")
    assert detail is not None
    assert detail["round"]["round_id"] == 1
    assert [event["event"] for event in detail["events"]] == ["启动", "优先级一确定", "MA10跌破"]
    assert detail["events"][0]["values"]["P_star"] == 13.5


def test_events_filter_and_levels(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    events = service.events("zhushenglang", start="2026-11-05", kinds=["优先级一确定"])
    assert events["count"] == 1
    assert events["events"][0]["level"] == "important"

    levels = service.levels("zhushenglang", "600519.SH")
    assert levels is not None
    by_key = {item["key"]: item for item in levels["levels"]}
    assert by_key["hb"]["value"] == 13.2
    assert by_key["p_star"]["value"] == 13.5
    assert by_key["s1"]["value"] == 10.2
    assert by_key["s2"]["value"] == 10.5
    assert by_key["ma10"]["value"] == 17.5
    assert "不是买卖建议" in levels["disclaimer"]


def test_unknown_strategy_is_a_typed_error(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    try:
        service.get("nope")
    except StrategyNotFound as exc:
        assert exc.strategy_id == "nope"
    else:  # pragma: no cover - assertion helper
        raise AssertionError("expected StrategyNotFound")


def test_same_event_name_twice_on_one_day_is_kept_by_source_event_id(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite")
    for event_id in (11, 12):
        store.add(
            strategy_id="zhushenglang",
            code="600519.SH",
            name="贵州茅台",
            round_id=1,
            event="支撑跌破",
            event_date="2026-11-17",
            level="info",
            rule_id="zhushenglang:支撑跌破",
            title="S1/S2",
            detail=f'{"S1" if event_id == 11 else "S2"}',
            created_at="2026-11-17T15:35:00+08:00",
            source_event_id=event_id,
        )
    rows = store.list(0, 10)
    assert len(rows) == 2
    assert [row["source_event_id"] for row in rows] == [11, 12]


def test_ingest_events_marks_important_and_info_with_cursor(databases: dict[str, Path]) -> None:
    service = build_service(databases)
    assert service.ingest_events("2026-11-17") == 3
    assert service.ingest_events("2026-11-17") == 0

    first = service.alerts_payload(0, 100)
    assert first["ok"] is True
    assert first["next_id"] == 3
    levels = {item["event"]: item["level"] for item in first["alerts"]}
    assert levels == {"优先级一确定": "important", "启动": "info", "MA10跌破": "info"}
    assert all(item["created_at"] for item in first["alerts"])
    assert json.loads(first["alerts"][0]["detail"])["strategy_id"] == "zhushenglang"

    later = service.alerts_payload(2, 100)
    assert len(later["alerts"]) == 1
    assert later["alerts"][0]["event"] == "MA10跌破"
