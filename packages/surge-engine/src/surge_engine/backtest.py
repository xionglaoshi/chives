"""Backtest for the 主升浪 strategy (T159).

Signals come
only from events the engine already emitted, entries use the next trading day's
open after the signal, exits use the open after the main-pool removal, and the
fees/slippage are applied exactly as written there.  No parameter is chosen
from the backtest result.

Execution prices are unadjusted (``adjust="none"``); the adjustment factor is
used only to keep a holding's return continuous across ex-rights days.
"""

from __future__ import annotations

import bisect
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Protocol

from cn_daily_store import DailyStore
from cn_daily_store.limits import limit_price_from, round_half_up_to_cent

SCHEME_EVENTS = {
    "p1": "优先级一确定",
    "p2": "优先级二确定",
    "start": "启动",
    "second_board": "二板",
}
SCHEME_LABELS = {
    "p1": "优先级一确定日买入",
    "p2": "优先级二确定日买入",
    "start": "启动日 T* 买入",
    "second_board": "二板日（F+1）买入",
}
SCHEMES = tuple(SCHEME_EVENTS)

COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_TAX_SWITCH = date(2023, 8, 28)
STAMP_TAX_BEFORE = 0.001
STAMP_TAX_AFTER = 0.0005
BUY_SLIPPAGE = 0.001
SELL_SLIPPAGE = 0.001
MAX_SUSPEND_DAYS = 5
PER_TRADE_CAPITAL = 100_000.0
INITIAL_CAPITAL = 1_000_000.0
MAX_POSITIONS = 10
MIN_POSITION_BUDGET = 1_000.0
RISK_FREE_RATE = 0.0
TRADING_DAYS_PER_YEAR = 252


class BacktestError(RuntimeError):
    """A user-facing backtest error with a Chinese message."""


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def commission(notional: float) -> float:
    """Commission in yuan: 0.025% both sides, minimum 5 yuan."""
    return max(MIN_COMMISSION, _money(notional * COMMISSION_RATE))


def stamp_tax(notional: float, day: date) -> float:
    """Sell-side stamp tax; 0.1% before 2023-08-28, 0.05% from that day."""
    rate = STAMP_TAX_AFTER if day >= STAMP_TAX_SWITCH else STAMP_TAX_BEFORE
    return _money(notional * rate)


@dataclass(frozen=True)
class PriceBar:
    day: date
    open: float
    close: float
    adj_factor: float


@dataclass(frozen=True)
class SecurityInfo:
    code: str
    name: str
    board: str


class BacktestSource(Protocol):
    calendar: list[date]

    def bar(self, code: str, day: date) -> PriceBar | None: ...

    def security(self, code: str) -> SecurityInfo | None: ...

    def limit_up_price(self, code: str, day: date) -> Decimal | None: ...

    def limit_down_price(self, code: str, day: date) -> Decimal | None: ...


