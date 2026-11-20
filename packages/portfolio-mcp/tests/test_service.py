from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from portfolio_mcp.quotes import Quote
from portfolio_mcp.service import PortfolioService


def _rows(*codes: str, qty: int = 1000, cost: float = 9.5) -> list[dict[str, object]]:
    return [
        {"code": code, "name": f"测试{code}", "qty": qty, "cost_price": cost}
        for code in codes
    ]


def _commit(service: PortfolioService, rows: list[dict[str, object]], mode: str = "replace") -> dict:
    preview = service.import_preview({"rows": rows, "mode": mode})
    assert preview["ok"] is True, preview
    return service.import_commit({"confirm_token": preview["data"]["confirm_token"]})


def test_get_empty(service: PortfolioService) -> None:
    payload = service.get({})
    assert payload["status"] == "empty"
    assert payload["data"]["empty"] is True
    assert payload["data"]["count"] == 0
    assert payload["data"]["hint"]
    assert payload["private"] is True
    assert payload["data"]["private"] is True
    assert payload["data"]["untrusted_text"] is False


def test_parse_csv_service(service: PortfolioService) -> None:
    text = "代码,名称,数量,成本价\n600000,浦发银行,1000,9.5\n"
    payload = service.parse_csv({"text": text})
    assert payload["status"] == "ready"
    assert payload["data"]["rows"][0]["code"] == "600000.SH"
    assert payload["data"]["private"] is True


def test_parse_csv_sensitive_error_does_not_echo(service: PortfolioService) -> None:
    account = "1" * 15
    payload = service.parse_csv({"text": f"代码,名称,数量,成本价,资金账号\n600000,浦发,1000,9.5,{account}\n"})
    assert payload["error"]["code"] == "sensitive_text"
    assert account not in json.dumps(payload, ensure_ascii=False)


def test_preview_does_not_write(service: PortfolioService, store) -> None:
    payload = service.import_preview({"rows": _rows("600000")})
    assert payload["ok"] is True
    assert payload["data"]["summary"]["added"] == 1
    assert payload["data"]["confirm_token"]
    assert not store.portfolio_path.exists()


def test_replace_diff(service: PortfolioService) -> None:
    _commit(service, _rows("600000", "000001", "002553"))
    rows = [
        {"code": "600000", "name": "测试600000", "qty": 1000, "cost_price": 9.5},
        {"code": "000001", "name": "测试000001", "qty": 1500, "cost_price": 9.5},
        {"code": "300750", "name": "测试300750", "qty": 100, "cost_price": 200.0},
    ]
    preview = service.import_preview({"rows": rows, "mode": "replace"})
    data = preview["data"]
    assert data["summary"] == {
        "added": 1,
        "changed": 1,
        "removed": 1,
        "unchanged": 1,
        "total_after": 3,
    }
    assert data["changed"][0]["code"] == "000001.SZ"
    assert data["changed"][0]["fields"] == ["qty"]
    assert data["removed"][0]["code"] == "002553.SZ"


def test_merge_diff_keeps_absent_positions(service: PortfolioService) -> None:
    _commit(service, _rows("600000", "000001"))
    preview = service.import_preview(
        {
            "rows": [
                {"code": "000001", "name": "测试000001", "qty": 1500, "cost_price": 9.5},
                {"code": "300750", "name": "测试300750", "qty": 100, "cost_price": 200.0},
            ],
            "mode": "merge",
        }
    )
    data = preview["data"]
    assert data["summary"] == {
        "added": 1,
        "changed": 1,
        "removed": 0,
        "unchanged": 0,
        "total_after": 3,
    }
    committed = service.import_commit({"confirm_token": data["confirm_token"]})
    assert committed["data"]["after_count"] == 3
    assert [row["code"] for row in committed["data"]["positions"]] == [
        "600000.SH",
        "000001.SZ",
        "300750.SZ",
    ]


def test_commit_preserves_cash_and_sets_as_of(service: PortfolioService) -> None:
    service.set_cash({"cash": 5000})
    committed = _commit(service, _rows("600000"))
    assert committed["data"]["as_of"] == date.today().isoformat()
    data = service.get({})["data"]
    assert data["cash"] == 5000.0
    assert data["as_of"] == date.today().isoformat()


