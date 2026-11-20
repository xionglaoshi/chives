"""Manual broker-fill registration in the existing private holdings book."""

from datetime import date
from math import isfinite
from uuid import UUID
from .errors import PortfolioError
from .fields import validate_qty, validate_position, validate_cost_price
from .symbols import normalize_symbol


def normalize_trade(args, today):
    try:
        uid = str(UUID(args["id"]))
        day = date.fromisoformat(args["date"])
        if day > today or args["side"] not in ("buy", "sell"):
            raise ValueError()
        fees = args.get("fees", 0)
        if (
            isinstance(fees, bool)
            or not isinstance(fees, (int, float))
            or not isfinite(fees)
            or fees < 0
        ):
            raise ValueError()
        return dict(
            id=uid,
            date=day.isoformat(),
            code=normalize_symbol(args["code"]).canonical,
            side=args["side"],
            shares=validate_qty(args["shares"]),
            price=validate_cost_price(args["price"]),
            fees=fees,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PortfolioError(
            "invalid_value", "需要成交 UUID、合法日期、方向、股数、成交价和非负手续费"
        ) from exc


def apply_trade(state, trade):
    prior = next((t for t in state.trades if t["id"] == trade["id"]), None)
    if prior:
        if prior != trade:
            raise PortfolioError("conflict", "同一成交编号的内容不一致")
        return state
    if state.warnings:
        raise PortfolioError("portfolio_corrupt", "请先修复持仓文件")
    if state.as_of and trade["date"] < state.as_of:
        raise PortfolioError(
            "invalid_value", "成交日早于当前持仓快照，请按交易时间顺序从期初快照登记"
        )
    row = next((r for r in state.positions if r["code"] == trade["code"]), None)
    qty = trade["shares"]
    amount = qty * trade["price"]
    if trade["side"] == "sell":
        if not row or row["qty"] < qty:
            raise PortfolioError("invalid_value", "卖出超过登记持仓")
        row["qty"] -= qty
        if row["available_qty"] is not None:
            row["available_qty"] = min(row["qty"], max(0, row["available_qty"] - qty))
        if not row["qty"]:
            state.positions.remove(row)
        delta = amount - trade["fees"]
    else:
        cost = amount + trade["fees"]
        if row:
            row["cost_price"] = (row["cost_price"] * row["qty"] + cost) / (
                row["qty"] + qty
            )
            row["qty"] += qty
        else:
            state.positions.append(
                validate_position(
                    dict(
                        code=trade["code"],
                        name=trade["code"],
                        qty=qty,
                        cost_price=cost / qty,
                        opened_date=trade["date"],
                    )
                )
            )
        delta = -cost
    if state.cash is not None:
        if state.cash + delta < 0:
            raise PortfolioError(
                "invalid_value", "已记录的现金余额不足，请先核对资金流水"
            )
        state.cash += delta
    state.as_of = trade["date"]
    state.trades.append(trade)
    return state