class DailyStoreBacktestSource:
    """Read-only adapter over ``cn_daily_store.DailyStore``.

    Single-bar reads keep memory flat: the four schemes together touch about
    22k signals over 7.8M daily bars.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.store = DailyStore(db_path)
        self.calendar = self.store.calendar()
        self.index = {day: offset for offset, day in enumerate(self.calendar)}

    def close(self) -> None:
        self.store.close()

    def bar(self, code: str, day: date) -> PriceBar | None:
        rows = self.store.bars(code, start=day, end=day, adjust="none")
        if not rows:
            return None
        row = rows[0]
        return PriceBar(day=row.date, open=row.open, close=row.close, adj_factor=row.adj_factor)

    def last_bar(self, code: str, day: date) -> PriceBar | None:
        rows = self.store.bars(code, end=day, adjust="none")
        if not rows:
            return None
        row = rows[-1]
        return PriceBar(day=row.date, open=row.open, close=row.close, adj_factor=row.adj_factor)

    def security(self, code: str) -> SecurityInfo | None:
        row = self.store.security(code)
        if row is None:
            return None
        return SecurityInfo(code=code, name=str(row["name"]), board=str(row["board"]))

    def _ratio(self, code: str, day: date) -> Any:
        return self.store.limit_ratio(code, day)

    def limit_up_price(self, code: str, day: date) -> Decimal | None:
        ratio = self._ratio(code, day)
        previous = self.store.previous_bar(code, day)
        if ratio is None or previous is None:
            return None
        return limit_price_from(previous.close, ratio)

    def limit_down_price(self, code: str, day: date) -> Decimal | None:
        ratio = self._ratio(code, day)
        previous = self.store.previous_bar(code, day)
        if ratio is None or previous is None:
            return None
        base = Decimal(str(previous.close)) * (Decimal("1") - ratio)
        return base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Signal:
    scheme: str
    code: str
    round_id: int
    signal_date: date
    rank: int
    score: int | None
    base_score: int | None
    gain: float | None
    main_out_date: date | None
    main_out_reason: str | None


@dataclass
class TradePlan:
    signal: Signal
    status: str
    buy_index: int | None = None
    buy_day: date | None = None
    buy_open: float | None = None
    buy_factor: float | None = None
    buy_exec: float | None = None
    sell_index: int | None = None
    sell_day: date | None = None
    sell_open: float | None = None
    sell_factor: float | None = None
    sell_exec: float | None = None
    valuation_index: int | None = None
    valuation_day: date | None = None
    valuation_close: float | None = None
    valuation_factor: float | None = None
    delay_days: int = 0
    exit_reason: str = ""
    unclosed: bool = False
    note: str = ""


def _readonly(path: Path | str) -> sqlite3.Connection:
    target = Path(path)
    if not target.is_file():
        raise BacktestError(f"引擎数据库不存在：{target}；请先运行 surge-engine replay")
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def load_signals(
    surge_db: Path | str,
    scheme: str,
    start: date,
    end: date,
) -> list[Signal]:
    """Read one scheme's signals and the matching pool rank on the signal day."""
    if scheme not in SCHEME_EVENTS:
        raise BacktestError(f"未知方案：{scheme}；可选 {', '.join(SCHEMES)}")
    event = SCHEME_EVENTS[scheme]
    with closing(_readonly(surge_db)) as conn:
        rounds = {
            (str(row["code"]), int(row["round_id"])): row
            for row in conn.execute(
                "SELECT code, round_id, F, main_out_date, main_out_reason FROM rounds"
            )
        }
        rows = conn.execute(
            "SELECT e.code, e.round_id, e.date, "
            "fs.rank AS first_rank, fs.score AS first_score, "
            "ms.rank AS main_rank, ms.score AS main_score, ms.base_score, ms.gain "
            "FROM events e "
            "LEFT JOIN pool_snapshots fs ON fs.code=e.code AND fs.round_id=e.round_id "
            "AND fs.date=e.date AND fs.pool='first' "
            "LEFT JOIN pool_snapshots ms ON ms.code=e.code AND ms.round_id=e.round_id "
            "AND ms.date=e.date AND ms.pool='main' "
            "WHERE e.event=? AND e.date>=? AND e.date<=? "
            "ORDER BY e.date, e.code, e.round_id",
            (event, start.isoformat(), end.isoformat()),
        ).fetchall()
    signals: list[Signal] = []
    for row in rows:
        code = str(row["code"])
        round_id = int(row["round_id"])
        info = rounds.get((code, round_id))
        if info is None:
            continue
        rank = row["first_rank"] if scheme in {"p1", "p2"} else row["main_rank"]
        score = row["first_score"] if scheme in {"p1", "p2"} else row["main_score"]
        signals.append(
            Signal(
                scheme=scheme,
                code=code,
                round_id=round_id,
                signal_date=date.fromisoformat(str(row["date"])),
                rank=int(rank) if rank is not None else 10**6,
                score=None if score is None else int(score),
                base_score=None if row["base_score"] is None else int(row["base_score"]),
                gain=None if row["gain"] is None else float(row["gain"]),
                main_out_date=(
                    None if info["main_out_date"] is None else date.fromisoformat(str(info["main_out_date"]))
                ),
                main_out_reason=None if info["main_out_reason"] is None else str(info["main_out_reason"]),
            )
        )
    return signals


def find_buy(source: BacktestSource, signal: Signal, end_index: int) -> tuple[str, int | None, PriceBar | None]:
    """Next trading day open; suspension rolls up to five days; one-word limit-up cannot buy."""
    start_index = source.index[signal.signal_date] + 1
    for offset in range(start_index, end_index + 1):
        delay = offset - (start_index - 1)
        if delay > MAX_SUSPEND_DAYS:
            return "suspension_abandoned", None, None
        bar = source.bar(signal.code, source.calendar[offset])
        if bar is None:
            continue
        limit_up = source.limit_up_price(signal.code, bar.day)
        if limit_up is not None and round_half_up_to_cent(bar.open) == limit_up:
            return "unfilled_limit_up", offset, bar
        return "ok", offset, bar
    return "out_of_range", None, None


def _last_valuation_bar(source: BacktestSource, code: str, buy_index: int, end_index: int) -> tuple[int, PriceBar] | None:
    for offset in range(end_index, buy_index - 1, -1):
        bar = source.bar(code, source.calendar[offset])
        if bar is not None:
            return offset, bar
    return None


def evaluate_signal(source: BacktestSource, signal: Signal, end_index: int, cutoff: date) -> TradePlan:
    """Turn one signal into a trade plan using only data after the signal day."""
    if signal.signal_date not in source.index:
        return TradePlan(signal=signal, status="signal_not_trading_day")
    status, buy_index, bar = find_buy(source, signal, end_index)
    if status != "ok" or buy_index is None or bar is None:
        return TradePlan(signal=signal, status=status)
    buy_exec = bar.open * (1.0 + BUY_SLIPPAGE)
    plan = TradePlan(
        signal=signal,
        status="ok",
        buy_index=buy_index,
        buy_day=bar.day,
        buy_open=bar.open,
        buy_factor=bar.adj_factor,
        buy_exec=round(buy_exec, 6),
        delay_days=buy_index - source.index[signal.signal_date],
    )

    out_date = signal.main_out_date
    if out_date is not None and out_date <= signal.signal_date:
        return TradePlan(signal=signal, status="exit_before_entry")
    if out_date is not None and bar.day is not None and out_date < bar.day:
        return TradePlan(signal=signal, status="exit_before_entry")
    if out_date is None or out_date > cutoff:
        return _mark_unclosed(source, plan, end_index, "截止日未平仓")

    sell_from = max(source.index[out_date] + 1, buy_index + 1)
    for offset in range(sell_from, end_index + 1):
        day = source.calendar[offset]
        sell_bar = source.bar(signal.code, day)
        if sell_bar is None:
            continue
        limit_down = source.limit_down_price(signal.code, day)
        if limit_down is not None and round_half_up_to_cent(sell_bar.open) == limit_down:
            continue
        plan.sell_index = offset
        plan.sell_day = day
        plan.sell_open = sell_bar.open
        plan.sell_factor = sell_bar.adj_factor
        plan.sell_exec = round(sell_bar.open * (1.0 - SELL_SLIPPAGE), 6)
        plan.exit_reason = signal.main_out_reason or "主升浪移出"
        return plan

    return _mark_unclosed(source, plan, end_index, "截止日跌停或停牌未卖出")


