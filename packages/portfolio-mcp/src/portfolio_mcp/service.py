"""Tool implementations: import preview/commit, edits, cash, clear, valuation."""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from portfolio_mcp.csvparse import parse_csv_text
from portfolio_mcp.envelope import envelope
from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.fields import (
    MAX_POSITIONS,
    merge_position,
    validate_cash,
    validate_cost_price,
    validate_position,
    validate_positions,
    validate_qty,
    validate_update_fields,
)
from portfolio_mcp.kline import GatewayKlineClient, KlineSeries
from portfolio_mcp.quotes import GatewayQuoteClient, Quote
from portfolio_mcp.risk import (
    MIN_BARS,
    annualized_volatility,
    asset_class_of,
    beta,
    board_of,
    correlation,
    is_broad_index_etf,
    max_drawdown,
    replay_returns,
    sum_by,
)
from portfolio_mcp.store import PortfolioState, PortfolioStore
from portfolio_mcp.symbols import normalize_symbol

CONFIRM_TTL_SECONDS = 600
MAX_PENDING_TOKENS = 64
CN_TZ = timezone(timedelta(hours=8))  # A-share market time; no DST, no tzdata dependency

DEFAULT_BENCHMARK = "000300.SH"
BENCHMARKS: tuple[str, ...] = (
    "000300.SH",
    "000001.SH",
    "000905.SH",
    "000852.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
)
RISK_WINDOW_MIN = 60
RISK_WINDOW_MAX = 500
RISK_METHODOLOGY = (
    "以基准交易日为日历，按最新收盘价×数量的权重固定回放；"
    "持仓在自身无 K 线的交易日按前值填充（当日收益 0），年化按 252 个交易日计算。"
)

EMPTY_HINT = (
    "持仓簿为空。只有在用户主动要求记录持仓、并确认 preview 差异后才写入；"
    "不要把持仓常驻写进 AGENTS.md，也不要外传。"
)
RISK_EMPTY_HINT = "持仓簿为空，未请求 K 线；请先按 preview → 用户确认 → commit 的流程导入持仓。"

_UNSET = object()


@dataclass
class _PendingImport:
    rows: list[dict[str, Any]]
    mode: str
    fingerprint: str
    created_at: float
    expires_at: float


def _name_key(value: str) -> str:
    return "".join(value.split()).casefold()


def _in_trading_session(moment: datetime) -> bool:
    if moment.weekday() >= 5:
        return False
    current = moment.time()
    return clock_time(9, 30) <= current <= clock_time(11, 30) or clock_time(13, 0) <= current <= clock_time(15, 0)


def _round_floats(value: Any, digits: int = 8) -> Any:
    """Round nested floats so risk output never looks like an account number."""
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {key: _round_floats(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item, digits) for item in value]
    return value


