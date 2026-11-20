"""Paper-broker service: validation, fills, account snapshots and ledger audits."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from paper_broker_mcp.book import Ledger, LedgerError
from paper_broker_mcp.envelope import envelope, now_cn, to_cn
from paper_broker_mcp.quotes import QuoteSource, latest_quote_time
from paper_broker_mcp.rules import (
    RuleError,
    check_buy_lot,
    check_sell_lot,
    decimal_of,
    fees_for,
    is_trading_session,
    money,
    normalize_code,
    parse_as_of,
    total_fees,
    trade_date_of,
    validate_quantity,
    validate_side,
)

logger = logging.getLogger(__name__)

DEFAULT_ORDER_LIMIT = 50
MAX_ORDER_LIMIT = 500
FEE_NAMES = ("commission", "transfer_fee", "stamp_duty")


class PaperBroker:
    """One simulated account per state directory; all mutations hold one lock."""

    def __init__(
        self,
        *,
        state_dir: Path,
        test_mode: bool = False,
        quote_file: Path | None = None,
        now_fn: Callable[[], datetime] = now_cn,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.test_mode = test_mode
        self.quote_file = Path(quote_file) if quote_file is not None else None
        self.quotes = QuoteSource(test_mode=test_mode, quote_file=self.quote_file)
        self.ledger = Ledger(self.state_dir / "ledger.jsonl")
        self.book = self.ledger.load()
        self._now_fn = now_fn
        self._lock = asyncio.Lock()
        self._last_as_of: datetime | None = self._last_ledger_time()

    def _last_ledger_time(self) -> datetime | None:
        for row in reversed(self.ledger.read_rows()):
            raw = row.get("as_of")
            if not raw:
                continue
            try:
                return to_cn(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
            except ValueError:
                continue
        return None

    def _reference_time(self) -> datetime:
        candidates: list[datetime] = []
        if self._last_as_of is not None:
            candidates.append(self._last_as_of)
        if self.test_mode:
            quote_time = latest_quote_time(self.quotes, sorted(self.book.positions))
            if quote_time is not None:
                candidates.append(quote_time)
        if candidates:
            return max(candidates)
        return self._now_fn()

    def _order_as_of(self, explicit: object) -> datetime:
        if self.test_mode:
            return parse_as_of(explicit, self._now_fn())
        return self._now_fn()

    @staticmethod
    def _skeleton(code: object, side: object, quantity: object) -> dict[str, Any]:
        return {
            "id": "",
            "status": "rejected",
            "code": str(code or ""),
            "side": str(side or ""),
            "quantity": quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else 0,
            "fill_price": 0.0,
            "gross": 0.0,
            "fees": {name: 0.0 for name in FEE_NAMES},
            "net_cash_change": 0.0,
            "reason": "",
        }

    def _commit(self, order: dict[str, Any], as_of: datetime) -> dict[str, Any]:
        self.book.seq += 1
        row = {
            "seq": self.book.seq,
            "ts": now_cn().isoformat(timespec="seconds"),
            "as_of": as_of.isoformat(timespec="seconds"),
            "trade_date": trade_date_of(as_of),
            "type": "order",
            **order,
            "cash_after": float(self.book.cash),
            "positions_after": self.book.snapshots(trade_date_of(as_of)),
        }
        self.ledger.append(row)
        self.book.orders.append(order)
        self._last_as_of = as_of
        return order

    def _reject(
        self,
        *,
        as_of: datetime,
        code: object,
        side: object,
        quantity: object,
        error_code: str,
        message: str,
    ) -> dict[str, Any]:
        order = self._skeleton(code, side, quantity)
        order["status"] = "rejected"
        order["reason"] = message
        order["id"] = f"PB{self.book.seq + 1:08d}"
        self._commit(order, as_of)
        return envelope(
            as_of=as_of,
            status="ready",
            data={"order": order},
            error_code=error_code,
            error_message=message,
        )

    def _fill(
        self,
        *,
        as_of: datetime,
        code: str,
        side: str,
        quantity: int,
        price: Decimal,
        quote: Any,
        limit_price: Decimal | None,
    ) -> dict[str, Any]:
        trade_date = trade_date_of(as_of)
        gross = money(price * quantity)
        fees = fees_for(side, gross)
        fee_total = total_fees(fees)
        net = money(gross - fee_total) if side == "sell" else money(-(gross + fee_total))
        order = {
            "id": f"PB{self.book.seq + 1:08d}",
            "status": "filled",
            "code": code,
            "side": side,
            "quantity": quantity,
            "fill_price": float(price),
            "gross": float(gross),
            "fees": {name: float(fees[name]) for name in FEE_NAMES},
            "net_cash_change": float(net),
            "reason": "",
        }
        position = self.book.position(code)
        position.last_price = price
        self.book.cash = money(self.book.cash + net)
        if side == "buy":
            unit_cost = ((gross + fee_total) / quantity).quantize(Decimal("0.000001"))
            position.add(trade_date, quantity, unit_cost)
        else:
            position.consume(trade_date, quantity)
        self._commit(order, as_of)
        logger.info(
            "paper fill %s %s %s @ %s (quote %s, limit %s)",
            side,
            quantity,
            code,
            price,
            quote.price,
            limit_price,
        )
        return envelope(as_of=as_of, data={"order": order})

    def place_order(
        self,
        *,
        code: object,
        side: object,
        quantity: object,
        price: object = None,
        as_of: object = None,
    ) -> dict[str, Any]:
        if (self.state_dir / "STOP").exists():
            try:
                moment = self._order_as_of(as_of)
            except RuleError:
                moment = self._now_fn()
            return self._reject(
                as_of=moment,
                code=code,
                side=side,
                quantity=quantity,
                error_code="kill_switch",
                message="kill switch is active (STOP file present)",
            )

        try:
            moment = self._order_as_of(as_of)
        except RuleError as exc:
            moment = self._now_fn()
            return self._reject(
                as_of=moment,
                code=code,
                side=side,
                quantity=quantity,
                error_code=exc.code,
                message=exc.message,
            )

        try:
            normalized = normalize_code(code)
        except RuleError as exc:
            return self._reject(
                as_of=moment, code=code, side=side, quantity=quantity, error_code=exc.code, message=exc.message
            )
        try:
            normalized_side = validate_side(side)
        except RuleError as exc:
            return self._reject(
                as_of=moment,
                code=normalized,
                side=side,
                quantity=quantity,
                error_code=exc.code,
                message=exc.message,
            )
        try:
            shares = validate_quantity(quantity)
        except RuleError as exc:
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=quantity,
                error_code=exc.code,
                message=exc.message,
            )

        if not is_trading_session(moment):
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=shares,
                error_code="market_closed",
                message=f"market is closed at {moment.isoformat(timespec='seconds')}",
            )

        trade_date = trade_date_of(moment)
        if normalized_side == "buy":
            try:
                check_buy_lot(normalized, shares)
            except RuleError as exc:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code=exc.code,
                    message=exc.message,
                )
        else:
            position = self.book.positions.get(normalized)
            if position is None or position.quantity <= 0:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code="no_position",
                    message=f"no position in {normalized}",
                )
            sellable = position.sellable_on(trade_date)
            if shares > sellable:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code="t_plus_1",
                    message=f"sellable quantity is {sellable} (T+1)",
                )
            try:
                check_sell_lot(shares, sellable)
            except RuleError as exc:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code=exc.code,
                    message=exc.message,
                )

        quote = self.quotes.get(normalized)
        if quote is None or not quote.usable():
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=shares,
                error_code="no_quote",
                message=f"no usable quote for {normalized}",
            )
        limit_up, limit_down = quote.limit_up, quote.limit_down
        if limit_up is None or limit_down is None or limit_up <= 0 or limit_down <= 0:
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=shares,
                error_code="no_quote",
                message=f"quote lacks usable limit prices for {normalized}",
            )
        if quote.price < limit_down or quote.price > limit_up:
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=shares,
                error_code="price_limit",
                message=f"quote {quote.price} is outside [{limit_down}, {limit_up}]",
            )

        limit_price: Decimal | None = None
        if price is not None:
            limit_price = decimal_of(price)
            if limit_price is None or limit_price <= 0:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code="price_limit",
                    message="limit price must be a positive number",
                )
            if limit_price < limit_down or limit_price > limit_up:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code="price_limit",
                    message=f"limit price {limit_price} is outside [{limit_down}, {limit_up}]",
                )
            marketable = (
                normalized_side == "buy" and limit_price >= quote.price
            ) or (normalized_side == "sell" and limit_price <= quote.price)
            if not marketable:
                return self._reject(
                    as_of=moment,
                    code=normalized,
                    side=normalized_side,
                    quantity=shares,
                    error_code="not_marketable",
                    message=f"limit price {limit_price} is not marketable against {quote.price}",
                )

        gross = money(quote.price * shares)
        fees = fees_for(normalized_side, gross)
        fee_total = total_fees(fees)
        if normalized_side == "buy" and money(gross + fee_total) > self.book.cash:
            return self._reject(
                as_of=moment,
                code=normalized,
                side=normalized_side,
                quantity=shares,
                error_code="insufficient_cash",
                message=f"required {money(gross + fee_total)} exceeds cash {self.book.cash}",
            )

        return self._fill(
            as_of=moment,
            code=normalized,
            side=normalized_side,
            quantity=shares,
            price=quote.price,
            quote=quote,
            limit_price=limit_price,
        )

    async def async_place_order(
        self, *, code: object, side: object, quantity: object, price: object = None, as_of: object = None
    ) -> dict[str, Any]:
        async with self._lock:
            return self.place_order(code=code, side=side, quantity=quantity, price=price, as_of=as_of)

    def account(self) -> dict[str, Any]:
        moment = self._reference_time()
        trade_date = trade_date_of(moment)
        prices: dict[str, Decimal] = {}
        for code, position in self.book.positions.items():
            if position.quantity <= 0:
                continue
            quote = self.quotes.get(code)
            if quote is not None and quote.usable():
                prices[code] = quote.price
        market_value = self.book.market_value(prices)
        data = {
            "initial_cash": float(self.book.initial_cash),
            "cash": float(self.book.cash),
            "positions": [row for row in self.book.snapshots(trade_date) if row["quantity"] > 0],
            "market_value": float(market_value),
            "equity": float(money(self.book.cash + market_value)),
            "currency": "CNY",
        }
        return envelope(as_of=moment, data=data)

    async def async_account(self) -> dict[str, Any]:
        async with self._lock:
            return self.account()

    def orders(self, limit: object = DEFAULT_ORDER_LIMIT) -> dict[str, Any]:
        moment = self._reference_time()
        if isinstance(limit, bool):
            parsed = 0
        elif isinstance(limit, int):
            parsed = limit
        elif isinstance(limit, float) and limit.is_integer():
            parsed = int(limit)
        elif isinstance(limit, str) and limit.strip().isdigit():
            parsed = int(limit.strip())
        else:
            parsed = 0
        if parsed < 1 or parsed > MAX_ORDER_LIMIT:
            return envelope(
                as_of=moment,
                status="error",
                error_code="invalid_argument",
                error_message=f"limit must be an integer in [1, {MAX_ORDER_LIMIT}]",
            )
        rows = list(reversed(self.book.orders))[:parsed]
        return envelope(as_of=moment, data={"orders": rows, "count": len(rows)})

    async def async_orders(self, limit: object = DEFAULT_ORDER_LIMIT) -> dict[str, Any]:
        async with self._lock:
            return self.orders(limit)

    def verify(self) -> dict[str, Any]:
        moment = self._reference_time()
        trade_date = trade_date_of(moment)
        mismatches: list[dict[str, Any]] = []
        try:
            fresh = self.ledger.load()
        except LedgerError as exc:
            data = {
                "ok": False,
                "recomputed_cash": 0.0,
                "recomputed_positions": [],
                "mismatches": [{"field": "ledger", "expected": "readable", "actual": str(exc)}],
            }
            return envelope(as_of=moment, data=data)
        if fresh.cash != self.book.cash:
            mismatches.append(
                {"field": "cash", "expected": float(fresh.cash), "actual": float(self.book.cash)}
            )
        expected = {row["code"]: row for row in fresh.snapshots(trade_date) if row["quantity"] > 0}
        actual = {row["code"]: row for row in self.book.snapshots(trade_date) if row["quantity"] > 0}
        for code in sorted(set(expected) | set(actual)):
            if code not in expected:
                mismatches.append({"field": f"position.{code}", "expected": None, "actual": actual[code]})
                continue
            if code not in actual:
                mismatches.append({"field": f"position.{code}", "expected": expected[code], "actual": None})
                continue
            for field in ("quantity", "sellable_quantity", "avg_cost"):
                if expected[code][field] != actual[code][field]:
                    mismatches.append(
                        {
                            "field": f"position.{code}.{field}",
                            "expected": expected[code][field],
                            "actual": actual[code][field],
                        }
                    )
        data = {
            "ok": not mismatches,
            "recomputed_cash": float(fresh.cash),
            "recomputed_positions": list(expected.values()),
            "mismatches": mismatches,
        }
        return envelope(as_of=moment, data=data)

    async def async_verify(self) -> dict[str, Any]:
        async with self._lock:
            return self.verify()