def _mark_unclosed(source: BacktestSource, plan: TradePlan, end_index: int, reason: str) -> TradePlan:
    found = _last_valuation_bar(source, plan.signal.code, plan.buy_index or 0, end_index)
    if found is None:
        plan.status = "no_valuation_bar"
        return plan
    plan.valuation_index, bar = found
    plan.valuation_day = bar.day
    plan.valuation_close = bar.close
    plan.valuation_factor = bar.adj_factor
    plan.exit_reason = reason
    plan.unclosed = True
    return plan


def per_trade_row(plan: TradePlan, capital: float = PER_TRADE_CAPITAL) -> dict[str, Any]:
    """Fixed-capital, independent trade statistics row."""
    row: dict[str, Any] = {
        "scheme": plan.signal.scheme,
        "code": plan.signal.code,
        "round_id": plan.signal.round_id,
        "signal_date": plan.signal.signal_date.isoformat(),
        "signal_rank": plan.signal.rank,
        "first_score": plan.signal.score,
        "base_score": plan.signal.base_score,
        "entry_gain": plan.signal.gain,
        "status": plan.status,
        "delay_days": plan.delay_days,
        "buy_date": "",
        "buy_open_raw": "",
        "buy_exec": "",
        "buy_adj_factor": "",
        "sell_date": "",
        "sell_open_raw": "",
        "sell_exec": "",
        "sell_adj_factor": "",
        "valuation_date": "",
        "valuation_close_raw": "",
        "shares": "",
        "buy_notional": "",
        "buy_commission": "",
        "sell_commission": "",
        "stamp_tax": "",
        "buy_cost": "",
        "sell_net": "",
        "pnl": "",
        "return_pct": "",
        "holding_days": "",
        "exit_reason": plan.exit_reason,
        "unclosed": plan.unclosed,
        "portfolio_skip_reason": "",
    }
    if plan.status != "ok" or plan.buy_exec is None or plan.buy_open is None or plan.buy_factor is None:
        return row

    shares = capital / plan.buy_exec
    buy_notional = shares * plan.buy_exec
    buy_commission = commission(buy_notional)
    buy_cost = buy_notional + buy_commission
    row.update(
        {
            "buy_date": plan.buy_day.isoformat() if plan.buy_day else "",
            "buy_open_raw": round(plan.buy_open, 4),
            "buy_exec": round(plan.buy_exec, 6),
            "buy_adj_factor": plan.buy_factor,
            "shares": round(shares, 6),
            "buy_notional": round(buy_notional, 2),
            "buy_commission": buy_commission,
            "buy_cost": round(buy_cost, 2),
        }
    )

    if plan.sell_open is not None and plan.sell_factor is not None and plan.sell_day is not None:
        sell_exec_notional = shares * plan.sell_exec  # type: ignore[operator]
        sell_commission = commission(sell_exec_notional)
        tax = stamp_tax(sell_exec_notional, plan.sell_day)
        factor_ratio = plan.sell_factor / plan.buy_factor
        sell_net = shares * plan.sell_exec * factor_ratio - sell_commission - tax  # type: ignore[operator]
        pnl = sell_net - buy_cost
        row.update(
            {
                "sell_date": plan.sell_day.isoformat(),
                "sell_open_raw": round(plan.sell_open, 4),
                "sell_exec": round(plan.sell_exec, 6),  # type: ignore[arg-type]
                "sell_adj_factor": plan.sell_factor,
                "sell_commission": sell_commission,
                "stamp_tax": tax,
                "sell_net": round(sell_net, 2),
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / buy_cost * 100, 4),
                "holding_days": plan.sell_index - plan.buy_index if plan.sell_index and plan.buy_index else "",
            }
        )
        return row

    if plan.valuation_close is not None and plan.valuation_factor is not None:
        factor_ratio = plan.valuation_factor / plan.buy_factor
        value = shares * plan.valuation_close * factor_ratio
        pnl = value - buy_cost
        row.update(
            {
                "valuation_date": plan.valuation_day.isoformat() if plan.valuation_day else "",
                "valuation_close_raw": round(plan.valuation_close, 4),
                "sell_net": round(value, 2),
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / buy_cost * 100, 4),
                "holding_days": (
                    plan.valuation_index - plan.buy_index
                    if plan.valuation_index and plan.buy_index
                    else ""
                ),
            }
        )
    return row


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _returns(rows: Iterable[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        if row.get("return_pct") in ("", None):
            continue
        values.append(float(row["return_pct"]))
    return values


def summarize_returns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = _returns(rows)
    executed = [row for row in rows if row.get("return_pct") not in ("", None)]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    ordered = sorted(executed, key=lambda row: (row["buy_date"], row["code"]))
    longest = current = 0
    for row in ordered:
        if float(row["return_pct"]) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    holding = [int(row["holding_days"]) for row in executed if row.get("holding_days") not in ("", None)]
    return {
        "count": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(values) * 100, 2) if values else None,
        "avg_return_pct": round(sum(values) / len(values), 4) if values else None,
        "median_return_pct": round(_median(values), 4) if values else None,
        "profit_loss_ratio": round(avg_win / abs(avg_loss), 4) if avg_loss else None,
        "max_win_pct": round(max(values), 4) if values else None,
        "max_loss_pct": round(min(values), 4) if values else None,
        "longest_losing_streak": longest,
        "avg_holding_days": round(sum(holding) / len(holding), 2) if holding else None,
        "unclosed_count": sum(1 for row in executed if row.get("unclosed")),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


HISTOGRAM_BINS = (-50.0, -30.0, -20.0, -10.0, -5.0, 0.0, 5.0, 10.0, 20.0, 30.0, 50.0, 100.0)


def histogram(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = _returns(rows)
    bins: list[dict[str, Any]] = []
    for low, high in zip(HISTOGRAM_BINS, HISTOGRAM_BINS[1:]):
        count = sum(1 for value in values if low <= value < high)
        bins.append({"low": low, "high": high, "label": f"{low:g}~{high:g}", "count": count})
    below = sum(1 for value in values if value < HISTOGRAM_BINS[0])
    above = sum(1 for value in values if value >= HISTOGRAM_BINS[-1])
    if below or not bins:
        bins.insert(0, {"low": None, "high": HISTOGRAM_BINS[0], "label": f"<{HISTOGRAM_BINS[0]:g}", "count": below})
    if above:
        bins.append({"low": HISTOGRAM_BINS[-1], "high": None, "label": f">={HISTOGRAM_BINS[-1]:g}", "count": above})
    return bins


# ---------------------------------------------------------------------------
# Portfolio simulation
# ---------------------------------------------------------------------------


@dataclass
class _Position:
    plan: TradePlan
    shares: float
    cost: float
    buy_factor: float
    last_value: float
    last_close: float


def _position_value(position: _Position, bar: PriceBar | None) -> float:
    if bar is None or position.buy_factor <= 0:
        return position.last_value
    return position.shares * bar.close * (bar.adj_factor / position.buy_factor)


def run_portfolio(
    plans: list[TradePlan],
    source: BacktestSource,
    start_index: int,
    end_index: int,
    *,
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
    benchmark_closes: dict[str, dict[date, float]] | None = None,
) -> dict[str, Any]:
    """Daily portfolio: at most ten names, 1/10 of total assets per entry."""
    benchmark_closes = benchmark_closes or {}
    active = {key: dict(value) for key, value in benchmark_closes.items()}
    last_bench: dict[str, float | None] = {key: None for key in active}

    executable = [plan for plan in plans if plan.status == "ok" and plan.buy_index is not None]
    entries: dict[int, list[TradePlan]] = defaultdict(list)
    exits: dict[int, list[TradePlan]] = defaultdict(list)
    for plan in executable:
        if plan.buy_index is not None and plan.buy_index <= end_index:
            entries[plan.buy_index].append(plan)
        if plan.sell_index is not None and plan.sell_index <= end_index:
            exits[plan.sell_index].append(plan)
    for rows in entries.values():
        rows.sort(key=lambda plan: (plan.signal.rank, plan.signal.signal_date, plan.signal.code))

    cash = float(initial_capital)
    positions: dict[str, _Position] = {}
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    turnover_notional = 0.0

    for offset in range(start_index, end_index + 1):
        day = source.calendar[offset]

        for plan in exits.get(offset, ()):
            position = positions.get(plan.signal.code)
            if position is None or plan.sell_exec is None or plan.sell_factor is None or plan.sell_day is None:
                continue
            sell_exec_notional = position.shares * plan.sell_exec
            sell_commission = commission(sell_exec_notional)
            tax = stamp_tax(sell_exec_notional, plan.sell_day)
            factor_ratio = plan.sell_factor / position.buy_factor
            proceeds = position.shares * plan.sell_exec * factor_ratio - sell_commission - tax
            cash += proceeds
            pnl = proceeds - position.cost
            turnover_notional += sell_exec_notional
            trades.append(
                {
                    "scheme": plan.signal.scheme,
                    "code": plan.signal.code,
                    "round_id": plan.signal.round_id,
                    "signal_date": plan.signal.signal_date.isoformat(),
                    "signal_rank": plan.signal.rank,
                    "buy_date": plan.buy_day.isoformat() if plan.buy_day else "",
                    "buy_open_raw": round(plan.buy_open or 0.0, 4),
                    "buy_exec": round(plan.buy_exec or 0.0, 6),
                    "buy_adj_factor": position.buy_factor,
                    "shares": round(position.shares, 6),
                    "buy_notional": round(position.shares * (plan.buy_exec or 0.0), 2),
                    "buy_commission": commission(position.shares * (plan.buy_exec or 0.0)),
                    "buy_cost": round(position.cost, 2),
                    "sell_date": plan.sell_day.isoformat(),
                    "sell_open_raw": round(plan.sell_open or 0.0, 4),
                    "sell_exec": round(plan.sell_exec, 6),
                    "sell_adj_factor": plan.sell_factor,
                    "sell_commission": sell_commission,
                    "stamp_tax": tax,
                    "sell_net": round(proceeds, 2),
                    "pnl": round(pnl, 2),
                    "return_pct": round(pnl / position.cost * 100, 4) if position.cost else "",
                    "holding_days": offset - position.plan.buy_index if position.plan.buy_index is not None else "",
                    "status": "closed",
                    "exit_reason": plan.exit_reason,
                }
            )
            del positions[plan.signal.code]

        for plan in entries.get(offset, ()):
            if len(positions) >= max_positions:
                skipped.append(_skip_row(plan, "仓位已满跳过"))
                continue
            if plan.signal.code in positions:
                skipped.append(_skip_row(plan, "已持有该股跳过"))
                continue
            if plan.buy_exec is None or plan.buy_factor is None or plan.buy_day is None:
                continue
            equity_now = cash
            for held_code, held in positions.items():
                held_bar = source.bar(held_code, day)
                if held_bar is None:
                    equity_now += held.last_value
                else:
                    equity_now += held.shares * held_bar.open * (held_bar.adj_factor / held.buy_factor)
            budget = min(equity_now / max_positions, cash)
            if budget < MIN_POSITION_BUDGET:
                skipped.append(_skip_row(plan, "资金不足跳过"))
                continue
            shares = max(0.0, (budget - MIN_COMMISSION) / (plan.buy_exec * (1.0 + COMMISSION_RATE)))
            if shares <= 0:
                skipped.append(_skip_row(plan, "资金不足跳过"))
                continue
            notional = shares * plan.buy_exec
            buy_commission = commission(notional)
            cost = notional + buy_commission
            if cost > cash + 1e-6:
                skipped.append(_skip_row(plan, "资金不足跳过"))
                continue
            cash -= cost
            turnover_notional += notional
            positions[plan.signal.code] = _Position(
                plan=plan,
                shares=shares,
                cost=cost,
                buy_factor=plan.buy_factor,
                last_value=cost,
                last_close=plan.buy_open or 0.0,
            )

        positions_value = 0.0
        for code, position in positions.items():
            bar = source.bar(code, day)
            value = _position_value(position, bar)
            if bar is not None:
                position.last_close = bar.close
            position.last_value = value
            positions_value += value
        equity = cash + positions_value

        row: dict[str, Any] = {
            "date": day.isoformat(),
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "equity": round(equity, 2),
            "positions": len(positions),
        }
        for key, series in active.items():
            close = series.get(day)
            if close is not None:
                last_bench[key] = close
            row[key] = None if last_bench[key] is None else round(float(last_bench[key]), 6)
        equity_rows.append(row)

    for code, position in sorted(positions.items()):
        plan = position.plan
        if plan.valuation_close is None or plan.valuation_factor is None:
            value = position.last_value
            valuation_day = plan.valuation_day or source.calendar[end_index]
        else:
            value = position.shares * plan.valuation_close * (plan.valuation_factor / position.buy_factor)
            valuation_day = plan.valuation_day or source.calendar[end_index]
        pnl = value - position.cost
        trades.append(
            {
                "scheme": plan.signal.scheme,
                "code": plan.signal.code,
                "round_id": plan.signal.round_id,
                "signal_date": plan.signal.signal_date.isoformat(),
                "signal_rank": plan.signal.rank,
                "buy_date": plan.buy_day.isoformat() if plan.buy_day else "",
                "buy_open_raw": round(plan.buy_open or 0.0, 4),
                "buy_exec": round(plan.buy_exec or 0.0, 6),
                "buy_adj_factor": position.buy_factor,
                "shares": round(position.shares, 6),
                "buy_notional": round(position.shares * (plan.buy_exec or 0.0), 2),
                "buy_commission": commission(position.shares * (plan.buy_exec or 0.0)),
                "buy_cost": round(position.cost, 2),
                "sell_date": "",
                "sell_open_raw": "",
                "sell_exec": "",
                "sell_adj_factor": "",
                "sell_commission": "",
                "stamp_tax": "",
                "sell_net": round(value, 2),
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / position.cost * 100, 4) if position.cost else "",
                "holding_days": (
                    plan.valuation_index - plan.buy_index
                    if plan.valuation_index is not None and plan.buy_index is not None
                    else ""
                ),
                "status": "unclosed",
                "exit_reason": plan.exit_reason or "截止日未平仓",
            }
        )

    return {
        "equity_rows": equity_rows,
        "trades": trades,
        "skipped": skipped,
        "turnover_notional": turnover_notional,
    }


def _skip_row(plan: TradePlan, reason: str) -> dict[str, Any]:
    return {
        "signal_date": plan.signal.signal_date.isoformat(),
        "code": plan.signal.code,
        "round_id": plan.signal.round_id,
        "rank": plan.signal.rank,
        "reason": reason,
        "buy_date": "" if plan.buy_day is None else plan.buy_day.isoformat(),
    }


# ---------------------------------------------------------------------------
# Portfolio metrics and grouping
# ---------------------------------------------------------------------------


def max_drawdown(values: list[float], days: list[str]) -> tuple[float, str, str]:
    peak = values[0] if values else 0.0
    peak_day = days[0] if days else ""
    best = 0.0
    best_peak = peak_day
    best_trough = peak_day
    for value, day in zip(values, days):
        if value > peak:
            peak, peak_day = value, day
        drawdown = value / peak - 1.0 if peak else 0.0
        if drawdown < best:
            best, best_peak, best_trough = drawdown, peak_day, day
    return best, best_peak, best_trough


def _daily_returns(values: list[float]) -> list[float]:
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values)) if values[index - 1]]