def test_token_is_one_time(service: PortfolioService) -> None:
    ticket = service.import_preview({"rows": _rows("600000")})["data"]["confirm_token"]
    assert service.import_commit({"confirm_token": ticket})["ok"] is True
    second = service.import_commit({"confirm_token": ticket})
    assert second["error"]["code"] == "invalid_token"


def test_token_expires(store, clock) -> None:
    service = PortfolioService(store, quotes=None, clock=clock, token_ttl=10)
    ticket = service.import_preview({"rows": _rows("600000")})["data"]["confirm_token"]
    clock.advance(10)
    payload = service.import_commit({"confirm_token": ticket})
    assert payload["error"]["code"] == "invalid_token"
    assert not store.portfolio_path.exists()


def test_tampered_token_is_rejected(service: PortfolioService) -> None:
    ticket = service.import_preview({"rows": _rows("600000")})["data"]["confirm_token"]
    payload = service.import_commit({"confirm_token": ticket + "x"})
    assert payload["error"]["code"] == "invalid_token"


def test_tampered_pending_rows_are_rejected(service: PortfolioService) -> None:
    ticket = service.import_preview({"rows": _rows("600000")})["data"]["confirm_token"]
    service._pending[ticket].rows[0]["qty"] = 999999
    payload = service.import_commit({"confirm_token": ticket})
    assert payload["error"]["code"] == "invalid_token"


def test_tokens_are_bound_to_their_own_rows_and_mode(service: PortfolioService) -> None:
    first = service.import_preview({"rows": _rows("600000"), "mode": "replace"})
    second = service.import_preview({"rows": _rows("000001"), "mode": "merge"})
    assert first["data"]["plan_hash"] != second["data"]["plan_hash"]

    committed = service.import_commit({"confirm_token": first["data"]["confirm_token"]})
    assert [row["code"] for row in committed["data"]["positions"]] == ["600000.SH"]
    assert service.import_commit({"confirm_token": first["data"]["confirm_token"]})["error"][
        "code"
    ] == "invalid_token"


def test_update_position(service: PortfolioService) -> None:
    _commit(service, _rows("600000", qty=1000, cost=9.5))
    payload = service.update_position({"code": "600000", "fields": {"qty": 800, "cost_price": 9.8}})
    assert payload["ok"] is True
    assert payload["data"]["before"]["qty"] == 1000
    assert payload["data"]["after"]["qty"] == 800
    assert payload["data"]["changed"] == ["cost_price", "qty"]
    stored = service.get({})["data"]["positions"][0]
    assert stored["qty"] == 800


def test_update_rejects_available_above_qty_and_unknown_code(service: PortfolioService) -> None:
    _commit(
        service,
        [
            {
                "code": "600000",
                "name": "测试600000",
                "qty": 1000,
                "available_qty": 800,
                "cost_price": 9.5,
            }
        ],
    )
    payload = service.update_position({"code": "600000", "fields": {"qty": 100}})
    assert payload["error"]["code"] == "invalid_value"
    assert payload["data"]["field"] == "available_qty"

    payload = service.update_position({"code": "000001", "fields": {"qty": 100}})
    assert payload["error"]["code"] == "not_found"

    payload = service.update_position({"code": "600000", "fields": {"code": "000001"}})
    assert payload["error"]["code"] == "invalid_value"


def test_update_rejects_sensitive_note(service: PortfolioService) -> None:
    _commit(service, _rows("600000"))
    account = "2" * 15
    payload = service.update_position({"code": "600000", "fields": {"note": account}})
    assert payload["error"]["code"] == "sensitive_text"
    assert account not in json.dumps(payload, ensure_ascii=False)


def test_remove_position(service: PortfolioService) -> None:
    _commit(service, _rows("600000", "000001"))
    payload = service.remove_position({"code": "000001"})
    assert payload["ok"] is True
    assert payload["data"]["removed"]["code"] == "000001.SZ"
    assert payload["data"]["before"]["code"] == "000001.SZ"
    assert payload["data"]["after"] is None
    assert payload["data"]["after_count"] == 1
    assert service.remove_position({"code": "000001"})["error"]["code"] == "not_found"


