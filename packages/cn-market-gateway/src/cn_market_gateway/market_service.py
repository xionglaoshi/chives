"""Market-level capabilities: overview, movers, limit pool, sectors, flows,
trading activity and northbound (T141)."""

from __future__ import annotations

import copy
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import config
from .codes import Code, InvalidCode, normalize_code
from .envelope import basis, envelope, missing, now_iso
from .market_sources import (
    MarketSources,
    holdings_change,
    normalize_block_row,
    normalize_dragon_row,
    normalize_margin_row,
    normalize_seat,
    previous_quarter_end,
    quarter_end,
)

INDEX_CODES = [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "000688.SH",
    "000016.SH",
]
POOL_KINDS = ("zt", "zb", "dt", "ladder", "stats")
SECTOR_KINDS = ("industry", "concept")
FLOW_SCOPES = ("stock", "sector", "rank")
ACTIVITY_KINDS = ("dragon_tiger", "block_trades", "margin")
NORTHBOUND_KINDS = ("daily", "top_active", "holdings")
NORTHBOUND_NOTE = "自 2024-08-19 起没有每日净买入数据；成交额为买卖合计，本结果不含净流入"
HOLDINGS_NOTE = "北向持股按季度披露（季末后约第 5 个北向交易日公布），没有每日持股；变化方向是外资季度增减持，不是每日资金流"
HOLDINGS_DEFAULT_LIMIT = 50
NORTHBOUND_MAX_DAYS = 20
HOLDINGS_MAX_LIMIT = 200
HOLDINGS_SORTS = ("change_shares", "shareholding_pct", "change_pct_points")
FLOW_NOTE = (
    "主力净流入按另一套主力定义统计（与默认的大单+超大单口径不同，阈值未公开），"
    "数值不能与默认口径直接比较"
)
SINA_TAXONOMY_NOTE = "使用另一套行业/概念分类（与默认的一级行业不同），板块代码与默认分类不通用"


class MarketError(Exception):
    """A user-facing market-data failure."""