def equity_metrics(values: list[float], days: list[str]) -> dict[str, Any]:
    if len(values) < 2:
        return {
            "total_return_pct": None,
            "annualized_return_pct": None,
            "max_drawdown_pct": None,
            "max_drawdown_peak": "",
            "max_drawdown_trough": "",
            "sharpe": None,
            "calmar": None,
        }
    total = values[-1] / values[0] - 1.0
    periods = len(values) - 1
    annualized = (1.0 + total) ** (TRADING_DAYS_PER_YEAR / periods) - 1.0 if total > -1 else -1.0
    drawdown, peak_day, trough_day = max_drawdown(values, days)
    returns = _daily_returns(values)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    std = variance ** 0.5
    sharpe = (mean - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR) / std * (TRADING_DAYS_PER_YEAR ** 0.5) if std > 0 else None
    calmar = annualized / abs(drawdown) if drawdown < 0 else None
    return {
        "total_return_pct": round(total * 100, 4),
        "annualized_return_pct": round(annualized * 100, 4),
        "max_drawdown_pct": round(drawdown * 100, 4),
        "max_drawdown_peak": peak_day,
        "max_drawdown_trough": trough_day,
        "sharpe": None if sharpe is None else round(sharpe, 4),
        "calmar": None if calmar is None else round(calmar, 4),
    }