def test_set_cash_and_clear(service: PortfolioService) -> None:
    _commit(service, _rows("600000"))
    assert service.set_cash({"cash": 5000})["data"]["cash_after_cny"] == 5000.0
    assert service.set_cash({"cash": -1})["error"]["code"] == "invalid_value"

    rejected = service.clear({})
    assert rejected["error"]["code"] == "confirmation_required"
    assert service.get({})["data"]["count"] == 1

    assert service.clear({"confirm": False})["error"]["code"] == "confirmation_required"
    cleared = service.clear({"confirm": True})
    assert cleared["data"]["cleared_positions"] == 1
    after = service.get({})
    assert after["data"]["positions"] == []
    assert after["data"]["cash"] is None
    assert after["data"]["as_of"] is None


def test_preview_rejects_bad_mode_and_rows(service: PortfolioService) -> None:
    assert service.import_preview({"rows": _rows("600000"), "mode": "append"})["error"][
        "code"
    ] == "invalid_argument"
    assert service.import_preview({"rows": _rows("900901")})["error"]["code"] == "invalid_code"


def test_preview_rejects_over_100_positions(service: PortfolioService) -> None:
    rows = _rows(*[f"6{index:05d}" for index in range(101)])
    payload = service.import_preview({"rows": rows})
    assert payload["error"]["code"] == "too_many_positions"


def test_merge_cannot_exceed_100(service: PortfolioService) -> None:
    rows = _rows(*[f"6{index:05d}" for index in range(100)])
    _commit(service, rows)
    payload = service.import_preview({"rows": _rows("000001"), "mode": "merge"})
    assert payload["error"]["code"] == "too_many_positions"


def test_concurrent_commits_do_not_corrupt_the_file(service: PortfolioService, store) -> None:
    tokens = []
    for index in range(8):
        preview = service.import_preview(
            {"rows": _rows(f"6{index:05d}"), "mode": "merge"}
        )
        tokens.append(preview["data"]["confirm_token"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda ticket: service.import_commit({"confirm_token": ticket}), tokens)
        )
    assert all(result["ok"] for result in results)

    doc = json.loads(store.portfolio_path.read_text(encoding="utf-8"))
    assert len(doc["positions"]) == 8
    assert service.get({})["data"]["count"] == 8


def test_corrupt_file_warning_is_surfaced(service: PortfolioService, store) -> None:
    store.profile_dir.mkdir(parents=True, exist_ok=True)
    store.portfolio_path.write_text("{oops", encoding="utf-8")
    payload = service.get({})
    assert payload["status"] == "empty"
    assert "portfolio_corrupt" in payload["warnings"]


class _StubQuotes:
    def __init__(self, quotes: dict[str, Quote]) -> None:
        self.quotes = quotes
        self.calls: list[list[str]] = []

    def fetch(self, codes: list[str]) -> dict[str, Quote]:
        self.calls.append(list(codes))
        return {code: self.quotes[code] for code in codes if code in self.quotes}


def test_preview_quote_warnings(store) -> None:
    stub = _StubQuotes(
        {
            "600000.SH": Quote(
                code="600000.SH",
                name="别的名字",
                price=10.0,
                prev_close=9.8,
                change_pct=2.0,
                time="2026-11-03 10:00:00",
                limit_up=None,
                limit_down=None,
            )
        }
    )
    service = PortfolioService(store, quotes=stub)
    payload = service.import_preview(
        {
            "rows": [
                {"code": "600000", "name": "浦发银行", "qty": 50, "cost_price": 30.0},
                {"code": "000001", "name": "平安银行", "qty": 1000, "cost_price": 10.0},
            ]
        }
    )
    codes = payload["warnings"]
    assert "name_mismatch" in codes
    assert "cost_deviation_high" in codes
    assert "qty_suspected_lots" in codes
    assert "quote_missing" in codes
    assert stub.calls == [["600000.SH", "000001.SZ"]]


