from __future__ import annotations

from pathlib import Path

import pytest

from cn_extra_mcp import service

FIXTURE = Path(__file__).parent / "fixtures/tencent_quotes.txt"
BJ_FIXTURE = Path(__file__).parent / "fixtures/tencent_quotes_bj.txt"


@pytest.fixture
def captured(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    text = FIXTURE.read_text(encoding="utf-8")

    def fake_fetch(symbols: list[str], timeout: float = 8.0) -> str:
        calls.append(list(symbols))
        return text

    monkeypatch.setattr(service.sources, "fetch_tencent_text", fake_fetch)
    return calls


@pytest.fixture
def captured_bj(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    text = BJ_FIXTURE.read_text(encoding="utf-8")

    def fake_fetch(symbols: list[str], timeout: float = 8.0) -> str:
        calls.append(list(symbols))
        return text

    monkeypatch.setattr(service.sources, "fetch_tencent_text", fake_fetch)
    return calls


def test_real_tencent_fixture_parsing(captured) -> None:
    payload = service.cn_get_quote_snapshot(["002553.SZ", "600000", "002553"])
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert captured == [["sz002553", "sh600000"]]
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) == 2

    nanfang = payload["data"][0]
    assert nanfang["code"] == "002553.SZ"
    assert nanfang["name"] == "南方精工"
    assert nanfang["price"] == 15.83
    assert nanfang["prev_close"] == 15.07
    assert nanfang["open"] == 15.07
    assert nanfang["high"] == 16.05
    assert nanfang["low"] == 14.30
    assert nanfang["change_pct"] == 5.04
    assert nanfang["volume_lots"] == 153401
    assert nanfang["amount_wan"] == 23251
    assert nanfang["time"] == "2026-11-02 13:52:39"

    pufa = payload["data"][1]
    assert pufa["code"] == "600000.SH"
    assert pufa["name"] == "浦发银行"
    assert pufa["price"] == 10.15
    assert pufa["limit_up"] == 11.02
    assert pufa["limit_down"] == 9.02
    assert nanfang["limit_up"] == 16.58
    assert nanfang["limit_down"] == 13.56
    assert "warnings" not in payload
    assert "warning_message" not in payload


def test_bj_quote_parsing_with_limits(captured_bj) -> None:
    payload = service.cn_get_quote_snapshot(["920418.BJ"])
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert captured_bj == [["bj920418"]]
    assert "warnings" not in payload
    assert "warning_message" not in payload

    item = payload["data"][0]
    assert item["code"] == "920418.BJ"
    assert item["name"] == "苏轴股份"
    assert item["price"] == 18.53
    assert item["prev_close"] == 18.74
    assert item["open"] == 18.99
    assert item["high"] == 19.11
    assert item["low"] == 18.08
    assert item["change_pct"] == -1.12
    assert item["volume_lots"] == 30205
    assert item["amount_wan"] == 5625.96
    assert item["time"] == "2026-11-02 15:34:21"
    assert item["limit_up"] == 24.36
    assert item["limit_down"] == 13.12


def test_bare_bj_code_is_deduplicated(captured_bj) -> None:
    payload = service.cn_get_quote_snapshot(["920418", "920418.BJ"])
    assert captured_bj == [["bj920418"]]
    assert len(payload["data"]) == 1
    assert payload["data"][0]["code"] == "920418.BJ"


def test_legacy_bj_quote_warns(captured_bj) -> None:
    payload = service.cn_get_quote_snapshot(["430418.BJ"])
    assert payload["ok"] is True
    assert captured_bj == [["bj430418"]]
    assert payload["warnings"] == ["legacy_bj_code"]
    assert "北交所代码已迁移为 92xxxx" in payload["warning_message"]
    assert "旧代码数据可能停更" in payload["warning_message"]

    item = payload["data"][0]
    assert item["code"] == "430418.BJ"
    assert item["name"] == "苏轴股份"
    assert item["price"] == 18.25
    assert item["time"] == "2026-11-02 09:00:00"
    assert item["limit_up"] is None
    assert item["limit_down"] is None


def test_missing_limit_fields_are_null(monkeypatch) -> None:
    text = BJ_FIXTURE.read_text(encoding="utf-8")
    fields = text.split('"')[1].split("~")[:40]
    line = 'v_bj920418="' + "~".join(fields) + '";'
    monkeypatch.setattr(
        service.sources, "fetch_tencent_text", lambda symbols, timeout=8.0: line
    )
    item = service.cn_get_quote_snapshot(["920418.BJ"])["data"][0]
    assert item["code"] == "920418.BJ"
    assert item["limit_up"] is None
    assert item["limit_down"] is None


def test_bad_inputs(captured) -> None:
    assert service.cn_get_quote_snapshot([])["error"]["code"] == "invalid_argument"
    assert service.cn_get_quote_snapshot(["002553"] * 21)["error"]["code"] == "invalid_argument"
    assert service.cn_get_quote_snapshot(["abc"])["error"]["code"] == "invalid_symbol"
    assert service.cn_get_quote_snapshot("002553")["error"]["code"] == "invalid_argument"
    assert captured == []


def test_missing_row_and_upstream_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        service.sources, "fetch_tencent_text", lambda symbols, timeout=8.0: ""
    )
    payload = service.cn_get_quote_snapshot(["002553"])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "upstream_error"

    def boom(symbols, timeout=8.0):
        raise OSError("network down")

    monkeypatch.setattr(service.sources, "fetch_tencent_text", boom)
    payload = service.cn_get_quote_snapshot(["002553"])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "upstream_error"