def _int_arg(args: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
    value = args.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MarketError(f"{name} 必须是 {low} 到 {high} 的整数")
    return value


def _bool_arg(args: dict[str, Any], name: str, default: bool) -> bool:
    value = args.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise MarketError(f"{name} 必须是 true 或 false")
    return value


def _str_arg(args: dict[str, Any], name: str, choices: tuple[str, ...], default: str | None) -> str | None:
    value = args.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or value not in choices:
        raise MarketError(f"{name} 只能是 {'/'.join(choices)}")
    return value


def _date_arg(args: dict[str, Any], name: str) -> date | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MarketError(f"{name} 必须是 YYYY-MM-DD 格式的日期")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise MarketError(f"{name} 必须是 YYYY-MM-DD 格式的日期") from None


def _last_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _clean(value: Any, keep: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in keep if key in value}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


class MarketTools:
    def __init__(self, service: Any, sources: MarketSources) -> None:
        self._holdings_lock = threading.Lock()
        self._hkex_days_lock = threading.Lock()
        self._hkex_days: dict[date, dict[str, Any]] = {}
        self._holdings_pages: dict[str, tuple[float, dict[str, Any]]] = {}
        self.service = service
        self.sources = sources
        self.company: Any = None

    # ------------------------------------------------------------------ shared
    def _event(self, tool: str, source: str, *, ok: bool, switched: bool = False, error: str | None = None) -> None:
        self.service._event(tool, source, ok=ok, switched=switched, error=error)  # noqa: SLF001

    def _cached(self, key: str, ttl: float, fallback: float, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        return self.service._cached(key, ttl, fallback, compute)  # noqa: SLF001

    # ------------------------------------------------------------------ overview
    def market_overview(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._cached(
            "market_overview", config.OVERVIEW_TTL, config.OVERVIEW_FALLBACK, self._overview_compute
        )

    def _overview_compute(self) -> dict[str, Any]:
        return self._overview_direct()

    def _overview_direct(self) -> dict[str, Any]:
        missing_items: list[dict[str, Any]] = []
        bias: list[dict[str, Any]] = []
        quotes = self.service.call("market_quote", {"codes": INDEX_CODES})
        indexes = []
        stamps = []
        if quotes.get("status") in {"ok", "partial"}:
            for item in (quotes.get("data") or {}).get("quotes") or []:
                indexes.append(
                    _clean(
                        item,
                        ("code", "name", "price", "prev_close", "change_pct", "amount_yuan", "volume_ratio"),
                    )
                )
                if item.get("quote_time"):
                    stamps.append(str(item["quote_time"]))
        else:
            missing_items.append(missing("indexes", "指数行情暂时取不到"))
        breadth: dict[str, Any] = {}
        limits: dict[str, Any] = {
            "limit_up_count": None,
            "limit_down_count": None,
            "broken_count": None,
            "max_streak": None,
            "seal_ratio_pct": None,
        }
        amount = None
        try:
            activity = self.sources.legu_activity()
            self._event("market_overview", "legulegu.com", ok=True, switched=True)
            breadth = {
                "up_count": activity.up,
                "down_count": activity.down,
                "flat_count": activity.flat,
                "suspended_count": activity.suspended,
                "up_ratio_pct": round(activity.up / (activity.up + activity.down) * 100.0, 2)
                if activity.up + activity.down > 0
                else None,
            }
            limits["limit_up_count"] = activity.limit_up
            limits["limit_down_count"] = activity.limit_down
            if activity.as_of is not None:
                stamps.append(activity.as_of.isoformat(timespec="seconds"))
            bias.append(basis("up_count", "统计范围为沪深两市（不含北交所），涨停/跌停家数含 ST"))
            for field_name in ("suspended_count", "limit_up_count", "limit_down_count"):
                if breadth.get(field_name) is None and limits.get(field_name) is None:
                    missing_items.append(missing(field_name, "该来源不提供此字段"))
            for field_name in ("broken_count", "max_streak", "seal_ratio_pct"):
                missing_items.append(missing(field_name, "此时不提供炸板与连板统计"))
        except Exception as exc:
            self._event("market_overview", "legulegu.com", ok=False, switched=True, error=type(exc).__name__)
            missing_items.append(missing("up_count", "涨跌家数暂时取不到"))
        by_code = {item.get("code"): item for item in indexes}
        if by_code.get("000001.SH") and by_code.get("399001.SZ"):
            amount = sum(
                float(by_code[code].get("amount_yuan") or 0.0) for code in ("000001.SH", "399001.SZ")
            )
        if not indexes and not breadth:
            raise MarketError("大盘数据暂时不可用，稍后再试")
        if amount is None:
            missing_items.append(missing("amount_yuan", "全市场成交额暂时取不到"))
        else:
            bias.append(basis("amount_yuan", "全市场成交额=上证指数成交额+深证成指成交额"))
        missing_items.append(missing("headlines", "此时不提供市场摘要"))
        data = {"indexes": indexes, "breadth": breadth, "limit": limits, "amount_yuan": amount, "headlines": []}
        return envelope(
            "partial" if missing_items else "ok",
            data=data,
            as_of=max(stamps) if stamps else now_iso(self.service.now()),
            basis_items=bias,
            missing_items=missing_items,
        )

    # ------------------------------------------------------------------ movers
    def market_movers(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _str_arg(args, "kind", ("gainers", "losers", "active"), "gainers")
        assert kind is not None
        limit = _int_arg(args, "limit", 1, config.MAX_MOVER_LIMIT, 10)
        include_bj = _bool_arg(args, "include_bj", False)
        key = f"market_movers|{kind}|{limit}|{include_bj}"
        return self._cached(
            key, config.MOVERS_TTL, config.MOVERS_FALLBACK, lambda: self._movers_compute(kind, limit, include_bj)
        )

    def _movers_compute(self, kind: str, limit: int, include_bj: bool) -> dict[str, Any]:
        try:
            rows = self.sources.sina_movers(kind, include_bj=include_bj, limit=limit)
            self._event("market_movers", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("market_movers", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("榜单数据暂时不可用，稍后再试") from None
        today = self.service.now().date().isoformat()
        stamps = []
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
            ticktime = row.pop("ticktime", None)
            if ticktime:
                stamps.append(f"{today}T{ticktime}+08:00")
        return envelope(
            "ok" if len(rows) >= limit else "partial",
            data={"kind": kind, "include_bj": include_bj, "rows": rows},
            as_of=max(stamps) if stamps else now_iso(self.service.now()),
            missing_items=[] if len(rows) >= limit else [missing("rows", "榜单行数少于请求数量")],
        )

    # ------------------------------------------------------------------ limit pool
    def market_limit_pool(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _str_arg(args, "kind", POOL_KINDS, "zt")
        assert kind is not None
        limit = _int_arg(args, "limit", 1, config.MAX_POOL_LIMIT, config.DEFAULT_POOL_LIMIT)
        days = _int_arg(args, "days", 10, 30, 10)
        day = _date_arg(args, "date")
        key = f"market_limit_pool|{kind}|{day}|{limit}|{days}"
        return self._cached(
            key, config.POOL_TTL, config.POOL_FALLBACK, lambda: self._pool_compute(kind, day, limit, days)
        )

    def _pool_compute(self, kind: str, day: date | None, limit: int, days: int) -> dict[str, Any]:
        return self._pool_direct(kind, day, limit, days)

    def _pool_direct(self, kind: str, day: date | None, limit: int, days: int) -> dict[str, Any]:
        target = day or _last_weekday(self.service.now().date())
        if kind == "dt":
            raise MarketError("跌停池暂时取不到，请稍后再试")
        if kind in {"zt", "zb"}:
            try:
                total, rows = self.sources.ths_pool(kind, day=target, limit=limit)
                self._event("market_limit_pool", "data.10jqka.com.cn", ok=True)
            except Exception as exc:
                self._event("market_limit_pool", "data.10jqka.com.cn", ok=False, error=type(exc).__name__)
                raise MarketError("涨停池数据暂时不可用，稍后再试") from None
            missing_items = []
            if any(row.get("industry") is None for row in rows):
                missing_items.append(missing("industry", "该来源不提供行业字段"))
            if any(row.get("amount_yuan") is None for row in rows):
                missing_items.append(missing("amount_yuan", "该来源不提供成交额"))
            if total > len(rows):
                missing_items.append(missing("rows", "超过本次查询范围，或来源只返回了部分股票"))
            return envelope(
                "partial" if missing_items else "ok",
                data={"date": target.isoformat(), "kind": kind, "count": total, "rows": rows},
                as_of=now_iso(self.service.now()),
                basis_items=[basis("count", "涨停池按另一口径统计，ST/新股的过滤可能与默认口径不同")],
                missing_items=missing_items,
            )
        if kind == "ladder":
            try:
                raw = self.sources.ths_ladder(day=target)
                self._event("market_limit_pool", "data.10jqka.com.cn", ok=True)
            except Exception as exc:
                self._event("market_limit_pool", "data.10jqka.com.cn", ok=False, error=type(exc).__name__)
                raise MarketError("连板梯队数据暂时不可用，稍后再试") from None
            missing_items = [missing("rows", "此时只有连板家数与代码、名称，不含行情字段")]
            return envelope(
                "partial",
                data={"date": target.isoformat(), "max_streak": raw["max_streak"], "tiers": raw["tiers"]},
                as_of=now_iso(self.service.now()),
                missing_items=missing_items,
            )
        return self._pool_stats_direct(target, days)

    def _pool_stats_direct(self, target: date, days: int) -> dict[str, Any]:
        previous = _last_weekday(target - timedelta(days=1))
        try:
            today_total, today_rows = self.sources.ths_pool("zt", day=target, limit=200)
            broken_total, _ = self.sources.ths_pool("zb", day=target, limit=200)
        except Exception as exc:
            self._event("market_limit_pool", "data.10jqka.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("封板率与晋级率数据暂时不可用，稍后再试") from None
        previous_total = 0
        previous_rows: list[dict[str, Any]] = []
        previous_failed = False
        try:
            previous_total, previous_rows = self.sources.ths_pool("zt", day=previous, limit=200)
        except Exception:
            previous_failed = True
        denominator = today_total + broken_total
        seal_ratio = round(today_total / denominator * 100.0, 2) if denominator else None
        today_map = {row["code"]: (row.get("streak") or 0) for row in today_rows}
        previous_map = {row["code"]: (row.get("streak") or 0) for row in previous_rows}
        today_streaks = list(today_map.values())
        previous_streaks = list(previous_map.values())
        max_streak = max(today_streaks) if today_streaks else None

        def promote(old: int, new: int) -> float | None:
            base = [code for code, streak in previous_map.items() if streak == old]
            if not base:
                return None
            return round(sum(1 for code in base if today_map.get(code) == new) / len(base) * 100.0, 2)

        previous_three = [code for code, streak in previous_map.items() if streak >= 3]
        promoted_three = sum(
            1 for code in previous_three if today_map.get(code, 0) >= previous_map[code] + 1
        )
        entry = {
            "date": target.isoformat(),
            "zt": today_total,
            "dt": None,
            "zb": broken_total,
            "seal_ratio_pct": seal_ratio,
            "max_streak": max_streak,
            "promote_1to2_pct": promote(1, 2),
            "promote_2to3_pct": promote(2, 3),
            "promote_3up_pct": round(promoted_three / len(previous_three) * 100.0, 2) if previous_three else None,
            "available": True,
        }
        missing_items = [missing("days", "此时只计算当日封板率与晋级率")]
        if entry["dt"] is None:
            missing_items.append(missing("dt", "跌停家数暂时取不到"))
        if previous_failed:
            missing_items.append(missing("promote_1to2_pct", "上一交易日涨停池取不到，晋级率无法计算"))
        elif today_total > len(today_rows) or previous_total > len(previous_rows):
            missing_items.append(missing("promote_1to2_pct", "最多取到 200 行，晋级率按已取到的行计算"))
        return envelope(
            "partial",
            data={"days": [entry]},
            as_of=now_iso(self.service.now()),
            basis_items=[basis("zt", "涨停池按另一口径统计，ST/新股的过滤可能与默认口径不同")],
            missing_items=missing_items,
        )

    # ------------------------------------------------------------------ sectors
    def market_sectors(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _str_arg(args, "kind", SECTOR_KINDS, "industry")
        assert kind is not None
        sort = _str_arg(args, "sort", ("change", "amount"), "change")
        limit = _int_arg(args, "limit", 1, config.MAX_SECTOR_LIMIT, 20)
        code = args.get("code")
        if code is not None and not isinstance(code, str):
            raise MarketError("code 必须是板块代码，例如 BK0437 或 new_kfq")
        key = f"market_sectors|{kind}|{sort}|{limit}|{code}"
        return self._cached(
            key, config.SECTOR_TTL, config.SECTOR_FALLBACK, lambda: self._sectors_compute(kind, sort, limit, code)
        )

    def _sectors_compute(self, kind: str, sort: str, limit: int, code: str | None) -> dict[str, Any]:
        if code:
            if code.startswith(("new_", "gn_")):
                return self._sector_detail_sina(kind, code, limit)
            raise MarketError("code 需要是 market_sectors 排行里返回的板块代码（例如 new_jxhy、gn_hwhs）")
        if kind == "industry":
            return self._sectors_ths(sort, limit)
        return self._sectors_sina(kind, sort, limit)

    def _sectors_sina(self, kind: str, sort: str, limit: int) -> dict[str, Any]:
        try:
            rows = self.sources.sina_boards(kind)
            self._event("market_sectors", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("market_sectors", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("板块数据暂时不可用，稍后再试") from None
        rows.sort(
            key=lambda row: (
                -(row.get("change_pct") if row.get("change_pct") is not None else -1e18)
                if sort == "change"
                else -(row.get("amount_yuan") or 0.0)
            )
        )
        cleaned = [self._sector_row(row, kind) for row in rows[:limit]]
        return envelope(
            "ok",
            data={"kind": kind, "sort": sort, "rows": cleaned},
            as_of=now_iso(self.service.now()),
            basis_items=[basis("code", SINA_TAXONOMY_NOTE)],
        )

    def _sectors_ths(self, sort: str, limit: int) -> dict[str, Any]:
        try:
            raw_rows = self.sources.ths_industry_summary()
            self._event("market_sectors", "q.10jqka.com.cn", ok=True)
        except Exception as exc:
            self._event("market_sectors", "q.10jqka.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("行业排行数据暂时不可用，稍后再试") from None
        parsed: list[dict[str, Any]] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            amount = _number(row.get("总成交额"))
            flow = _number(row.get("净流入"))
            parsed.append(
                {
                    "code": None,
                    "name": row.get("板块"),
                    "kind": "industry",
                    "change_pct": _number(row.get("涨跌幅")),
                    "amount_yuan": None if amount is None else amount * 100_000_000.0,
                    "up_count": _int_or_none(row.get("上涨家数")),
                    "down_count": _int_or_none(row.get("下跌家数")),
                    "limit_up_count": None,
                    "rel_300_pct": None,
                    "rank_change_30m": None,
                    "amount_share_pct": None,
                    "net_inflow_yuan": None if flow is None else flow * 100_000_000.0,
                    "member_count": None,
                    "leader": {
                        "name": row.get("领涨股"),
                        "change_pct": _number(row.get("领涨股-涨跌幅")),
                    },
                }
            )
        if not parsed:
            raise MarketError("行业排行数据暂时不可用，稍后再试")
        total_amount = sum(row["amount_yuan"] for row in parsed if row["amount_yuan"] is not None)
        for row in parsed:
            if total_amount > 0 and row["amount_yuan"] is not None:
                row["amount_share_pct"] = round(row["amount_yuan"] / total_amount * 100.0, 4)
        if sort == "amount":
            parsed.sort(key=lambda row: -(row["amount_yuan"] if row["amount_yuan"] is not None else -1e18))
        else:
            parsed.sort(key=lambda row: -(row["change_pct"] if row["change_pct"] is not None else -1e18))
        missing_items = [
            missing("code", "该口径只提供行业名称，没有板块代码"),
            missing("limit_up_count", "该口径没有板块内涨停家数"),
            missing("rel_300_pct", "该口径没有相对沪深300的涨跌幅"),
            missing("rank_change_30m", "该口径没有30分钟排名变化"),
            missing("member_count", "该口径没有板块成分数量"),
        ]
        return envelope(
            "partial",
            data={"kind": "industry", "sort": sort, "rows": parsed[:limit]},
            as_of=now_iso(self.service.now()),
            basis_items=[
                basis("classification", "行业分类为另一套行业口径，与默认一级行业不可直接对齐，名称与默认分类不通用"),
                basis("amount_share_pct", "板块成交额占该表全部行业成交额合计的比例，单位为百分数"),
            ],
            missing_items=missing_items,
        )

    @staticmethod
    def _sector_row(row: dict[str, Any], kind: str) -> dict[str, Any]:
        leader = row.get("leader") if isinstance(row.get("leader"), dict) else None
        if leader is None and isinstance(row.get("leaders"), list):
            leader = next((item for item in row["leaders"] if isinstance(item, dict)), None)
        return {
            "code": row.get("code"),
            "name": row.get("name"),
            "kind": kind,
            "change_pct": row.get("change_pct"),
            "amount_yuan": row.get("amount_yuan"),
            "member_count": row.get("member_count"),
            "leader": None if leader is None else _clean(leader, ("code", "name", "change_pct")),
        }

    def _sector_detail_sina(self, kind: str, code: str, limit: int) -> dict[str, Any]:
        board_kind = "concept" if code.startswith("gn_") else "industry"
        try:
            members = self.sources.sina_node(code, limit=max(limit, 20))
            boards = self.sources.sina_boards(board_kind)
            self._event("market_sectors", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("market_sectors", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("该板块的成分暂时取不到") from None
        board = next((row for row in boards if row.get("code") == code), None)
        data = self._sector_row(board or {"code": code, "name": None}, board_kind)
        data["members"] = members[:limit]
        return envelope(
            "partial" if board is None else "ok",
            data=data,
            as_of=now_iso(self.service.now()),
            basis_items=[basis("code", SINA_TAXONOMY_NOTE)],
            missing_items=[] if board is not None else [missing("name", "该板块不在当前分类列表中")],
        )

    # ------------------------------------------------------------------ fund flow
    def market_fund_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        scope = _str_arg(args, "scope", FLOW_SCOPES, "rank")
        assert scope is not None
        kind = _str_arg(args, "kind", ("in", "out"), "in")
        assert kind is not None
        limit = _int_arg(args, "limit", 1, config.MAX_FLOW_LIMIT, 10)
        days = _int_arg(args, "days", 1, 120, 20)
        include_bj = _bool_arg(args, "include_bj", False)
        code = args.get("code")
        if scope == "stock":
            if not isinstance(code, str):
                raise MarketError("scope=stock 时必须给 code，例如 600519")
            try:
                normalized = normalize_code(code)
            except InvalidCode as exc:
                raise MarketError(str(exc)) from None
            key = f"market_fund_flow|stock|{normalized.canonical}|{days}"
            return self._cached(
                key, config.FLOW_TTL, config.FLOW_FALLBACK, lambda: self._flow_stock(normalized, days)
            )
        if code is not None:
            raise MarketError("scope=stock 以外的请求不接受 code")
        key = f"market_fund_flow|{scope}|{kind}|{limit}|{include_bj}"
        return self._cached(
            key, config.FLOW_TTL, config.FLOW_FALLBACK, lambda: self._flow_rank(scope, kind, limit, include_bj)
        )

    def _flow_stock(self, code: Code, days: int) -> dict[str, Any]:
        try:
            rows = self.sources.sina_stock_history(code, days=days)
            self._event("market_fund_flow", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("market_fund_flow", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("该股票的资金流暂时取不到") from None
        if not rows:
            raise MarketError("该股票在该时段没有资金流数据")
        latest = rows[0]["date"]
        as_of = (
            now_iso(self.service.now())
            if latest == self.service.now().date().isoformat()
            else f"{latest}T15:00:00+08:00"
        )
        return envelope(
            "ok",
            data={"code": code.canonical, "scope": "stock", "days": rows},
            as_of=as_of,
            basis_items=[basis("main_net_yuan", FLOW_NOTE)],
        )

    def _flow_rank(self, scope: str, kind: str, limit: int, include_bj: bool) -> dict[str, Any]:
        try:
            if scope == "sector":
                rows = self.sources.sina_sector_flows(kind)
            else:
                rows = self.sources.sina_stock_flows(kind, include_bj=include_bj, limit=limit)
            self._event("market_fund_flow", "vip.stock.finance.sina.com.cn", ok=True)
        except Exception as exc:
            self._event("market_fund_flow", "vip.stock.finance.sina.com.cn", ok=False, error=type(exc).__name__)
            raise MarketError("资金流数据暂时不可用，稍后再试") from None
        for index, row in enumerate(rows[:limit], start=1):
            row["rank"] = index
        return envelope(
            "ok",
            data={"scope": scope, "kind": kind, "rows": rows[:limit]},
            as_of=now_iso(self.service.now()),
            basis_items=[basis("main_net_yuan", FLOW_NOTE)],
        )

    # ------------------------------------------------------------------ trading activity
    def market_trading_activity(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _str_arg(args, "kind", ACTIVITY_KINDS, None)
        if kind is None:
            raise MarketError("kind 只能是 dragon_tiger/block_trades/margin")
        code = args.get("code")
        if code is not None and not isinstance(code, str):
            raise MarketError("code 必须是 6 位数字或带 .SH/.SZ/.BJ 的代码")
        normalized = None
        if code:
            try:
                normalized = normalize_code(code)
            except InvalidCode as exc:
                raise MarketError(str(exc)) from None
        day = _date_arg(args, "date")
        days = _int_arg(args, "days", 1, 365, 30)
        limit = _int_arg(args, "limit", 1, 500, 200)
        key = f"market_trading_activity|{kind}|{normalized.canonical if normalized else None}|{day}|{days}|{limit}"
        ttl = config.ACTIVITY_TTL if kind == "margin" else 1800.0
        return self._cached(
            key, ttl, config.ACTIVITY_FALLBACK, lambda: self._activity_compute(kind, normalized, day, days, limit)
        )

    def _activity_compute(
        self, kind: str, code: Code | None, day: date | None, days: int, limit: int
    ) -> dict[str, Any]:
        if kind == "dragon_tiger":
            return self._dragon_tiger(code, day or self.service.now().date(), limit)
        if kind == "block_trades":
            if code is None:
                raise MarketError("kind=block_trades 时必须给 code")
            return self._block_trades(code, days)
        if code is None:
            raise MarketError("kind=margin 时必须给 code")
        return self._margin(code, days)

    def _datacenter(self, report: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        text_rows = self.sources.datacenter(report, params)
        self._event("market_trading_activity", "datacenter-web.eastmoney.com", ok=True)
        return text_rows

    def _dragon_tiger(self, code: Code | None, day: date, limit: int) -> dict[str, Any]:
        query = f"(TRADE_DATE='{day.isoformat()}')"
        if code is not None:
            query += f'(SECURITY_CODE="{code.digits}")'
        try:
            rows = self._datacenter(
                "RPT_DAILYBILLBOARD_DETAILS",
                {"filter": query, "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1", "pageNumber": "1", "pageSize": "500"},
            )
        except Exception as exc:
            self._event("market_trading_activity", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise MarketError("龙虎榜数据暂时取不到，请确认日期是否为交易日") from None
        appearances = [normalize_dragon_row(row) for row in rows[:limit]]
        data: dict[str, Any] = {"date": day.isoformat(), "count": len(rows), "appearances": appearances}
        missing_items: list[dict[str, Any]] = []
        if code is not None:
            try:
                buy_rows = self._datacenter(
                    "RPT_BILLBOARD_DAILYDETAILSBUY",
                    {"filter": query, "sortColumns": "BUY", "sortTypes": "-1", "pageNumber": "1", "pageSize": "500"},
                )
                sell_rows = self._datacenter(
                    "RPT_BILLBOARD_DAILYDETAILSSELL",
                    {"filter": query, "sortColumns": "SELL", "sortTypes": "-1", "pageNumber": "1", "pageSize": "500"},
                )
                data["seats"] = self._seat_groups(buy_rows, sell_rows)
            except Exception as exc:
                self._event("market_trading_activity", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
                missing_items.append(missing("seats", "该股的席位明细暂时取不到"))
        return envelope(
            "partial" if missing_items else "ok",
            data=data,
            as_of=f"{day.isoformat()}T18:00:00+08:00",
            missing_items=missing_items,
        )

    @staticmethod
    def _seat_groups(buy_rows: list[dict[str, Any]], sell_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[Any, dict[str, list[dict[str, Any]]]] = {}
        for side, rows in (("BUY", buy_rows), ("SELL", sell_rows)):
            for row in rows:
                groups.setdefault(row.get("TRADE_ID"), {"BUY": [], "SELL": []})[side].append(row)
        seats: list[dict[str, Any]] = []
        for sides in groups.values():
            for side in ("BUY", "SELL"):
                for rank, row in enumerate(sides[side], start=1):
                    seats.append(normalize_seat(row, side=side, rank=rank))
        return seats

    def _block_trades(self, code: Code, days: int) -> dict[str, Any]:
        end = self.service.now().date()
        start = end - timedelta(days=days - 1)
        query = (
            f'(SECURITY_CODE="{code.digits}")'
            f"(TRADE_DATE>='{start.isoformat()}')(TRADE_DATE<='{end.isoformat()}')"
        )
        try:
            rows = self._datacenter(
                "RPT_DATA_BLOCKTRADE",
                {"filter": query, "sortColumns": "TRADE_DATE", "sortTypes": "-1", "pageNumber": "1", "pageSize": "200"},
            )
        except Exception as exc:
            self._event("market_trading_activity", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise MarketError("大宗交易数据暂时取不到") from None
        records = [normalize_block_row(row) for row in rows]
        return envelope(
            "ok",
            data={"code": code.canonical, "days": days, "count": len(records), "records": records},
            as_of=f"{end.isoformat()}T18:00:00+08:00",
        )

    def _margin(self, code: Code, days: int) -> dict[str, Any]:
        try:
            rows = self._datacenter(
                "RPTA_WEB_RZRQ_GGMX",
                {"filter": f'(SCODE="{code.digits}")', "sortColumns": "DATE", "sortTypes": "-1",
                 "pageNumber": "1", "pageSize": str(days)},
            )
        except Exception as exc:
            self._event("market_trading_activity", "datacenter-web.eastmoney.com", ok=False, error=type(exc).__name__)
            raise MarketError("融资融券数据暂时取不到") from None
        records = [normalize_margin_row(row) for row in rows[:days]]
        if not records:
            raise MarketError("该代码没有融资融券数据")
        return envelope(
            "ok",
            data={"code": code.canonical, "days": days, "records": records},
            as_of=f"{records[0]['trade_date']}T18:00:00+08:00",
        )

    # ------------------------------------------------------------------ northbound
    def market_northbound(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = _str_arg(args, "kind", NORTHBOUND_KINDS, "daily")
        assert kind is not None
        day = _date_arg(args, "date")
        code = args.get("code")
        normalized = None
        if code is not None:
            if not isinstance(code, str):
                raise MarketError("code 必须是 6 位数字或带 .SH/.SZ 的代码")
            try:
                normalized = normalize_code(code)
            except InvalidCode as exc:
                raise MarketError(str(exc)) from None
        limit = args.get("limit", HOLDINGS_DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= HOLDINGS_MAX_LIMIT:
            raise MarketError(f"limit 必须是 1–{HOLDINGS_MAX_LIMIT} 的整数")
        sort = _str_arg(args, "sort", HOLDINGS_SORTS, "change_shares")
        days = args.get("days", 1)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= NORTHBOUND_MAX_DAYS:
            raise MarketError(f"days 必须是 1–{NORTHBOUND_MAX_DAYS} 的整数（只用于 kind=daily）")
        if kind == "daily" and days > 1:
            key = f"market_northbound|daily_series|{day}|{days}"
            return self._cached(
                key, self._northbound_ttl(), config.NORTHBOUND_FALLBACK, lambda: self._northbound_series(day, days)
            )
        key = f"market_northbound|{kind}|{day}|{normalized.canonical if normalized else None}|{limit}|{sort}"
        if kind == "holdings":
            ttl, fallback = config.HOLDINGS_TTL, config.HOLDINGS_FALLBACK
        else:
            ttl, fallback = self._northbound_ttl(), config.NORTHBOUND_FALLBACK
        payload = self._cached(
            key, ttl, fallback, lambda: self._northbound_compute(kind, day, normalized, limit, sort or "change_shares")
        )
        if kind in {"top_active", "holdings"}:
            payload = self._localize_names(payload)
        return payload

    def _localize_names(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Replace the channel's English stock names with the shared Chinese name table."""
        company = getattr(self, "company", None)
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("rows") if isinstance(data, dict) else None
        if company is None or not isinstance(rows, list) or not rows:
            return payload
        names = dict(company.name_map(wait=6.0) or {})
        # Codes the abbreviation table misses (e.g. 601899): one batched quote for up to
        # 20 of them, only for short lists (top_active, a code query or a small limit).
        unknown = [
            str(row.get("code")) for row in rows
            if isinstance(row, dict) and str(row.get("code") or "") not in names
            and re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(row.get("code") or ""))
        ]
        if unknown and len(rows) <= 50:
            quoted = self.service.call("market_quote", {"codes": unknown[:20]})
            for quote in (quoted.get("data") or {}).get("quotes", []) if isinstance(quoted, dict) else []:
                if quote.get("code") and quote.get("name"):
                    names[quote["code"]] = quote["name"]
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = names.get(str(row.get("code") or ""))
            if name:
                row["name"] = name
        return payload

    def _northbound_ttl(self) -> float:
        now = self.service.now()
        next_morning = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        return max(60.0, (next_morning - now).total_seconds())

    def _northbound_compute(
        self, kind: str, day: date | None, code: Code | None, limit: int, sort: str
    ) -> dict[str, Any]:
        if kind == "holdings":
            if code is not None:
                return self._northbound_holdings(day, code)
            return self._northbound_holdings_all(day, limit, sort)
        data = self._hkex_daily(day)
        if kind == "daily":
            channels = [
                {"channel": channel, **values} for channel, values in sorted(data["channels"].items())
            ]
            total = sum(float(item.get("total_turnover_yuan") or 0.0) for item in channels)
            return envelope(
                "ok",
                data={"date": data["date"], "channels": channels, "total_turnover_yuan": round(total, 2)},
                as_of=str(data["date"]),
                basis_items=[basis("total_turnover_yuan", NORTHBOUND_NOTE)],
            )
        rows = []
        for channel in ("sh", "sz"):
            for row in data["top_active"].get(channel) or []:
                if code is not None and row.get("code") != code.canonical:
                    continue
                rows.append({"channel": channel, **row})
        if not rows:
            raise MarketError("该日期的前十活跃股数据取不到")
        return envelope(
            "ok",
            data={"date": data["date"], "rows": rows},
            as_of=str(data["date"]),
            basis_items=[basis("turnover_yuan", NORTHBOUND_NOTE + "；前十活跃股成交额无买卖拆分")],
        )

    def _hkex_day(self, day: date) -> dict[str, Any] | None:
        """One published daily file, memoised: a day's statistics never change once published."""
        with self._hkex_days_lock:
            if day in self._hkex_days:
                return copy.deepcopy(self._hkex_days[day])
        try:
            data = self.service.flight.run(f"hkex_day|{day.isoformat()}", lambda: self.sources.hkex_daily(day))
        except Exception:
            return None
        with self._hkex_days_lock:
            self._hkex_days[day] = copy.deepcopy(data)
        return data

    def _northbound_series(self, end: date | None, days: int) -> dict[str, Any]:
        """The last `days` trading days of northbound turnover, oldest first, in one call."""
        current = end or _last_weekday(self.service.now().date())
        rows: list[dict[str, Any]] = []
        probe = current
        for _ in range(days * 2 + 6):
            if len(rows) >= days:
                break
            if probe.weekday() < 5:
                data = self._hkex_day(probe)
                if data is not None:
                    channels = [
                        {"channel": channel, **values} for channel, values in sorted(data["channels"].items())
                    ]
                    total = sum(float(item.get("total_turnover_yuan") or 0.0) for item in channels)
                    rows.append({"date": str(data["date"]), "channels": channels, "total_turnover_yuan": round(total, 2)})
            probe -= timedelta(days=1)
        self._event("market_northbound", "www.hkex.com.hk", ok=bool(rows))
        if not rows:
            raise MarketError("北向成交数据暂时取不到，稍后再试")
        rows.reverse()
        missing_items = [] if len(rows) == days else [missing("days", f"只取到 {len(rows)} 个交易日的数据")]
        return envelope(
            "partial" if missing_items else "ok",
            data={"count": len(rows), "days": rows},
            as_of=rows[-1]["date"],
            basis_items=[basis("total_turnover_yuan", NORTHBOUND_NOTE)],
            missing_items=missing_items,
        )

    def _hkex_daily(self, day: date | None) -> dict[str, Any]:
        candidates: list[date] = []
        if day is not None:
            candidates = [day]
        else:
            current = _last_weekday(self.service.now().date())
            candidates = [current - timedelta(days=offset) for offset in range(0, 8)]
            candidates = [item for item in candidates if item.weekday() < 5]
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                data = self.sources.hkex_daily(candidate)
                self._event("market_northbound", "www.hkex.com.hk", ok=True)
                return data
            except Exception as exc:
                last_error = exc
                continue
        self._event("market_northbound", "www.hkex.com.hk", ok=False, error=type(last_error).__name__)
        if day is not None:
            raise MarketError("该日期没有北向成交数据；请确认是否为交易日") from None
        raise MarketError("北向成交数据暂时取不到，稍后再试") from None

    def _holdings_page(self, channel: str, day: date | None) -> dict[str, Any]:
        """One channel's quarterly holdings page, shared by every code and the full list.

        The pages are large and the site is rate limited; past quarters never change
        and the latest one changes once a quarter, so a day-long cache is safe.
        """
        key = f"{channel}|{day.isoformat() if day else 'latest'}"
        now = self.service.clock()
        with self._holdings_lock:
            hit = self._holdings_pages.get(key)
            if hit is not None and now - hit[0] < config.HOLDINGS_TTL:
                return copy.deepcopy(hit[1])
        page = self.service.flight.run(
            f"hkex_holdings_page|{key}", lambda: self.sources.hkex_holdings(channel, day=day)
        )
        with self._holdings_lock:
            self._holdings_pages[key] = (now, copy.deepcopy(page))
            if day is None:
                self._holdings_pages[f"{channel}|{page['date'].isoformat()}"] = (now, copy.deepcopy(page))
        return page

    def _northbound_holdings(
        self, day: date | None, code: Code | None, *, all_rows: bool = False
    ) -> dict[str, Any]:
        if code is not None and code.exchange == "BJ":
            raise MarketError("北向持股只覆盖沪股通和深股通标的，不支持北交所代码")
        channel = "sz" if code is not None and code.exchange == "SZ" else "sh"
        if day is not None and day != quarter_end(day):
            raise MarketError("date 必须是季度末（03-31、06-30、09-30、12-31）")
        try:
            current = self._holdings_page(channel, day)
            if day is not None and current["date"] != day:
                raise MarketError("该季度没有持股数据；披露易只保留最近 12 个月")
            self._event("market_northbound", "www3.hkexnews.hk", ok=True)
        except MarketError:
            raise
        except Exception as exc:
            self._event("market_northbound", "www3.hkexnews.hk", ok=False, error=type(exc).__name__)
            raise MarketError("北向季度持股数据暂时取不到") from None
        missing_items: list[dict[str, Any]] = []
        previous_rows: list[dict[str, Any]] = []
        previous_date = previous_quarter_end(current["date"])
        try:
            previous = self._holdings_page(channel, previous_date)
            previous_rows = previous["rows"]
        except Exception:
            missing_items.append(missing("change_shares", "上季度持股取不到，无法计算变化"))
        rows = holdings_change(current["rows"], previous_rows)
        if code is not None and not all_rows:
            rows = [row for row in rows if row.get("code") == code.canonical]
            if not rows:
                raise MarketError("该季度持股名单中没有该代码")
        return envelope(
            "partial" if missing_items else "ok",
            data={
                "channel": channel,
                "date": current["date"].isoformat(),
                "previous_date": None if missing_items else previous_date.isoformat(),
                "count": len(rows),
                "rows": rows,
            },
            as_of=current["date"].isoformat(),
            basis_items=[
                basis("shareholding_shares", HOLDINGS_NOTE),
                basis("change_shares", "季度持股变化=本季末持股−上季末持股；比例变化为百分点差"),
            ],
            missing_items=missing_items,
        )


    def _northbound_holdings_all(self, day: date | None, limit: int, sort: str) -> dict[str, Any]:
        """Both Stock Connect channels, ranked by `sort` (descending) and capped at `limit`."""
        parts = []
        for probe in (normalize_code("600000"), normalize_code("000001")):
            part = self._northbound_holdings(day, probe, all_rows=True)
            parts.append(part)
        rows = [row for part in parts for row in part["data"]["rows"]]
        missing_items = [item for part in parts for item in part.get("missing", [])]
        rows.sort(key=lambda row: (row.get(sort) is None, -(row.get(sort) or 0.0)))
        first = parts[0]["data"]
        return envelope(
            "partial" if missing_items else "ok",
            data={
                "date": first["date"],
                "previous_date": first["previous_date"],
                "sort": sort,
                "total_count": len(rows),
                "count": min(limit, len(rows)),
                "rows": rows[:limit],
            },
            as_of=parts[0]["as_of"],
            basis_items=parts[0].get("basis"),
            missing_items=missing_items,
        )