def test_add_position_creates_new_row(service: PortfolioService) -> None:
    payload = service.add_position(
        {"code": "600000", "quantity": 1000, "cost": 9.5, "name": "浦发银行"}
    )
    assert payload["ok"] is True
    data = payload["data"]
    assert data["action"] == "added"
    assert data["before"] is None
    assert data["after"]["code"] == "600000.SH"
    assert data["after"]["qty"] == 1000
    assert data["after"]["cost_price"] == 9.5
    assert data["count"] == 1
    assert service.get({})["data"]["count"] == 1


def test_add_position_without_name_falls_back_to_code(service: PortfolioService) -> None:
    payload = service.add_position({"code": "600000", "quantity": 1000, "cost": 9.5})
    assert payload["ok"] is True
    assert payload["data"]["after"]["name"] == "600000.SH"


def test_add_position_merges_with_weighted_cost(service: PortfolioService) -> None:
    first = service.add_position(
        {"code": "600000", "quantity": 1000, "cost": 9.5, "name": "浦发银行"}
    )
    assert first["ok"] is True
    payload = service.add_position({"code": "600000", "quantity": 500, "cost": 10.5})
    assert payload["ok"] is True
    data = payload["data"]
    assert data["action"] == "merged"
    assert data["before"]["qty"] == 1000
    assert data["after"]["qty"] == 1500
    assert data["after"]["cost_price"] == 9.8333
    assert data["after"]["name"] == "浦发银行"
    assert "14750.0000" in data["formula"]
    assert "9.8333" in data["formula"]
    assert data["count"] == 1
    assert service.get({})["data"]["count"] == 1


def test_add_position_merge_false_is_rejected(service: PortfolioService) -> None:
    service.add_position(
        {"code": "600000", "quantity": 1000, "cost": 9.5, "name": "浦发银行"}
    )
    payload = service.add_position(
        {"code": "600000", "quantity": 500, "cost": 10.5, "merge": False}
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid"
    assert "portfolio_update_position" in payload["error"]["message"]
    stored = service.get({})["data"]["positions"][0]
    assert stored["qty"] == 1000
    assert stored["cost_price"] == 9.5


def test_add_position_validates_input(service: PortfolioService) -> None:
    assert service.add_position({"code": "600000", "quantity": 0, "cost": 9.5})["error"][
        "code"
    ] == "invalid_value"
    assert service.add_position({"code": "600000", "quantity": 100, "cost": 0})["error"][
        "code"
    ] == "invalid_value"
    assert service.add_position({"code": "900901", "quantity": 100, "cost": 9.5})["error"][
        "code"
    ] == "invalid_code"
    assert service.add_position(
        {"code": "600000", "quantity": 100, "cost": 9.5, "unknown": 1}
    )["error"]["code"] == "invalid_argument"
    assert service.add_position(
        {"code": "600000", "quantity": 100, "cost": 9.5, "merge": "yes"}
    )["error"]["code"] == "invalid_value"


def test_add_position_rejects_account_like_text(service: PortfolioService) -> None:
    account = "4" * 15
    payload = service.add_position(
        {"code": "600000", "quantity": 100, "cost": 9.5, "note": account}
    )
    assert payload["error"]["code"] == "sensitive_text"
    assert account not in json.dumps(payload, ensure_ascii=False)
    assert service.get({})["data"]["count"] == 0


def test_add_position_name_mismatch_warns_but_writes(store) -> None:
    stub = _StubQuotes(
        {
            "600000.SH": Quote(
                code="600000.SH",
                name="别的名字",
                price=10.0,
                prev_close=9.8,
                change_pct=2.0,
                time="2026-11-03 10:00:00",
                limit_up=None,
                limit_down=None,
            )
        }
    )
    service = PortfolioService(store, quotes=stub)
    payload = service.add_position(
        {"code": "600000", "quantity": 1000, "cost": 9.5, "name": "浦发银行"}
    )
    assert payload["ok"] is True
    assert "name_mismatch" in payload["warnings"]
    stored = service.get({})["data"]["positions"][0]
    assert stored["name"] == "浦发银行"
    assert stored["qty"] == 1000
