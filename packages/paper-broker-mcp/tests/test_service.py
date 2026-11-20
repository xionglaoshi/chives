"""Behavioral tests for the simulated broker and its append-only ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_broker_mcp.service import PaperBroker

AT_OPEN = "2026-11-03T10:00:00+08:00"
AT_NEXT_DAY = "2026-11-04T10:00:00+08:00"
CODE = "600000.SH"
STAR = "688001.SH"


def quote(price: float, *, up: float = 11.0, down: float = 9.0, prev: float = 10.0, when: str = AT_OPEN) -> dict:
    return {"price": price, "prev_close": prev, "limit_up": up, "limit_down": down, "time": when}


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.quotes = root / "quotes.json"
        self.set_quotes()

    def set_quotes(self, *, price: float = 10.0, star: float = 10.0, up: float = 11.0, down: float = 9.0, when: str = AT_OPEN) -> None:
        self.quotes.write_text(
            json.dumps({CODE: quote(price, up=up, down=down, when=when), STAR: quote(star, up=up, down=down, when=when)}),
            encoding="utf-8",
        )

    def broker(self) -> PaperBroker:
        return PaperBroker(state_dir=self.state, test_mode=True, quote_file=self.quotes)


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


async def place(fx: Fixture, broker: PaperBroker, **kwargs):
    args = {"code": CODE, "side": "buy", "quantity": 100, "as_of": AT_OPEN}
    args.update(kwargs)
    body = await broker.async_place_order(**args)
    return body, body.get("data", {}).get("order", {})


def code_of(body: dict) -> str:
    return (body.get("error") or {}).get("code", "")


async def test_fresh_account(fx: Fixture) -> None:
    body = await fx.broker().async_account()
    data = body["data"]
    assert body["simulated"] is True and body["source"] == "paper-broker"
    assert data["initial_cash"] == 1_000_000.00
    assert data["cash"] == 1_000_000.00
    assert data["positions"] == []
    assert data["currency"] == "CNY"


async def test_buy_fees_cash_and_t_plus_one(fx: Fixture) -> None:
    broker = fx.broker()
    body, order = await place(fx, broker, quantity=1000)
    assert order["status"] == "filled"
    assert order["fill_price"] == 10.0
    assert order["fees"] == {"commission": 5.0, "transfer_fee": 0.1, "stamp_duty": 0.0}
    assert order["net_cash_change"] == -10005.10

    account = (await broker.async_account())["data"]
    assert account["cash"] == 989_994.90
    assert account["positions"] == [
        {"code": CODE, "quantity": 1000, "sellable_quantity": 0, "avg_cost": 10.0051}
    ]

    body, order = await place(fx, broker, side="sell", quantity=500, as_of="2026-11-03T11:00:00+08:00")
    assert order["status"] == "rejected"
    assert code_of(body) == "t_plus_1"


async def test_next_day_sell_cash_matches_hand_calculation(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    fx.set_quotes(price=11.0, when=AT_NEXT_DAY)
    body, order = await place(fx, broker, side="sell", quantity=1000, as_of=AT_NEXT_DAY)
    assert order["status"] == "filled"
    assert order["fees"] == {"commission": 5.0, "transfer_fee": 0.11, "stamp_duty": 5.50}
    assert order["net_cash_change"] == 10989.39
    account = (await broker.async_account())["data"]
    assert account["cash"] == 1_000_984.29
    assert account["positions"] == []


async def test_board_lot_rules(fx: Fixture) -> None:
    broker = fx.broker()
    body, _ = await place(fx, broker, quantity=150)
    assert code_of(body) == "lot_size"

    body, _ = await place(fx, broker, code=STAR, quantity=100)
    assert code_of(body) == "lot_size"
    body, order = await place(fx, broker, code=STAR, quantity=200)
    assert order["status"] == "filled"


async def test_odd_lot_sell_must_clear_the_position(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    body, _ = await place(fx, broker, side="sell", quantity=150, as_of=AT_NEXT_DAY)
    assert code_of(body) == "lot_size"
    body, order = await place(fx, broker, side="sell", quantity=1000, as_of=AT_NEXT_DAY)
    assert order["status"] == "filled"


async def test_price_limit_and_marketability(fx: Fixture) -> None:
    broker = fx.broker()
    fx.set_quotes(price=11.5)
    body, _ = await place(fx, broker, quantity=100)
    assert code_of(body) == "price_limit"

    fx.set_quotes(price=10.0)
    body, _ = await place(fx, broker, quantity=100, price=9.5)
    assert code_of(body) == "not_marketable"
    body, _ = await place(fx, broker, quantity=100, price=12.0)
    assert code_of(body) == "price_limit"

    fx.set_quotes(price=10.0)
    body, order = await place(fx, broker, quantity=100, price=10.5)
    assert order["status"] == "filled"
    assert order["fill_price"] == 10.0


async def test_market_hours(fx: Fixture) -> None:
    broker = fx.broker()
    for moment in ("2026-11-03T12:00:00+08:00", "2026-11-03T09:29:59+08:00", "2026-11-07T10:00:00+08:00"):
        body, _ = await place(fx, broker, quantity=100, as_of=moment)
        assert code_of(body) == "market_closed"
    body, order = await place(fx, broker, quantity=100, as_of="2026-11-03T15:00:00+08:00")
    assert order["status"] == "filled"


async def test_insufficient_cash(fx: Fixture) -> None:
    broker = fx.broker()
    body, _ = await place(fx, broker, quantity=1_000_000)
    assert code_of(body) == "insufficient_cash"


async def test_no_quote(fx: Fixture) -> None:
    broker = fx.broker()
    fx.quotes.write_text("{}", encoding="utf-8")
    body, _ = await place(fx, broker, quantity=100)
    assert code_of(body) == "no_quote"


async def test_kill_switch_blocks_without_restart(fx: Fixture) -> None:
    broker = fx.broker()
    assert (await place(fx, broker, quantity=100))[1]["status"] == "filled"
    (fx.state / "STOP").write_text("stop", encoding="utf-8")
    body, _ = await place(fx, broker, quantity=100, as_of="2026-11-05T10:00:00+08:00")
    assert code_of(body) == "kill_switch"
    (fx.state / "STOP").unlink()
    body, order = await place(fx, broker, quantity=100, as_of="2026-11-05T10:00:00+08:00")
    assert order["status"] == "filled"


async def test_invalid_inputs_are_rejected_and_logged(fx: Fixture) -> None:
    broker = fx.broker()
    cases = [
        ({"code": "bad"}, "invalid_code"),
        ({"side": "hold"}, "invalid_side"),
        ({"quantity": 0}, "invalid_quantity"),
        ({"quantity": 1.5}, "invalid_quantity"),
        ({"as_of": "tomorrow"}, "invalid_as_of"),
    ]
    for overrides, expected in cases:
        body, order = await place(fx, broker, **overrides)
        assert order["status"] == "rejected"
        assert code_of(body) == expected
    rows = [json.loads(line) for line in (fx.state / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == len(cases)


async def test_ledger_replay_restart_and_verify(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    fx.set_quotes(price=11.0, when=AT_NEXT_DAY)
    await place(fx, broker, side="sell", quantity=1000, as_of=AT_NEXT_DAY)
    verified = (await broker.async_verify())["data"]
    assert verified["ok"] is True
    assert verified["mismatches"] == []
    assert verified["recomputed_cash"] == 1_000_984.29

    restarted = fx.broker()
    account = (await restarted.async_account())["data"]
    assert account["cash"] == 1_000_984.29
    assert account["positions"] == []
    assert (await restarted.async_verify())["data"]["ok"] is True


async def test_verify_detects_a_tampered_ledger(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    with (fx.state / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"seq": 2, "status": "rejected", "code": CODE, "side": "buy", "quantity": 100}) + "\n")
    report = (await broker.async_verify())["data"]
    assert report["ok"] is False
    assert report["mismatches"]


async def test_list_orders_newest_first(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=100)
    await place(fx, broker, quantity=200)
    body = await broker.async_orders(1)
    assert body["data"]["count"] == 1
    assert body["data"]["orders"][0]["quantity"] == 200
    bad = await broker.async_orders("nope")
    assert bad["status"] == "error"
    assert bad["error"]["code"] == "invalid_argument"


async def test_star_board_increments_after_two_hundred(fx: Fixture) -> None:
    broker = fx.broker()
    body, order = await place(fx, broker, code=STAR, quantity=250)
    assert order["status"] == "filled"
    assert code_of(body) == ""


async def test_account_market_value_and_equity(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    account = (await broker.async_account())["data"]
    assert account["market_value"] == 10_000.00
    assert account["equity"] == 999_994.90
    fx.set_quotes(price=10.5)
    account = (await broker.async_account())["data"]
    assert account["market_value"] == 10_500.00
    assert account["equity"] == 1_000_494.90


async def test_partial_sell_keeps_weighted_cost_and_sellable(fx: Fixture) -> None:
    broker = fx.broker()
    await place(fx, broker, quantity=1000)
    fx.set_quotes(price=10.5, when=AT_NEXT_DAY)
    body, order = await place(fx, broker, side="sell", quantity=400, as_of=AT_NEXT_DAY)
    assert order["status"] == "filled"
    account = (await broker.async_account())["data"]
    position = account["positions"][0]
    assert position["quantity"] == 600
    assert position["sellable_quantity"] == 600
    assert position["avg_cost"] == 10.0051