class PortfolioService:
    def __init__(
        self,
        store: PortfolioStore,
        *,
        quotes: Any = _UNSET,
        kline: Any = _UNSET,
        token_ttl: int = CONFIRM_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._store = store
        self._quotes = GatewayQuoteClient() if quotes is _UNSET else quotes
        self._kline = GatewayKlineClient() if kline is _UNSET else kline
        self._token_ttl = token_ttl
        self._clock = clock
        self._today = today
        self._pending: dict[str, _PendingImport] = {}
        self._token_lock = threading.Lock()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _args(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise PortfolioError("invalid_argument", "arguments must be a JSON object")
        return value

    @staticmethod
    def _only(args: Mapping[str, Any], allowed: Sequence[str]) -> None:
        extra = sorted(key for key in args if key not in allowed)
        if extra:
            raise PortfolioError(
                "invalid_argument", "unexpected argument(s): " + ", ".join(extra)
            )

    def _error(self, exc: PortfolioError) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if exc.field is not None:
            data["field"] = exc.field
        if exc.details:
            data.update(exc.details)
        return envelope(
            status="error",
            data=data,
            error_code=exc.code,
            error_message=exc.message,
        )

    def _purge_tokens(self, now: float) -> None:
        for token, record in list(self._pending.items()):
            if now >= record.expires_at:
                del self._pending[token]
        if len(self._pending) > MAX_PENDING_TOKENS:
            oldest = sorted(self._pending.items(), key=lambda item: item[1].created_at)
            for token, _ in oldest[: len(self._pending) - MAX_PENDING_TOKENS]:
                del self._pending[token]

    @staticmethod
    def _fingerprint(rows: list[dict[str, Any]], mode: str) -> str:
        return hashlib.sha256(
            json.dumps(
                {"rows": rows, "mode": mode},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _issue_token(self, rows: list[dict[str, Any]], mode: str) -> tuple[str, str]:
        now = self._clock()
        with self._token_lock:
            self._purge_tokens(now)
            ticket = secrets.token_urlsafe(24)
            digest = self._fingerprint(rows, mode)
            self._pending[ticket] = _PendingImport(
                rows=copy.deepcopy(rows),
                mode=mode,
                fingerprint=digest,
                created_at=now,
                expires_at=now + self._token_ttl,
            )
            return ticket, digest

    @staticmethod
    def _diff(
        existing: list[dict[str, Any]], rows: list[dict[str, Any]], mode: str
    ) -> dict[str, Any]:
        before = {row["code"]: row for row in existing}
        after = {row["code"]: row for row in rows}
        added = [row for code, row in after.items() if code not in before]
        changed: list[dict[str, Any]] = []
        unchanged: list[str] = []
        for code, row in after.items():
            if code not in before:
                continue
            old = before[code]
            if old == row:
                unchanged.append(code)
                continue
            fields = sorted(name for name in row if old.get(name) != row.get(name))
            changed.append({"code": code, "before": old, "after": row, "fields": fields})
        if mode == "replace":
            removed = [row for code, row in before.items() if code not in after]
        else:
            removed = []
        return {
            "added": added,
            "changed": changed,
            "removed": removed,
            "unchanged": unchanged,
        }

    def _quote_warnings(
        self, rows: list[dict[str, Any]], quotes: Any = _UNSET
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for row in rows:
            if row["qty"] < 100 and row["code"].startswith("6"):
                warnings.append(
                    {
                        "code": "qty_suspected_lots",
                        "message": (
                            f"{row['code']} 数量为 {row['qty']}，小于 100 且为 6 开头主板股票；"
                            "请确认券商表里是“股”还是“手”（1 手 = 100 股）"
                        ),
                    }
                )
        if quotes is _UNSET:
            if self._quotes is None or not rows:
                return warnings
            try:
                quotes = self._quotes.fetch([row["code"] for row in rows])
            except Exception:
                warnings.append(
                    {"code": "quote_unavailable", "message": "行情取不到，未能核对名称与成本"}
                )
                return warnings
        for row in rows:
            quote = quotes.get(row["code"])
            if quote is None:
                warnings.append(
                    {
                        "code": "quote_missing",
                        "message": f"{row['code']} 在行情源没有返回，代码可能不存在或已退市",
                    }
                )
                continue
            if quote.name and _name_key(quote.name) != _name_key(row["name"]):
                warnings.append(
                    {
                        "code": "name_mismatch",
                        "message": f"{row['code']} 名称与行情不符：表内 {row['name']}，行情 {quote.name}",
                    }
                )
            if quote.price and quote.price > 0:
                deviation = abs(row["cost_price"] - quote.price) / quote.price
                if deviation > 0.8:
                    warnings.append(
                        {
                            "code": "cost_deviation_high",
                            "message": (
                                f"{row['code']} 成本价 {row['cost_price']} 与现价 {quote.price} "
                                f"偏离 {deviation:.0%}（>80%），请核对复权或币种"
                            ),
                        }
                    )
        return warnings

    # ------------------------------------------------------------------ tools

    def get(self, args: Any = None) -> dict[str, Any]:
        try:
            self._only(self._args(args), ())
        except PortfolioError as exc:
            return self._error(exc)
        snap = self._store.snapshot()
        data: dict[str, Any] = {
            "positions": snap.positions,
            "count": len(snap.positions),
            "cash": snap.cash,
            "as_of": snap.as_of,
            "updated_at": snap.updated_at,
            "empty": not snap.positions,
            "private": True,
            "untrusted_text": False,
        }
        if not snap.positions:
            data["hint"] = EMPTY_HINT
        return envelope(
            status="empty" if not snap.positions else "ready",
            data=data,
            warnings=snap.warnings,
            private=True,
        )

    def parse_csv(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("text",))
            if "text" not in payload:
                raise PortfolioError("invalid_argument", "text is required", field="text")
            parsed = parse_csv_text(payload["text"], today=self._today())
        except PortfolioError as exc:
            return self._error(exc)
        data = dict(parsed)
        data["private"] = True
        data["untrusted_text"] = False
        return envelope(
            status="empty" if not parsed["rows"] else "ready",
            data=data,
            private=True,
        )

    def import_preview(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("rows", "mode"))
            if "rows" not in payload:
                raise PortfolioError("invalid_argument", "rows is required", field="rows")
            mode = payload.get("mode", "replace")
            if mode not in ("replace", "merge"):
                raise PortfolioError(
                    "invalid_argument", "mode must be 'replace' or 'merge'", field="mode"
                )
            rows = validate_positions(payload["rows"], today=self._today())
            existing = self._store.snapshot().positions

            if mode == "merge":
                merged = {row["code"]: row for row in existing}
                for row in rows:
                    merged[row["code"]] = row
                total_after = len(merged)
            else:
                total_after = len(rows)
            if total_after > MAX_POSITIONS:
                raise PortfolioError(
                    "too_many_positions", f"at most {MAX_POSITIONS} positions are supported"
                )

            diff = self._diff(existing, rows, mode)
            token, digest = self._issue_token(rows, mode)
            warnings = self._quote_warnings(rows)
            data = {
                "confirm_token": token,
                "expires_in_seconds": self._token_ttl,
                "plan_hash": digest[:16],
                "mode": mode,
                "summary": {
                    "added": len(diff["added"]),
                    "changed": len(diff["changed"]),
                    "removed": len(diff["removed"]),
                    "unchanged": len(diff["unchanged"]),
                    "total_after": total_after,
                },
                "added": diff["added"],
                "changed": diff["changed"],
                "removed": diff["removed"],
                "unchanged": diff["unchanged"],
            }
            return envelope(status="ready", data=data, warnings=warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def import_commit(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("confirm_token",))
            token = payload.get("confirm_token")
            if not isinstance(token, str) or not token:
                raise PortfolioError(
                    "invalid_token",
                    "confirm_token is missing, invalid, expired or already used; call preview again",
                    field="confirm_token",
                )
            now = self._clock()
            with self._token_lock:
                record = self._pending.pop(token, None)
                if record is None or now >= record.expires_at:
                    raise PortfolioError(
                        "invalid_token",
                        "confirm_token is invalid, expired or already used; call preview again",
                        field="confirm_token",
                    )
                if self._fingerprint(record.rows, record.mode) != record.fingerprint:
                    raise PortfolioError(
                        "invalid_token",
                        "confirm_token no longer matches its preview; call preview again",
                        field="confirm_token",
                    )

            def change(state: PortfolioState) -> PortfolioState:
                if record.mode == "replace":
                    positions = list(record.rows)
                else:
                    positions = list(state.positions)
                    index = {row["code"]: position for position, row in enumerate(positions)}
                    for row in record.rows:
                        if row["code"] in index:
                            positions[index[row["code"]]] = row
                        else:
                            index[row["code"]] = len(positions)
                            positions.append(row)
                return PortfolioState(
                    positions=positions,
                    cash=state.cash,
                    as_of=self._today().isoformat(),
                    updated_at=state.updated_at, trades=state.trades,
                )

            mutation = self._store.apply(change)
            diff = self._diff(mutation.before.positions, mutation.after.positions, "replace")
            data = {
                "written": True,
                "mode": record.mode,
                "as_of": mutation.after.as_of,
                "before_count": len(mutation.before.positions),
                "after_count": len(mutation.after.positions),
                "added": len(diff["added"]),
                "changed": len(diff["changed"]),
                "removed": len(diff["removed"]),
                "positions": mutation.after.positions,
            }
            return envelope(status="ready", data=data, warnings=mutation.warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def record_trade(self, args: Any) -> dict[str, Any]:
        from .trades import normalize_trade, apply_trade
        try:
            payload=self._args(args)
            self._only(payload,('id','code','side','date','shares','price','fees','confirm'))
            trade=normalize_trade(payload,self._today())
            if payload.get('confirm') is True:
                result=self._store.apply(lambda state:apply_trade(state,trade))
                return envelope(status='ready',data={'written':result.changed,'trade':trade},private=True)
            preview=apply_trade(self._store.snapshot(),trade)
            return envelope(status='ready',data={'written':False,'preview_positions':preview.positions,'cash':preview.cash,'trade':trade},private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def trade_history(self, args: Any) -> dict[str, Any]:
        try:
            payload=self._args(args)
            self._only(payload,('offset','limit'))
            offset,limit=payload.get('offset',0),payload.get('limit',50)
            if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=100:
                raise PortfolioError('invalid_value','分页参数无效')
            rows=self._store.snapshot().trades
            return envelope(status='ready',data={'total':len(rows),'trades':rows[offset:offset+limit]},private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def add_position(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(
                payload,
                (
                    "code",
                    "quantity",
                    "cost",
                    "name",
                    "available",
                    "opened_at",
                    "industry",
                    "note",
                    "merge",
                ),
            )
            symbol = normalize_symbol(payload.get("code"))
            if "quantity" not in payload:
                raise PortfolioError(
                    "invalid_argument", "quantity is required", field="quantity"
                )
            if "cost" not in payload:
                raise PortfolioError("invalid_argument", "cost is required", field="cost")
            quantity = validate_qty(payload["quantity"])
            cost = validate_cost_price(payload["cost"])
            merge = payload.get("merge", True)
            if not isinstance(merge, bool):
                raise PortfolioError("invalid_value", "merge must be a boolean", field="merge")

            name = payload.get("name")
            if name in (None, ""):
                name = None
            provided: dict[str, Any] = {
                "name": name,
                "available_qty": payload.get("available"),
                "opened_date": payload.get("opened_at"),
                "industry": payload.get("industry"),
                "note": payload.get("note"),
            }

            quotes: dict[str, Quote] | None = None
            if self._quotes is not None:
                try:
                    quotes = self._quotes.fetch([symbol.canonical])
                except Exception:
                    quotes = None
            if name is None:
                quote = (quotes or {}).get(symbol.canonical)
                name = quote.name if quote is not None and quote.name else symbol.canonical

            new_row = validate_position(
                {
                    "code": symbol.canonical,
                    "name": name,
                    "qty": quantity,
                    "available_qty": provided["available_qty"],
                    "cost_price": cost,
                    "opened_date": provided["opened_date"],
                    "industry": provided["industry"],
                    "note": provided["note"],
                },
                today=self._today(),
            )

            formula: str | None = None

            def change(state: PortfolioState) -> PortfolioState:
                nonlocal formula
                current = next(
                    (row for row in state.positions if row["code"] == symbol.canonical),
                    None,
                )
                if current is None:
                    if len(state.positions) >= MAX_POSITIONS:
                        raise PortfolioError(
                            "too_many_positions",
                            f"at most {MAX_POSITIONS} positions are supported",
                        )
                    positions = list(state.positions) + [new_row]
                else:
                    if not merge:
                        raise PortfolioError(
                            "invalid",
                            "position already exists; set merge=true to add to it, or use "
                            "portfolio_update_position to edit it",
                            field="merge",
                            details={"hint": "use portfolio_update_position"},
                        )
                    total_qty = current["qty"] + quantity
                    total_value = current["qty"] * current["cost_price"] + quantity * cost
                    total_cost = round(total_value / total_qty, 4)
                    merged = dict(current)
                    merged["qty"] = total_qty
                    merged["cost_price"] = total_cost
                    for key, value in provided.items():
                        if value is not None:
                            merged[key] = value
                    positions = [
                        merged if row["code"] == symbol.canonical else row
                        for row in state.positions
                    ]
                    formula = (
                        f"{current['qty']} × {current['cost_price']:.4f} + "
                        f"{quantity} × {cost:.4f} = {total_value:.4f}；"
                        f"{total_value:.4f} ÷ {total_qty} = {total_cost:.4f}"
                    )
                return PortfolioState(
                    positions=positions,
                    cash=state.cash,
                    as_of=self._today().isoformat(),
                    updated_at=state.updated_at, trades=state.trades,
                )

            mutation = self._store.apply(change)
            before = next(
                (row for row in mutation.before.positions if row["code"] == symbol.canonical),
                None,
            )
            after = next(
                row for row in mutation.after.positions if row["code"] == symbol.canonical
            )
            data: dict[str, Any] = {
                "action": "merged" if before is not None else "added",
                "code": symbol.canonical,
                "before": before,
                "after": after,
                "count": len(mutation.after.positions),
                "position_count": len(mutation.after.positions),
                "before_count": len(mutation.before.positions),
                "after_count": len(mutation.after.positions),
                "merged": before is not None,
            }
            if formula is not None:
                data["formula"] = formula
            warnings = list(mutation.warnings)
            if quotes is not None:
                warnings.extend(self._quote_warnings([after], quotes=quotes))
            return envelope(status="ready", data=data, warnings=warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def update_position(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("code", "fields"))
            symbol = normalize_symbol(payload.get("code"))
            if "fields" not in payload:
                raise PortfolioError("invalid_argument", "fields is required", field="fields")
            partial = validate_update_fields(payload["fields"], today=self._today())

            def change(state: PortfolioState) -> PortfolioState:
                positions = list(state.positions)
                for index, row in enumerate(positions):
                    if row["code"] == symbol.canonical:
                        positions[index] = merge_position(row, partial, today=self._today())
                        return PortfolioState(
                            positions=positions,
                            cash=state.cash,
                            as_of=state.as_of,
                            updated_at=state.updated_at, trades=state.trades,
                        )
                raise PortfolioError(
                    "not_found", f"position not found: {symbol.canonical}", field="code"
                )

            mutation = self._store.apply(change)
            before = next(
                row for row in mutation.before.positions if row["code"] == symbol.canonical
            )
            after = next(
                row for row in mutation.after.positions if row["code"] == symbol.canonical
            )
            data = {
                "code": symbol.canonical,
                "before": before,
                "after": after,
                "changed": sorted(name for name in after if before.get(name) != after.get(name)),
            }
            return envelope(status="ready", data=data, warnings=mutation.warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def remove_position(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("code",))
            symbol = normalize_symbol(payload.get("code"))

            def change(state: PortfolioState) -> PortfolioState:
                kept = [row for row in state.positions if row["code"] != symbol.canonical]
                if len(kept) == len(state.positions):
                    raise PortfolioError(
                        "not_found", f"position not found: {symbol.canonical}", field="code"
                    )
                return PortfolioState(
                    positions=kept,
                    cash=state.cash,
                    as_of=state.as_of,
                    updated_at=state.updated_at, trades=state.trades,
                )

            mutation = self._store.apply(change)
            before = next(
                row for row in mutation.before.positions if row["code"] == symbol.canonical
            )
            data = {
                "code": symbol.canonical,
                "before": before,
                "after": None,
                "removed": before,
                "before_count": len(mutation.before.positions),
                "after_count": len(mutation.after.positions),
            }
            return envelope(status="ready", data=data, warnings=mutation.warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def set_cash(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("cash",))
            if "cash" not in payload:
                raise PortfolioError("invalid_argument", "cash is required", field="cash")
            cash = validate_cash(payload["cash"])

            def change(state: PortfolioState) -> PortfolioState:
                return PortfolioState(
                    positions=state.positions,
                    cash=cash,
                    as_of=state.as_of,
                    updated_at=state.updated_at, trades=state.trades,
                )

            mutation = self._store.apply(change)
            data = {
                "cash_before_cny": mutation.before.cash,
                "cash_after_cny": mutation.after.cash,
                "cash": mutation.after.cash,
            }
            return envelope(status="ready", data=data, warnings=mutation.warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    def clear(self, args: Any) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("confirm",))
            if payload.get("confirm") is not True:
                raise PortfolioError(
                    "confirmation_required",
                    "clearing the whole portfolio requires confirm=true",
                    field="confirm",
                )

            def change(state: PortfolioState) -> PortfolioState:
                return PortfolioState(
                    positions=[],
                    cash=None,
                    as_of=None,
                    updated_at=state.updated_at,
                )

            mutation = self._store.apply(change)
            data = {
                "cleared": mutation.changed,
                "cleared_positions": len(mutation.before.positions),
                "before_count": len(mutation.before.positions),
                "after_count": 0,
            }
            return envelope(status="ready", data=data, warnings=mutation.warnings, private=True)
        except PortfolioError as exc:
            return self._error(exc)

    # -------------------------------------------------------------- valuation

    def valuation(self, args: Any = None) -> dict[str, Any]:
        try:
            self._only(self._args(args), ())
        except PortfolioError as exc:
            return self._error(exc)

        snap = self._store.snapshot()
        warnings: list[dict[str, Any]] = list(snap.warnings)
        today = self._today()
        now_cn = datetime.now(CN_TZ)
        cash = snap.cash or 0.0
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if not snap.positions:
            warnings.append({"code": "empty_portfolio", "message": "持仓簿为空，未请求行情"})
            data = self._valuation_data(
                [], cash, fetched_at, quote_time=None, total_count=0
            )
            return envelope(status="empty", data=data, warnings=warnings, private=True)

        quotes: dict[str, Quote] = {}
        fetch_failed = False
        if self._quotes is None:
            fetch_failed = True
            warnings.append(
                {"code": "quote_unavailable", "message": "未配置行情客户端，全部持仓标为 price_unavailable"}
            )
        else:
            try:
                quotes = self._quotes.fetch([row["code"] for row in snap.positions])
            except Exception:
                fetch_failed = True
                warnings.append(
                    {"code": "quote_unavailable", "message": "行情源取不到，全部持仓标为 price_unavailable"}
                )

        items = [
            self._value_position(row, quotes.get(row["code"]), today)
            for row in snap.positions
        ]
        if not fetch_failed:
            for item in items:
                if item["price_unavailable"]:
                    warnings.append(
                        {
                            "code": "price_unavailable",
                            "message": f"{item['code']} 行情缺失或停牌，已从汇总与权重中排除",
                        }
                    )

        quote_times = [item["quote_time"] for item in items if item["quote_time"]]
        quote_time = max(quote_times) if quote_times else None
        if quote_time:
            stale = not _in_trading_session(now_cn)
            try:
                quote_day = datetime.strptime(quote_time[:10], "%Y-%m-%d").date()
                stale = stale or quote_day != now_cn.date()
            except ValueError:
                pass
            if stale:
                warnings.append(
                    {
                        "code": "stale_quote",
                        "message": "当前为非交易时段或行情非当日，价格是上一交易时段的最后值",
                    }
                )

        data = self._valuation_data(
            items, cash, fetched_at, quote_time=quote_time
        )
        return envelope(status="ready", data=data, warnings=warnings, private=True)

    @staticmethod
    def _value_position(
        row: dict[str, Any], quote: Quote | None, today: date
    ) -> dict[str, Any]:
        price = None
        if quote is not None and quote.price is not None and quote.price > 0:
            price = quote.price
        price_unavailable = price is None

        qty = row["qty"]
        cost_price = row["cost_price"]
        cost_value = cost_price * qty
        market_value = price * qty if price is not None else None
        pnl = market_value - cost_value if market_value is not None else None
        pnl_pct = (pnl / cost_value * 100) if pnl is not None and cost_value > 0 else None

        limit_up = quote.limit_up if quote is not None else None
        limit_down = quote.limit_down if quote is not None else None
        at_limit_up = (
            price is not None and limit_up is not None and price >= limit_up - 0.0001
        )
        at_limit_down = (
            price is not None and limit_down is not None and price <= limit_down + 0.0001
        )

        available = row["available_qty"]
        if available is not None:
            sellable_qty = available
            sellable_today = available > 0
        else:
            bought_today = row["opened_date"] == today.isoformat()
            sellable_qty = 0 if bought_today else qty
            sellable_today = not bought_today

        change_pct = quote.change_pct if quote is not None and price is not None else None
        prev_close = quote.prev_close if quote is not None else None

        return {
            "code": row["code"],
            "name": row["name"],
            "qty_shares": qty,
            "available_qty_shares": available,
            "cost_price_cny_per_share": cost_price,
            "price_cny": price,
            "prev_close_cny": prev_close,
            "change_pct": change_pct,
            "market_value_cny": market_value,
            "cost_value_cny": cost_value,
            "pnl_cny": pnl,
            "pnl_pct": pnl_pct,
            "weight": 0.0,
            "weight_incl_cash": 0.0,
            "limit_up_cny": limit_up,
            "limit_down_cny": limit_down,
            "at_limit_up": at_limit_up,
            "at_limit_down": at_limit_down,
            "sellable_today": sellable_today,
            "sellable_qty_shares": sellable_qty,
            "price_unavailable": price_unavailable,
            "quote_time": quote.time if quote is not None else None,
            # Plain-name aliases kept for callers that use the task's prose field names.
            "qty": qty,
            "available_qty": available,
            "cost_price": cost_price,
            "price": price,
            "prev_close": prev_close,
            "market_value": market_value,
            "cost_value": cost_value,
            "pnl": pnl,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "sellable_qty": sellable_qty,
        }

    @staticmethod
    def _valuation_data(
        items: list[dict[str, Any]],
        cash: float,
        fetched_at: str,
        *,
        quote_time: str | None,
        total_count: int | None = None,
    ) -> dict[str, Any]:
        priced = [item for item in items if item["market_value_cny"] is not None]
        total_mv = sum(item["market_value_cny"] for item in priced)
        total_cost = sum(item["cost_value_cny"] for item in priced)
        total_pnl = total_mv - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        total_assets = total_mv + cash

        for item in items:
            value = item["market_value_cny"]
            item["weight"] = (value / total_mv) if value is not None and total_mv > 0 else 0.0
            item["weight_incl_cash"] = (
                (value / total_assets) if value is not None and total_assets > 0 else 0.0
            )

        weights = sorted((item["weight"] for item in items), reverse=True)
        weights_cash = sorted((item["weight_incl_cash"] for item in items), reverse=True)
        hhi = sum(weight * weight for weight in weights)
        hhi_cash = sum(weight * weight for weight in weights_cash)

        data: dict[str, Any] = {
            "positions": items,
            "count": len(items) if total_count is None else total_count,
            "priced_count": len(priced),
            "unpriced_count": len(items) - len(priced),
            "total_market_value_cny": total_mv,
            "total_cost_cny": total_cost,
            "total_pnl_cny": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "cash_cny": cash,
            "total_assets_cny": total_assets,
            "top1_weight": weights[0] if weights else 0.0,
            "top5_weight": sum(weights[:5]),
            "hhi": hhi,
            "effective_n": (1.0 / hhi) if hhi > 0 else 0.0,
            "top1_weight_incl_cash": weights_cash[0] if weights_cash else 0.0,
            "top5_weight_incl_cash": sum(weights_cash[:5]),
            "hhi_incl_cash": hhi_cash,
            "effective_n_incl_cash": (1.0 / hhi_cash) if hhi_cash > 0 else 0.0,
            "quote_time": quote_time,
            "fetched_at": fetched_at,
            "private": True,
            "untrusted_text": False,
            # Plain-name aliases.
            "total_market_value": total_mv,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "cash": cash,
            "total_assets": total_assets,
        }
        return data

    # ------------------------------------------------------------------ risk

    @staticmethod
    def _normalize_benchmark(value: Any) -> str:
        if not isinstance(value, str):
            raise PortfolioError(
                "invalid_benchmark",
                "benchmark must be one of: " + ", ".join(BENCHMARKS),
                field="benchmark",
            )
        text = value.strip().upper()
        if text not in BENCHMARKS:
            raise PortfolioError(
                "invalid_benchmark",
                "benchmark must be one of: " + ", ".join(BENCHMARKS),
                field="benchmark",
            )
        return text

    @staticmethod
    def _benchmark_symbol(benchmark: str) -> str:
        digits, exchange = benchmark.split(".", 1)
        return f"{exchange.lower()}{digits}"

    @staticmethod
    def _excluded_row(
        row: dict[str, Any],
        reason: str,
        message: str,
        bars: int | None,
        latest_close: float | None,
    ) -> dict[str, Any]:
        return {
            "code": row["code"],
            "name": row["name"],
            "qty_shares": row["qty"],
            "reason": reason,
            "message": message,
            "bars": bars,
            "latest_close_cny": latest_close,
            "market_value_cny": None if latest_close is None else latest_close * row["qty"],
        }

    @staticmethod
    def _risk_empty_data(
        benchmark: str,
        window: int,
        cash: float,
        fetched_at: str,
        *,
        empty_book: bool,
    ) -> dict[str, Any]:
        return {
            "benchmark": benchmark,
            "benchmark_code": benchmark,
            "window_days_requested": window,
            "window_days": window,
            "observations": 0,
            "annualized_vol_ratio": None,
            "beta": None,
            "max_drawdown_ratio": None,
            "benchmark_annualized_vol_ratio": None,
            "benchmark_max_drawdown_ratio": None,
            "as_of_bar_date": None,
            "positions": [],
            "excluded": [],
            "top1_weight_ratio": 0.0,
            "top5_weight_ratio": 0.0,
            "hhi": 0.0,
            "effective_n": 0.0,
            "broad_index_etfs": [],
            "broad_index_etf_codes": [],
            "broad_index_etf_weight_ratio": 0.0,
            "largest_pair_correlations": [],
            "exposure_by_board": {},
            "exposure_by_industry": {},
            "asset_class": {},
            "cash_share_ratio": 1.0 if empty_book and cash > 0 else 0.0,
            "fetched_at": fetched_at,
            "methodology": RISK_METHODOLOGY,
            "private": True,
            "untrusted_text": False,
        }

    def risk(self, args: Any = None) -> dict[str, Any]:
        try:
            payload = self._args(args)
            self._only(payload, ("window_days", "benchmark"))
            window = payload.get("window_days", 250)
            if (
                isinstance(window, bool)
                or not isinstance(window, int)
                or not RISK_WINDOW_MIN <= window <= RISK_WINDOW_MAX
            ):
                raise PortfolioError(
                    "invalid_argument",
                    "window_days must be an integer between 60 and 500",
                    field="window_days",
                )
            benchmark = self._normalize_benchmark(payload.get("benchmark", DEFAULT_BENCHMARK))
        except PortfolioError as exc:
            return self._error(exc)

        snap = self._store.snapshot()
        warnings: list[dict[str, Any]] = list(snap.warnings)
        cash = float(snap.cash or 0.0)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if not snap.positions:
            warnings.append({"code": "empty_portfolio", "message": "持仓簿为空，未请求 K 线"})
            data = self._risk_empty_data(
                benchmark, window, cash, fetched_at, empty_book=True
            )
            data["hint"] = RISK_EMPTY_HINT
            return envelope(status="empty", data=_round_floats(data), warnings=warnings, private=True)

        if self._kline is None:
            return envelope(
                status="error",
                error_code="benchmark_unavailable",
                error_message="未配置 K 线客户端，无法计算组合风险",
            )
        begin_call = getattr(self._kline, "begin_call", None)
        if callable(begin_call):
            begin_call()

        try:
            benchmark_series: KlineSeries = self._kline.fetch(
                self._benchmark_symbol(benchmark), bars=window + 5, kind="index"
            )
        except Exception as exc:  # noqa: BLE001 - any upstream failure is benchmark_unavailable
            upstream_code = getattr(exc, "code", "upstream_error")
            return envelope(
                status="error",
                error_code="benchmark_unavailable",
                error_message=f"基准 {benchmark} 的日 K 取不到（{upstream_code}）",
            )
        if len(benchmark_series) < 2 or benchmark_series.last_date is None:
            return envelope(
                status="error",
                error_code="benchmark_unavailable",
                error_message=f"基准 {benchmark} 的有效日 K 不足 2 根",
            )

        excluded: list[dict[str, Any]] = []
        active: list[tuple[dict[str, Any], KlineSeries]] = []
        for row in snap.positions:
            symbol = normalize_symbol(row["code"])
            try:
                series = self._kline.fetch(symbol.tencent, bars=window + 5, kind="stock")
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not fail the tool
                upstream_code = getattr(exc, "code", "upstream_error")
                excluded.append(
                    self._excluded_row(
                        row,
                        "kline_unavailable",
                        f"日 K 取不到（{upstream_code}），未参与风险计算",
                        None,
                        None,
                    )
                )
                continue
            if len(series) < MIN_BARS:
                latest = series.closes[-1] if series.points else None
                excluded.append(
                    self._excluded_row(
                        row,
                        "insufficient_bars",
                        f"有效日 K {len(series)} 根，少于 {MIN_BARS} 根，未参与风险计算",
                        len(series),
                        latest,
                    )
                )
                continue
            active.append((row, series))

        benchmark_first = benchmark_series.dates[0]
        overlapping: list[tuple[dict[str, Any], KlineSeries]] = []
        for row, series in active:
            if series.last_date is None or series.last_date < benchmark_first:
                excluded.append(
                    self._excluded_row(
                        row,
                        "no_bars_in_window",
                        "持仓 K 线早于基准窗口，未参与风险计算",
                        0,
                        series.closes[-1] if series.points else None,
                    )
                )
            else:
                overlapping.append((row, series))
        active = overlapping

        active_with_points: list[tuple[dict[str, Any], KlineSeries, list[tuple[str, float]]]] = []
        calendar: list[str] = []
        end_date: str | None = None
        while active:
            last_dates = [benchmark_series.last_date] + [series.last_date for _, series in active]
            candidate_end = min(day for day in last_dates if day is not None)
            benchmark_dates = [day for day in benchmark_series.dates if day <= candidate_end]
            if len(benchmark_dates) < 2:
                earliest = [
                    (row, series)
                    for row, series in active
                    if series.last_date == candidate_end
                ]
                if not earliest:
                    return envelope(
                        status="error",
                        error_code="benchmark_unavailable",
                        error_message=f"基准 {benchmark} 与持仓没有足够的共同交易日",
                    )
                for row, series in earliest:
                    excluded.append(
                        self._excluded_row(
                            row,
                            "no_bars_in_window",
                            "持仓 K 线早于基准的第二个交易日，未参与风险计算",
                            0,
                            series.closes[-1] if series.points else None,
                        )
                    )
                active = [item for item in active if item not in earliest]
                continue
            candidate_calendar = benchmark_dates[-window:]
            calendar_set = set(candidate_calendar)
            kept: list[tuple[dict[str, Any], KlineSeries, list[tuple[str, float]]]] = []
            dropped = False
            for row, series in active:
                points = [
                    (day, close)
                    for day, close in series.points
                    if day in calendar_set
                ]
                if len(points) < 2:
                    excluded.append(
                        self._excluded_row(
                            row,
                            "no_bars_in_window",
                            "窗口内有效日 K 少于 2 根，未参与风险计算",
                            len(points),
                            series.close_on_or_before(candidate_end),
                        )
                    )
                    dropped = True
                else:
                    kept.append((row, series, points))
            if not dropped:
                active_with_points = kept
                calendar = candidate_calendar
                end_date = candidate_end
                break
            active = [(row, series) for row, series, _ in kept]

        if not active_with_points or end_date is None:
            warnings.append(
                {"code": "excluded_positions", "message": "没有可用于风险计算的持仓"}
            )
            data = self._risk_empty_data(
                benchmark, window, cash, fetched_at, empty_book=False
            )
            data["excluded"] = excluded
            data["hint"] = "所有持仓都因 K 线不足或取不到而未参与风险计算，未给出估计值。"
            return envelope(status="empty", data=_round_floats(data), warnings=warnings, private=True)

        benchmark_closes = dict(benchmark_series.points)
        benchmark_returns: list[float | None] = []
        previous: float | None = None
        for day in calendar:
            close = benchmark_closes[day]
            benchmark_returns.append(None if previous is None else close / previous - 1.0)
            previous = close

        replayed = {
            row["code"]: replay_returns(calendar, dict(series.points))
            for row, series, _ in active_with_points
        }
        active_codes = [row["code"] for row, _, _ in active_with_points]

        latest_closes: dict[str, float] = {}
        market_values: dict[str, float] = {}
        for row, series, _ in active_with_points:
            close = series.close_on_or_before(end_date)
            if close is None:
                continue
            latest_closes[row["code"]] = close
            market_values[row["code"]] = close * row["qty"]
        total_market_value = sum(market_values.values())
        if total_market_value <= 0:
            warnings.append(
                {"code": "excluded_positions", "message": "持仓市值合计为 0，无法计算风险"}
            )
            data = self._risk_empty_data(
                benchmark, window, cash, fetched_at, empty_book=False
            )
            data["excluded"] = excluded
            data["hint"] = "持仓市值合计为 0，未给出风险数字。"
            return envelope(status="empty", data=_round_floats(data), warnings=warnings, private=True)
        weights = {
            code: value / total_market_value for code, value in market_values.items()
        }

        indices = [
            index
            for index in range(1, len(calendar))
            if all(replayed[code][index] is not None for code in active_codes)
        ]
        if not indices:
            warnings.append(
                {"code": "excluded_positions", "message": "持仓与基准没有重叠的收益区间"}
            )
            data = self._risk_empty_data(
                benchmark, window, cash, fetched_at, empty_book=False
            )
            data["excluded"] = excluded
            data["hint"] = "持仓与基准没有重叠的收益区间，未给出风险数字。"
            return envelope(status="empty", data=_round_floats(data), warnings=warnings, private=True)

        portfolio_returns = [
            sum(weights[code] * float(replayed[code][index]) for code in active_codes)
            for index in indices
        ]
        benchmark_window_returns = [
            float(benchmark_returns[index]) for index in indices
        ]

        portfolio_vol = annualized_volatility(portfolio_returns)
        portfolio_beta = beta(portfolio_returns, benchmark_window_returns)
        portfolio_drawdown = max_drawdown(portfolio_returns)
        benchmark_vol = annualized_volatility(benchmark_window_returns)
        benchmark_drawdown = max_drawdown(benchmark_window_returns)

        position_items: list[dict[str, Any]] = []
        replayed_by_code: dict[str, list[float | None]] = {
            code: [replayed[code][index] for index in indices] for code in active_codes
        }
        for row, series, points in active_with_points:
            code = row["code"]
            position_returns = [
                float(value) for value in replayed_by_code[code] if value is not None
            ]
            corr = correlation(position_returns, portfolio_returns)
            position_items.append(
                {
                    "code": code,
                    "name": row["name"],
                    "qty_shares": row["qty"],
                    "industry": row.get("industry"),
                    "latest_close_cny": latest_closes[code],
                    "market_value_cny": market_values[code],
                    "weight_ratio": weights[code],
                    "weight": weights[code],
                    "bars": len(points),
                    "annualized_vol_ratio": annualized_volatility(position_returns),
                    "max_drawdown_ratio": max_drawdown(position_returns),
                    "beta": beta(position_returns, benchmark_window_returns),
                    "corr_to_portfolio": corr,
                    "corr_to_portfolio_ratio": corr,
                    "board": board_of(code),
                    "asset_class": asset_class_of(code),
                    "broad_index_etf": is_broad_index_etf(code, row["name"]),
                }
            )

        sorted_weights = sorted(weights.values(), reverse=True)
        hhi = sum(weight * weight for weight in sorted_weights)
        broad = sorted(
            [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "weight_ratio": item["weight_ratio"],
                }
                for item in position_items
                if item["broad_index_etf"]
            ],
            key=lambda item: item["weight_ratio"],
            reverse=True,
        )

        pair_correlations: list[dict[str, Any]] = []
        for left in range(len(position_items)):
            for right in range(left + 1, len(position_items)):
                code_a = position_items[left]["code"]
                code_b = position_items[right]["code"]
                corr = correlation(replayed_by_code[code_a], replayed_by_code[code_b])
                if corr is None:
                    continue
                pair_correlations.append(
                    {
                        "code_a": code_a,
                        "code_b": code_b,
                        "corr_ratio": corr,
                        "correlation_ratio": corr,
                        "correlation": corr,
                        "corr": corr,
                    }
                )
        pair_correlations.sort(key=lambda item: item["corr_ratio"], reverse=True)

        exposure_by_board = sum_by(position_items, "board")
        exposure_by_industry = sum_by(position_items, "industry")
        exposure_by_asset_class = sum_by(position_items, "asset_class")

        if excluded:
            warnings.append(
                {
                    "code": "excluded_positions",
                    "message": "未参与风险计算："
                    + ", ".join(f"{item['code']}({item['reason']})" for item in excluded),
                }
            )

        total_assets = total_market_value + cash
        data = {
            "benchmark": benchmark,
            "benchmark_code": benchmark,
            "window_days_requested": window,
            "window_days": window,
            "observations": len(indices),
            "annualized_vol_ratio": portfolio_vol,
            "beta": portfolio_beta,
            "max_drawdown_ratio": portfolio_drawdown,
            "benchmark_annualized_vol_ratio": benchmark_vol,
            "benchmark_max_drawdown_ratio": benchmark_drawdown,
            "as_of_bar_date": end_date,
            "positions": position_items,
            "excluded": excluded,
            "top1_weight_ratio": sorted_weights[0] if sorted_weights else 0.0,
            "top5_weight_ratio": sum(sorted_weights[:5]),
            "hhi": hhi,
            "effective_n": (1.0 / hhi) if hhi > 0 else 0.0,
            "broad_index_etfs": broad,
            "broad_index_etf_codes": [item["code"] for item in broad],
            "broad_index_etf_weight_ratio": sum(item["weight_ratio"] for item in broad),
            "largest_pair_correlations": pair_correlations[:3],
            "exposure_by_board": exposure_by_board,
            "exposure_by_industry": exposure_by_industry,
            "asset_class": exposure_by_asset_class,
            "cash_share_ratio": (cash / total_assets) if total_assets > 0 else 0.0,
            "fetched_at": fetched_at,
            "methodology": RISK_METHODOLOGY,
            "private": True,
            "untrusted_text": False,
        }
        return envelope(status="ready", data=_round_floats(data), warnings=warnings, private=True)
