from __future__ import annotations

import json
from datetime import date, datetime

from chives_data import config
from chives_data.sources import parse_global_sina, parse_global_tencent
from fakes import CN, FIXTURES, FakeSources, make_service, minute_rows, tencent_fixture_rows


def _service() -> tuple:
    sources = FakeSources()
    sources.quote_tencent = tencent_fixture_rows()
    sources.daily_sina = [
        {
            "date": "2026-11-03",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "volume_shares": 123400,
            "amount_yuan": 1250000.0,
            "turnover_pct": 1.2,
        }
    ]
    sources.minutes_sina = minute_rows(
        [("2026-11-03 09:31:00", 10.0, 10.1, 9.9, 10.0, 100, 1000.0)]
    )
    now = datetime(2026, 11, 17, 16, 0, tzinfo=CN)
    sources.global_tencent_rows = parse_global_tencent(
        (FIXTURES / "global" / "tencent_global.txt").read_text(encoding="utf-8"), now=now
    )
    sources.global_sina_rows = parse_global_sina(
        (FIXTURES / "global" / "sina_global.txt").read_text(encoding="utf-8"), now=now
    )
    sources.rates = {
        "us10y": {date(2026, 11, 14): 4.2, date(2026, 11, 17): 4.25},
        "cn10y": {date(2026, 11, 14): 1.8, date(2026, 11, 17): 1.82},
    }
    return make_service(sources, now=now), sources


def _calls() -> list[tuple[str, dict]]:
    return [
        ("market_quote", {"codes": ["600000", "002553"]}),
        ("market_bars", {"code": "600519", "start": "2026-11-01", "end": "2026-11-10"}),
        ("market_bars", {"code": "600519", "interval": "1m", "start": "2026-11-03", "end": "2026-11-03"}),
        ("market_intraday", {"code": "600519", "date": "2026-11-03"}),
        ("market_global", {"groups": ["us_index", "a50", "fx", "rates"]}),
        ("market_global", {"symbols": ["usNVDA"]}),
    ]


def test_every_envelope_is_free_of_implementation_words():
    service, _ = _service()
    for tool, args in _calls():
        payload = service.call(tool, args)
        assert payload["status"] in {"ok", "partial", "unavailable"}
        text = json.dumps(payload, ensure_ascii=False).lower()
        for word in config.FORBIDDEN_OUTPUT:
            assert word.lower() not in text, (tool, word)
        assert "source" not in _keys(payload)


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_envelope_always_has_the_four_required_fields():
    service, _ = _service()
    for tool, args in _calls():
        payload = service.call(tool, args)
        assert set(payload) >= {"status", "as_of", "data", "stale"}
        assert payload["stale"] is False
        if payload["status"] == "unavailable":
            assert payload.get("message")


def test_parameter_errors_are_unavailable_not_protocol_errors():
    service, _ = _service()
    for tool in ("market_quote", "market_bars", "market_intraday", "market_global"):
        payload = service.call(tool, {})
        assert payload["status"] == "unavailable"
        assert isinstance(payload["message"], str) and payload["message"]
