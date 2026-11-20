"""Gateway-backed adapters used by the rule layer.

Every score, pool and board row comes from ``POST /v1/call`` on the local data
gateway.  No vendor host is contacted from this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from ..gateway import GatewayClient, SourceError
from ..models import (
    CN_TZ,
    BoardQuote,
    Breadth,
    FlowRow,
    IndexQuote,
    LimitPool,
    MoverRow,
    StockQuote,
    fmt_iso,
    parse_iso,
)

INDEX_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000852.SH",
    "000688.SH",
)
INDEX_NAMES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300",
    "000852.SH": "中证1000",
    "000688.SH": "科创50",
}
MAX_QUOTE_CODES = 20
POOL_LIMIT = 200


def _stamp(value: Any, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return parse_iso(value)
    except ValueError:
        return fallback


def _exchange_code(code: Any) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        return text
    if not text:
        return ""
    if text.startswith(("6", "9")):
        return f"{text}.SH"
    if text.startswith(("4", "8", "92")):
        return f"{text}.BJ"
    return f"{text}.SZ"


@dataclass(frozen=True)
class BoardRow:
    code: str
    name: str
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    up: Optional[int]
    down: Optional[int]
    flat: Optional[int]
    leader_code: Optional[str] = None
    leader_name: Optional[str] = None
    leader_change_pct: Optional[float] = None
    price: Optional[float] = None
    prev_close: Optional[float] = None
    provider_time: Optional[datetime] = None
    member_total: Optional[int] = None


@dataclass(frozen=True)
class MemberRow:
    code: str
    name: str
    price: Optional[float]
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    turnover_pct: Optional[float] = None


@dataclass(frozen=True)
class HistoryBar:
    day: date
    close: float


@dataclass(frozen=True)
class TrendPoint:
    t: datetime
    price: float
    change_pct: Optional[float]


@dataclass(frozen=True)
class PoolStock:
    code: str
    name: str
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    streak: Optional[int]
    broken_times: Optional[int]
    first_seal_time: Optional[int]
    industry: str
    market: Optional[int] = None
    price: Optional[float] = None
    turnover_pct: Optional[float] = None
    seal_amount_yuan: Optional[float] = None
    board_days: Optional[int] = None
    board_count: Optional[int] = None


def format_seal_time(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    text = f"{number:06d}"
    hour, minute, second = int(text[:2]), int(text[2:4]), int(text[4:6])
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _seal_int(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
    except ValueError:
        return None


def pool_rows(stocks: Iterable[PoolStock]) -> list[dict[str, object]]:
    return [
        {
            "code": _exchange_code(item.code),
            "name": item.name,
            "price": item.price,
            "change_pct": item.change_pct,
            "amount_yuan": item.amount_yuan,
            "turnover_pct": item.turnover_pct,
            "streak": item.streak,
            "first_seal_time": format_seal_time(item.first_seal_time),
            "broken_times": item.broken_times,
            "industry": item.industry or None,
            "seal_amount_yuan": item.seal_amount_yuan,
        }
        for item in stocks
    ]


def _row_to_pool_stock(row: Mapping[str, Any]) -> PoolStock:
    return PoolStock(
        code=str(row.get("code") or ""),
        name=str(row.get("name") or ""),
        change_pct=row.get("change_pct"),
        amount_yuan=row.get("amount_yuan"),
        streak=row.get("streak"),
        broken_times=row.get("broken_times"),
        first_seal_time=_seal_int(row.get("first_seal_time")),
        industry=str(row.get("industry") or ""),
        price=row.get("price"),
        turnover_pct=row.get("turnover_pct"),
        seal_amount_yuan=row.get("seal_amount_yuan"),
    )


class QuoteSource:
    """Index/watchlist snapshots (``market_quote``)."""

    name = "gateway.market_quote"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def _quotes(self, codes: list[str], now: datetime) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for start in range(0, len(codes), MAX_QUOTE_CODES):
            chunk = codes[start : start + MAX_QUOTE_CODES]
            data = self.client.data("market_quote", {"codes": chunk})
            for item in data.get("quotes") or []:
                if isinstance(item, dict) and item.get("code"):
                    found[str(item["code"])] = item
        return found

    def _as_index(self, row: Mapping[str, Any], now: datetime) -> IndexQuote:
        code = str(row.get("code"))
        return IndexQuote(
            code=code,
            name=str(row.get("name") or INDEX_NAMES.get(code, code)),
            price=float(row.get("price") or 0.0),
            prev_close=float(row.get("prev_close") or 0.0),
            open=float(row.get("open") or 0.0),
            high=float(row.get("high") or 0.0),
            low=float(row.get("low") or 0.0),
            change_pct=float(row.get("change_pct") or 0.0),
            amount_yuan=row.get("amount_yuan"),
            volume_lots=int((row.get("volume_shares") or 0) / 100),
            exch_time=_stamp(row.get("quote_time"), now),
            limit_up=row.get("limit_up"),
            limit_down=row.get("limit_down"),
        )

    def _as_stock(self, row: Mapping[str, Any], now: datetime) -> StockQuote:
        return StockQuote(
            code=str(row.get("code")),
            name=str(row.get("name") or ""),
            price=float(row.get("price") or 0.0),
            prev_close=float(row.get("prev_close") or 0.0),
            change_pct=float(row.get("change_pct") or 0.0),
            amount_yuan=row.get("amount_yuan"),
            volume_lots=int((row.get("volume_shares") or 0) / 100),
            exch_time=_stamp(row.get("quote_time"), now),
            limit_up=row.get("limit_up"),
            limit_down=row.get("limit_down"),
        )

    def fetch_market(
        self, now: datetime, extra_codes: list[str]
    ) -> tuple[dict[str, IndexQuote], dict[str, StockQuote]]:
        extra = [code for code in extra_codes if code not in INDEX_CODES]
        codes = list(INDEX_CODES) + list(dict.fromkeys(extra))
        rows = self._quotes(codes, now)
        indexes = {
            code: self._as_index(rows[code], now) for code in INDEX_CODES if code in rows
        }
        stocks = {
            code: self._as_stock(rows[code], now) for code in extra if code in rows
        }
        if not indexes:
            raise SourceError("parse_empty", "行情网关没有返回任何指数")
        return indexes, stocks

    def fetch_indexes(self, now: datetime) -> dict[str, IndexQuote]:
        indexes, _ = self.fetch_market(now, [])
        return indexes

    def fetch_stocks(self, codes: list[str], now: datetime) -> dict[str, StockQuote]:
        if not codes:
            return {}
        rows = self._quotes(list(dict.fromkeys(codes)), now)
        return {code: self._as_stock(rows[code], now) for code in codes if code in rows}

    def fetch_stock_rows(self, codes: list[str], now: datetime) -> dict[str, Any]:
        if not codes:
            return {}
        rows = self._quotes(list(dict.fromkeys(codes)), now)
        return {code: SimpleNamespace(**row) for code, row in rows.items()}


class BreadthSource:
    """Advance/decline counts from ``market_overview``."""

    name = "gateway.market_overview"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def fetch(self, now: datetime) -> Breadth:
        data = self.client.data("market_overview", {})
        breadth = data.get("breadth") if isinstance(data.get("breadth"), dict) else {}
        up = breadth.get("up_count")
        down = breadth.get("down_count")
        flat = breadth.get("flat_count")
        if up is None or down is None or flat is None:
            raise SourceError("parse_missing", "行情网关宽度缺少涨/跌/平家数")
        up, down, flat = int(up), int(down), int(flat)
        ratio = up / (up + down) if (up + down) > 0 else None
        return Breadth(
            up=up,
            down=down,
            flat=flat,
            up_ratio=ratio,
            amount_yuan=data.get("amount_yuan"),
            as_of=_stamp(data.get("as_of"), now),
            fetched_at=now,
            source=self.name,
        )


class LimitPoolSource:
    """Limit-up / broken / limit-down pools from ``market_limit_pool``."""

    name = "gateway.market_limit_pool"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def _fetch(self, kind: str, day: date | None, now: datetime) -> tuple[int, list[dict[str, Any]]]:
        args: dict[str, Any] = {"kind": kind, "limit": POOL_LIMIT}
        if day is not None:
            args["date"] = day.isoformat()
        payload = self.client.call("market_limit_pool", args)
        data = payload.get("data") or {}
        rows = [row for row in data.get("rows") or [] if isinstance(row, dict)]
        count = data.get("count")
        if count is None:
            count = len(rows)
        return int(count), rows

    def fetch_pool(
        self, kind: str, date_text: str, now: datetime, *, cache_ttl: float = 20.0
    ) -> tuple[int, str, list[PoolStock]]:
        if kind not in {"zt", "zb", "dt"}:
            raise SourceError("bad_kind", f"未知池类型: {kind}")
        try:
            day = datetime.strptime(date_text, "%Y%m%d").date()
        except ValueError as exc:
            raise SourceError("bad_date", f"无效日期: {date_text}") from exc
        count, rows = self._fetch(kind, day, now)
        return count, date_text, [_row_to_pool_stock(row) for row in rows]

    def fetch(self, now: datetime) -> LimitPool:
        reasons: list[str] = []
        limit_up = limit_down = broken = None
        seal = None
        max_streak: Optional[int] = None
        try:
            overview = self.client.data("market_overview", {})
            limits = overview.get("limit") if isinstance(overview.get("limit"), dict) else {}
            limit_up = limits.get("limit_up_count")
            limit_down = limits.get("limit_down_count")
            broken = limits.get("broken_count")
            max_streak = limits.get("max_streak")
            if limits.get("seal_ratio_pct") is not None:
                seal = float(limits["seal_ratio_pct"]) / 100.0
        except SourceError as exc:
            reasons.append(f"overview:{exc.code}")
        details: dict[str, list[dict[str, Any]]] = {}
        for kind in ("zt", "zb"):
            try:
                count, rows = self._fetch(kind, now.date(), now)
                details[kind] = rows
                if kind == "zt" and limit_up is None:
                    limit_up = count
                if kind == "zb" and broken is None:
                    broken = count
            except SourceError as exc:
                reasons.append(f"{kind}:{exc.code}")
        if limit_down is None:
            try:
                count, rows = self._fetch("dt", now.date(), now)
                limit_down = count
                details["dt"] = rows
            except SourceError as exc:
                reasons.append(f"dt:{exc.code}")
        if limit_up is None and broken is None and limit_down is None:
            raise SourceError("upstream_unavailable", "涨停/炸板/跌停池全部失败")
        zt_rows = details.get("zt") or []
        if max_streak is None:
            streaks = [row.get("streak") for row in zt_rows if row.get("streak") is not None]
            max_streak = max(streaks) if streaks else (None if not zt_rows else 0)
        if seal is None and limit_up is not None and broken is not None and (limit_up + broken) > 0:
            seal = limit_up / (limit_up + broken)
        return LimitPool(
            as_of=now,
            limit_up=limit_up,
            limit_down=limit_down,
            broken=broken,
            seal_ratio=seal,
            max_streak=max_streak,
            zt_codes=tuple(str(row.get("code")) for row in zt_rows if row.get("code")),
            zb_codes=tuple(
                str(row.get("code")) for row in (details.get("zb") or []) if row.get("code")
            ),
            dt_codes=tuple(
                str(row.get("code")) for row in (details.get("dt") or []) if row.get("code")
            ),
            stale=bool(reasons),
            reason="; ".join(reasons) if reasons else None,
            details=details,
        )


class BoardSource:
    """Industry/concept rankings from ``market_sectors`` (gateway taxonomy)."""

    name = "gateway.market_sectors"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    @staticmethod
    def _row(row: Mapping[str, Any], kind: str) -> BoardRow:
        leader = row.get("leader") if isinstance(row.get("leader"), dict) else {}
        code = row.get("code")
        name = str(row.get("name") or "")
        return BoardRow(
            code=str(code) if code else name,
            name=name,
            change_pct=row.get("change_pct"),
            amount_yuan=row.get("amount_yuan"),
            up=row.get("up_count"),
            down=row.get("down_count"),
            flat=None,
            leader_code=leader.get("code"),
            leader_name=leader.get("name"),
            leader_change_pct=leader.get("change_pct"),
            member_total=row.get("member_count"),
        )

    def fetch(self, now: datetime) -> list[BoardRow]:
        return self.fetch_all(now, limit=100)

    def fetch_all(self, now: datetime, *, limit: int = 100, max_pages: int = 8) -> list[BoardRow]:
        data = self.client.data("market_sectors", {"kind": "industry", "limit": limit})
        rows = [self._row(row, "industry") for row in data.get("rows") or [] if isinstance(row, dict)]
        if not rows:
            raise SourceError("parse_empty", "行业排行返回为空")
        return rows

    def fetch_concepts(
        self, now: datetime, *, sort: str = "change", page_size: int = 100, max_pages: int = 2
    ) -> list[BoardRow]:
        data = self.client.data(
            "market_sectors", {"kind": "concept", "sort": sort, "limit": page_size}
        )
        rows = [self._row(row, "concept") for row in data.get("rows") or [] if isinstance(row, dict)]
        if not rows:
            raise SourceError("parse_empty", "概念板块返回为空")
        return rows

    def fetch_members(
        self, code: str, now: datetime, *, pace: Optional[Callable[[], None]] = None
    ) -> tuple[list[MemberRow], Optional[int], Optional[datetime]]:
        if not code.startswith(("new_", "gn_")):
            raise SourceError("no_member_source", "该行业口径没有板块代码与成分")
        if pace is not None:
            pace()
        data = self.client.data("market_sectors", {"kind": "industry", "code": code, "limit": 100})
        rows: list[MemberRow] = []
        for item in data.get("members") or []:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            rows.append(
                MemberRow(
                    code=str(item["code"]),
                    name=str(item.get("name") or ""),
                    price=item.get("price"),
                    change_pct=item.get("change_pct"),
                    amount_yuan=item.get("amount_yuan"),
                    turnover_pct=item.get("turnover_pct"),
                )
            )
        if not rows:
            raise SourceError("parse_empty", f"板块 {code} 成分返回为空")
        return rows, data.get("member_count"), now

    def fetch_history(self, code: str, now: datetime) -> list[HistoryBar]:
        raise SourceError("no_history_source", "该行业口径没有板块日线")

    def fetch_index_history(
        self, code: str, now: datetime, *, days: int = 60
    ) -> list[HistoryBar]:
        data = self.client.data(
            "market_bars",
            {
                "code": code,
                "interval": "1d",
                "start": (now.date() - timedelta(days=max(120, days * 3))).isoformat(),
                "end": now.date().isoformat(),
                "limit": days,
            },
        )
        bars: list[HistoryBar] = []
        for item in data.get("bars") or []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("time") or "")[:10]
            try:
                day = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            if item.get("close") is None:
                continue
            bars.append(HistoryBar(day=day, close=float(item["close"])))
        if not bars:
            raise SourceError("parse_empty", f"指数 {code} 日线为空")
        return bars

    def fetch_trend(self, code: str, now: datetime) -> tuple[list[TrendPoint], Optional[float]]:
        raise SourceError("no_trend_source", "该行业口径没有板块分时")


class MoversSource:
    """Gainers / losers / turnover from ``market_movers``."""

    name = "gateway.market_movers"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def fetch(
        self,
        kind: str,
        now: datetime,
        *,
        include_bj: bool = False,
        page_size: int = 100,
        cache_ttl: float = 15.0,
    ) -> list[MoverRow]:
        data = self.client.data(
            "market_movers", {"kind": kind, "limit": 20, "include_bj": include_bj}
        )
        return [
            MoverRow(
                code=str(row.get("code")),
                name=str(row.get("name") or ""),
                price=row.get("price"),
                change_pct=row.get("change_pct"),
                amount_yuan=row.get("amount_yuan"),
                turnover_pct=row.get("turnover_pct"),
                industry=row.get("industry"),
            )
            for row in data.get("rows") or []
            if isinstance(row, dict) and row.get("code")
        ]


class FlowSource:
    """Fund-flow rankings from ``market_fund_flow``."""

    name = "gateway.market_fund_flow"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    @staticmethod
    def _rows(data: Mapping[str, Any]) -> list[FlowRow]:
        return [
            FlowRow(
                code=str(row.get("code")),
                name=str(row.get("name") or ""),
                main_net_yuan=row.get("main_net_yuan"),
                main_net_pct=row.get("main_net_pct"),
                change_pct=row.get("change_pct"),
                amount_yuan=row.get("amount_yuan"),
            )
            for row in data.get("rows") or []
            if isinstance(row, dict) and row.get("code")
        ]

    def fetch_sector_flows(
        self,
        now: datetime,
        *,
        universe: Iterable[str] = (),
        page_size: int = 100,
        max_pages: int = 8,
        cache_ttl: float = 20.0,
    ) -> list[FlowRow]:
        data = self.client.data(
            "market_fund_flow", {"scope": "sector", "kind": "in", "limit": 20}
        )
        return self._rows(data)

    def fetch_stock_flows(
        self,
        kind: str,
        now: datetime,
        *,
        include_bj: bool = False,
        page_size: int = 100,
        cache_ttl: float = 20.0,
    ) -> list[FlowRow]:
        direction = "out" if kind.endswith("_out") else "in"
        data = self.client.data(
            "market_fund_flow",
            {"scope": "rank", "kind": direction, "limit": 20, "include_bj": include_bj},
        )
        return self._rows(data)


class NorthboundSource:
    """Northbound intraday flow: the exchanges no longer publish it."""

    name = "gateway.market_northbound"

    def __init__(self, client: GatewayClient) -> None:
        self.client = client

    def fetch(self, now: datetime) -> dict[str, Any]:
        return {
            "available": False,
            "reason": "交易所自 2024-08-19 起不再实时披露北向净买入，网关也不输出净流入",
        }