def portfolio_metrics(
    equity_rows: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    turnover_notional: float,
) -> dict[str, Any]:
    values = [float(row["equity"]) for row in equity_rows]
    days = [str(row["date"]) for row in equity_rows]
    metrics = equity_metrics(values, days)
    avg_equity = sum(values) / len(values) if values else 0.0
    years = (len(values) - 1) / TRADING_DAYS_PER_YEAR if values else 0.0
    metrics.update(
        {
            "trades": len(trades),
            "win_rate_pct": (
                round(sum(1 for row in trades if float(row["return_pct"]) > 0) / len(trades) * 100, 2)
                if trades
                else None
            ),
            "avg_trade_return_pct": (
                round(sum(float(row["return_pct"]) for row in trades) / len(trades), 4) if trades else None
            ),
            "avg_positions": (
                round(sum(int(row["positions"]) for row in equity_rows) / len(equity_rows), 2)
                if equity_rows
                else None
            ),
            "turnover_annualized": (
                round(turnover_notional / avg_equity / years, 4) if avg_equity > 0 and years > 0 else None
            ),
            "turnover_definition": "双边成交额 / 平均权益 / 年数（按 252 个交易日折算）",
        }
    )
    return metrics


def yearly_returns(equity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not equity_rows:
        return []
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in equity_rows:
        by_year[int(str(row["date"])[:4])].append(row)
    out: list[dict[str, Any]] = []
    previous = float(equity_rows[0]["equity"])
    for year in sorted(by_year):
        rows = by_year[year]
        last = float(rows[-1]["equity"])
        out.append(
            {
                "year": year,
                "return_pct": round((last / previous - 1.0) * 100, 4) if previous else None,
                "end_equity": round(last, 2),
            }
        )
        previous = last
    return out


def _bucket_first_score(score: int | None) -> str:
    if score is None:
        return "未知"
    if score < 60:
        return "<60"
    if score < 70:
        return "60–69"
    if score < 80:
        return "70–79"
    if score < 90:
        return "80–89"
    return "90–100"


def _bucket_base_score(score: int | None) -> str:
    if score is None:
        return "未知"
    return str(score)


def group_statistics(rows: list[dict[str, Any]], key, order: list[str] | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(key(row))].append(row)
    keys = order if order is not None else sorted(grouped)
    out = []
    for label in keys:
        members = grouped.get(label, [])
        if not members and order is not None:
            out.append({"group": label, "count": 0, "win_rate_pct": None, "avg_return_pct": None, "avg_holding_days": None})
            continue
        stats = summarize_returns(members)
        out.append(
            {
                "group": label,
                "count": stats["count"],
                "win_rate_pct": stats["win_rate_pct"],
                "avg_return_pct": stats["avg_return_pct"],
                "median_return_pct": stats["median_return_pct"],
                "avg_holding_days": stats["avg_holding_days"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _board_label(board: str | None) -> str:
    return {
        "sh_main": "主板",
        "sz_main": "主板",
        "chinext": "创业板",
        "star": "科创板",
    }.get(board or "", board or "未知")


def _environment_map(closes: dict[date, float]) -> dict[date, str]:
    days = sorted(closes)
    out: dict[date, str] = {}
    for index, day in enumerate(days):
        if index < 19:
            continue
        window = [closes[item] for item in days[index - 19 : index + 1]]
        ma20 = sum(window) / len(window)
        out[day] = "沪深300 收盘在 MA20 上方" if closes[day] > ma20 else "沪深300 收盘在 MA20 下方"
    return out


def _benchmark_metrics(equity_rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    values: list[float] = []
    days: list[str] = []
    for row in equity_rows:
        value = row.get(key)
        if value is None:
            continue
        values.append(float(value))
        days.append(str(row["date"]))
    if len(values) < 2:
        return None
    return equity_metrics(values, days)


def run_backtest(
    *,
    surge_db: Path | str,
    daily_db: Path | str,
    scheme: str,
    start: date,
    end: date | None = None,
    benchmark_closes: dict[str, dict[date, float]] | None = None,
    run_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run one scheme and return a serialisable result (no files written)."""
    if scheme not in SCHEME_EVENTS:
        raise BacktestError(f"未知方案：{scheme}；可选 {', '.join(SCHEMES)}")
    source = DailyStoreBacktestSource(daily_db)
    try:
        if end is None:
            forecast = source.store.latest_trading_day()
            if forecast is None:
                raise BacktestError("日线库没有交易日历")
            end = forecast
        start_index = bisect.bisect_left(source.calendar, start)
        end_index = bisect.bisect_right(source.calendar, end) - 1
        if start_index >= len(source.calendar):
            raise BacktestError(f"日线库没有 {start} 之后的交易日")
        if end_index < start_index:
            raise BacktestError("结束日早于起始日")
        start_day = source.calendar[start_index]
        cutoff = source.calendar[end_index]

        signals = load_signals(surge_db, scheme, start_day, cutoff)
        plans = [evaluate_signal(source, signal, end_index, cutoff) for signal in signals]
        _assert_no_lookahead(source, plans)

        per_trade = [per_trade_row(plan) for plan in plans]

        if benchmark_closes is None:
            from .backtest_benchmarks import load_benchmarks

            benchmark_closes = load_benchmarks(
                run_root or default_run_root(),
                start=start_day - timedelta(days=90),
                end=cutoff,
            )
        portfolio = run_portfolio(plans, source, start_index, end_index, benchmark_closes=benchmark_closes)
        skip_map = {
            (str(row["code"]), str(row["signal_date"]), int(row["round_id"])): str(row["reason"])
            for row in portfolio["skipped"]
        }
        for row in per_trade:
            reason = skip_map.get((str(row["code"]), str(row["signal_date"]), int(row["round_id"])))
            if reason is not None:
                row["portfolio_skip_reason"] = reason

        status_counts: dict[str, int] = defaultdict(int)
        for plan in plans:
            status_counts[plan.status] += 1
        for plan in plans:
            if plan.status == "ok" and plan.unclosed:
                status_counts["unclosed"] += 1
        skipped_counts: dict[str, int] = defaultdict(int)
        for row in portfolio["skipped"]:
            skipped_counts[str(row["reason"])] += 1

        executed = [row for row in per_trade if row.get("return_pct") not in ("", None)]
        first_score_rows = [row for row in executed if scheme in {"p1", "p2"}]
        environments = _environment_map(benchmark_closes.get("hs300", {}))
        board_cache: dict[str, str] = {}

        def board_of(row: dict[str, Any]) -> str:
            code = str(row["code"])
            if code not in board_cache:
                info = source.security(code)
                board_cache[code] = _board_label(None if info is None else info.board)
            return board_cache[code]

        groups = {
            "by_year": group_statistics(executed, lambda row: str(row["signal_date"])[:4]),
            "by_environment": group_statistics(
                executed,
                lambda row: environments.get(date.fromisoformat(str(row["signal_date"])), "未知"),
                [
                    "沪深300 收盘在 MA20 上方",
                    "沪深300 收盘在 MA20 下方",
                    "未知",
                ],
            ),
            "by_board": group_statistics(
                executed, board_of, ["主板", "创业板", "科创板", "未知"]
            ),
            "by_first_score": (
                group_statistics(
                    first_score_rows,
                    lambda row: _bucket_first_score(None if row.get("first_score") is None else int(row["first_score"])),
                    ["<60", "60–69", "70–79", "80–89", "90–100", "未知"],
                )
                if scheme in {"p1", "p2"}
                else []
            ),
            "by_base_score": group_statistics(
                executed,
                lambda row: _bucket_base_score(None if row.get("base_score") is None else int(row["base_score"])),
                ["0", "80", "90", "100", "未知"],
            ),
        }
        out_of_sample = {}
        for label, predicate in (
            ("2020–2023", lambda year: year <= 2023),
            ("2024–至今", lambda year: year >= 2024),
        ):
            members = [
                row for row in executed if predicate(int(str(row["signal_date"])[:4]))
            ]
            out_of_sample[label] = summarize_returns(members)

        portfolio_stats = portfolio_metrics(portfolio["equity_rows"], portfolio["trades"], portfolio["turnover_notional"])
        per_trade_stats = summarize_returns(per_trade)
        per_trade_stats["signals"] = len(signals)
        per_trade_stats["unfilled_limit_up"] = status_counts.get("unfilled_limit_up", 0)
        per_trade_stats["suspension_abandoned"] = status_counts.get("suspension_abandoned", 0)
        per_trade_stats["out_of_range"] = status_counts.get("out_of_range", 0)
        per_trade_stats["skipped_full"] = skipped_counts.get("仓位已满跳过", 0)
        per_trade_stats["skipped_held"] = skipped_counts.get("已持有该股跳过", 0)
        per_trade_stats["histogram"] = histogram(per_trade)

        run_id = f"{scheme}_{start_day.strftime('%Y%m%d')}_{cutoff.strftime('%Y%m%d')}"
        summary = {
            "run_id": run_id,
            "scheme": scheme,
            "scheme_label": SCHEME_LABELS[scheme],
            "signal_event": SCHEME_EVENTS[scheme],
            "start": start_day.isoformat(),
            "requested_start": start.isoformat(),
            "cutoff": cutoff.isoformat(),
            "requested_end": end.isoformat(),
            "signal_count": len(signals),
            "status_counts": dict(status_counts),
            "skipped_counts": dict(skipped_counts),
            "per_trade": per_trade_stats,
            "portfolio": portfolio_stats,
            "benchmarks": {
                "hs300": _benchmark_metrics(portfolio["equity_rows"], "hs300"),
                "csi1000": _benchmark_metrics(portfolio["equity_rows"], "csi1000"),
            },
            "by_year": yearly_returns(portfolio["equity_rows"]),
            "yearly_trade_stats": groups["by_year"],
            "out_of_sample": out_of_sample,
            "groups": groups,
            "rules": {
                "entry": "信号日的下一个交易日开盘价（未复权）；开盘即涨停买不到；停牌顺延最多 5 个交易日。",
                "exit": "主升浪池移出日的下一个交易日开盘价（未复权）；开盘即跌停顺延。",
                "commission": "佣金万 2.5，双边，单笔最低 5 元。",
                "stamp_tax": "卖出印花税：2023-08-28 前 0.1%，之后 0.05%。",
                "slippage": "买入 +0.1%，卖出 -0.1%。",
                "adjustment": "成交用未复权价；持有期收益用复权因子比例衔接，避免除权日假亏损。",
                "per_trade_capital": PER_TRADE_CAPITAL,
                "initial_capital": INITIAL_CAPITAL,
                "max_positions": MAX_POSITIONS,
                "position_size": "买入当时总资产（按当日开盘价重估）的 1/10；仓满按信号日排序取前几名，其余跳过。",
                "min_position_budget": MIN_POSITION_BUDGET,
                "risk_free_rate": RISK_FREE_RATE,
            },
            "disclaimer": "按冻结规则的历史模拟，不代表未来收益，不是投资建议。",
        }
        return {
            "summary": summary,
            "per_trade_rows": per_trade,
            "portfolio_trades": portfolio["trades"],
            "skipped": portfolio["skipped"],
            "equity_rows": portfolio["equity_rows"],
            "plans": plans,
            "benchmark_closes": benchmark_closes,
        }
    finally:
        source.close()


def _assert_no_lookahead(source: BacktestSource, plans: list[TradePlan]) -> None:
    for plan in plans:
        if plan.status != "ok":
            continue
        signal_index = source.index[plan.signal.signal_date]
        if plan.buy_index is None or plan.buy_index <= signal_index:
            raise BacktestError(f"未来数据检查失败：{plan.signal.code} 买入日不晚于信号日")
        if plan.sell_index is not None and plan.buy_index is not None and plan.sell_index <= plan.buy_index:
            raise BacktestError(f"未来数据检查失败：{plan.signal.code} 卖出日不晚于买入日")


def default_run_root() -> Path:
    from .outputs import repo_root

    return repo_root() / "runtime" / "surge" / "backtest"


def write_result(result: dict[str, Any], run_root: Path | str | None = None) -> Path:
    """Write CSV/JSON/report/charts under ``<run_root>/<run_id>``."""
    root = Path(run_root) if run_root else default_run_root()
    run_dir = root / str(result["summary"]["run_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(run_dir / "trades.csv", result["per_trade_rows"])
    _write_csv(run_dir / "portfolio_trades.csv", result["portfolio_trades"])
    _write_csv(run_dir / "skipped.csv", result["skipped"])
    _write_csv(run_dir / "equity.csv", result["equity_rows"])

    result["summary"]["paths"] = {
        "run_dir": str(run_dir),
        "trades": str(run_dir / "trades.csv"),
        "portfolio_trades": str(run_dir / "portfolio_trades.csv"),
        "skipped": str(run_dir / "skipped.csv"),
        "equity": str(run_dir / "equity.csv"),
        "summary": str(run_dir / "summary.json"),
        "report": str(run_dir / "report.md"),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    from .backtest_report import write_report

    write_report(result, run_dir)
    return run_dir


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def load_summary(run_dir: Path | str) -> dict[str, Any]:
    path = Path(run_dir) / "summary.json"
    if not path.is_file():
        raise BacktestError(f"回测结果不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))
