"""Append-only ledger and the account state it reconstructs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from paper_broker_mcp.rules import ZERO, decimal_of, money, total_fees

INITIAL_CASH = Decimal("1000000.00")


class LedgerError(RuntimeError):
    """The ledger on disk cannot be replayed safely."""


@dataclass
class Lot:
    trade_date: str
    quantity: int
    unit_cost: Decimal


@dataclass
class Position:
    code: str
    lots: list[Lot] = field(default_factory=list)
    last_price: Decimal | None = None

    @property
    def quantity(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    def sellable_on(self, trade_date: str) -> int:
        return sum(lot.quantity for lot in self.lots if lot.trade_date < trade_date)

    def avg_cost(self) -> Decimal:
        quantity = self.quantity
        if quantity <= 0:
            return ZERO
        basis = sum((lot.unit_cost * lot.quantity for lot in self.lots), ZERO)
        return (basis / quantity).quantize(Decimal("0.0001"))

    def add(self, trade_date: str, quantity: int, unit_cost: Decimal) -> None:
        self.lots.append(Lot(trade_date=trade_date, quantity=quantity, unit_cost=unit_cost))

    def consume(self, trade_date: str, quantity: int) -> None:
        if quantity > self.sellable_on(trade_date):
            raise LedgerError(f"ledger replay would oversell {self.code} on {trade_date}")
        remaining = quantity
        kept: list[Lot] = []
        for lot in self.lots:
            if remaining <= 0 or lot.trade_date >= trade_date:
                kept.append(lot)
                continue
            taken = min(lot.quantity, remaining)
            remaining -= taken
            if lot.quantity > taken:
                kept.append(Lot(lot.trade_date, lot.quantity - taken, lot.unit_cost))
        self.lots = [lot for lot in kept if lot.quantity > 0]

    def snapshot(self, trade_date: str) -> dict[str, Any]:
        return {
            "code": self.code,
            "quantity": self.quantity,
            "sellable_quantity": self.sellable_on(trade_date),
            "avg_cost": float(self.avg_cost()),
        }


class Book:
    """Cash and positions rebuilt from ledger rows; mutations mirror fills exactly."""

    def __init__(self) -> None:
        self.initial_cash = INITIAL_CASH
        self.cash = INITIAL_CASH
        self.positions: dict[str, Position] = {}
        self.orders: list[dict[str, Any]] = []
        self.seq = 0

    def position(self, code: str) -> Position:
        return self.positions.setdefault(code, Position(code=code))

    def apply_row(self, row: dict[str, Any]) -> None:
        try:
            self.seq = int(row["seq"])
            code = str(row["code"])
            quantity = int(row["quantity"])
            status = str(row["status"])
            side = str(row["side"])
            trade_date = str(row["trade_date"])
            net = decimal_of(row.get("net_cash_change")) or ZERO
            fill_price = decimal_of(row.get("fill_price")) or ZERO
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerError(f"malformed ledger row: {exc}") from exc
        if status == "filled":
            position = self.position(code)
            position.last_price = fill_price
            fees = row.get("fees") if isinstance(row.get("fees"), dict) else {}
            fee_total = total_fees(
                {name: decimal_of(fees.get(name)) or ZERO for name in ("commission", "transfer_fee", "stamp_duty")}
            )
            self.cash = money(self.cash + net)
            if side == "buy":
                gross = decimal_of(row.get("gross")) or ZERO
                unit_cost = ((gross + fee_total) / quantity).quantize(Decimal("0.000001"))
                position.add(trade_date, quantity, unit_cost)
            elif side == "sell":
                position.consume(trade_date, quantity)
            else:
                raise LedgerError(f"unknown side in ledger: {side!r}")
        self.orders.append(
            {
                "id": str(row.get("id", "")),
                "status": status,
                "code": code,
                "side": side,
                "quantity": quantity,
                "fill_price": float(fill_price),
                "gross": float(decimal_of(row.get("gross")) or ZERO),
                "fees": {
                    name: float(decimal_of((row.get("fees") or {}).get(name)) or ZERO)
                    for name in ("commission", "transfer_fee", "stamp_duty")
                },
                "net_cash_change": float(net),
                "reason": str(row.get("reason") or ""),
            }
        )

    def snapshots(self, trade_date: str) -> list[dict[str, Any]]:
        return [self.positions[code].snapshot(trade_date) for code in sorted(self.positions)]

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = ZERO
        for code in sorted(self.positions):
            position = self.positions[code]
            price = prices.get(code) or position.last_price or position.avg_cost()
            total += price * position.quantity
        return money(total)


class Ledger:
    """Append-only JSONL log; every order (filled or rejected) is one durable row."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LedgerError(f"cannot read ledger: {exc}") from exc
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise LedgerError(f"ledger line {number} is not JSON") from exc
            if not isinstance(row, dict):
                raise LedgerError(f"ledger line {number} is not an object")
            rows.append(row)
        return rows

    def append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def load(self) -> Book:
        book = Book()
        for row in self.read_rows():
            book.apply_row(row)
        return book
