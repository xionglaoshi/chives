"""Deterministic polling engine: fetch -> compute -> evaluate rules -> store alerts.

Every external datum is read through the local data gateway (``POST
/v1/call``); the engine owns no vendor host list.  R1/R2 use indexes, breadth
and watchlist quotes; R3-R6 stay suppressed because the gateway industry
taxonomy has no stable board code, constituent set or limit-pool attribution.

Every data block keeps its last valid value in sqlite.  A process start does a
full fetch immediately (whatever the trading state), then loads the persisted
snapshot first so a restart has data before the first network round-trip.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from collections import deque
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import calendar as cal
from .calc import flows as flows_calc
from .calc import metrics
from .calc import movers as movers_calc
from .calc import pools as pools_calc
from .calc import summary as summary_calc
from .config import MarketConfig, SectorDef, load_config, load_watchlist
from .gateway import GatewayClient, SourceError
from .models import (
    CN_TZ,
    Block,
    BoardQuote,
    Breadth,
    FlowRow,
    IndexQuote,
    LimitPool,
    MemberQuote,
    MoverRow,
    StockQuote,
    dataclass_from_dict,
    dataclass_to_dict,
    fmt_iso,
    parse_iso,
)
from .rules import AlertDraft, MarketView, RuleEvaluator, SectorView
from .sources.gateway import (
    INDEX_CODES,
    INDEX_NAMES,
    BoardRow,
    BreadthSource,
    BoardSource,
    FlowSource,
    GatewayClient,
    HistoryBar,
    LimitPoolSource,
    MemberRow,
    MoversSource,
    NorthboundSource,
    PoolStock,
    QuoteSource,
    TrendPoint,
    pool_rows,
)
from .store import AlertStore, StoredMember

logger = logging.getLogger("market_watch.engine")

INDEX_STATE_NOTE = "休市，显示上一交易时段最后值"
FROZEN_STATES = {"holiday", "closed", "lunch", "pre_open"}

BLOCK_INDEX = "index"
BLOCK_STOCK = "stock"
BLOCK_BREADTH = "breadth"
BLOCK_POOL = "pool"
BLOCK_BOARDS = "boards"
BLOCK_SW = "sw"
MEMBER_PREFIX = "members:"
HISTORY_PREFIX = "history:"
TREND_PREFIX = "trend:"
MOVERS_PREFIX = "movers:"
FLOW_PREFIX = "flows:"
DAILY_SPARK_PREFIX = "dailyspark:"
THEME_PREFIX = "themes:"

MOVER_KINDS = movers_calc.MOVER_KINDS
MOVERS_TTL_SECONDS = 15.0
MOVERS_STALE_SECONDS = 90.0
FLOW_KINDS = flows_calc.FLOW_KINDS
FLOWS_TTL_SECONDS = 20.0
FLOWS_STALE_SECONDS = 90.0
NORTHBOUND_TTL_SECONDS = 60.0
DAILY_SPARK_POINTS = 30
DAILY_SPARK_STALE_SECONDS = 900.0
THEME_SORTS = ("change", "amount")
THEMES_TTL_SECONDS = 30.0
THEMES_STALE_SECONDS = 120.0
YESTERDAY_TTL_SECONDS = 30.0
POOL_LIMIT_MAX = 500
POOL_HISTORY_DAYS = (10, 30)
BREADTH_KEEP_DAYS = 10
BACKFILL_DAYS = 30
BACKFILL_MIN_INTERVAL = 1.2
POOL_HISTORY_DEFINITION = pools_calc.HISTORY_DEFINITION
POOL_LADDER_DEFINITION = pools_calc.LADDER_DEFINITION
THEME_DEFINITION = pools_calc.THEME_DEFINITION
BY_INDUSTRY_DEFINITION = pools_calc.BY_INDUSTRY_DEFINITION
POOL_DEFINITION = (
    "网关涨停/炸板/跌停池（厂商口径）；字段缺失为 null，不补 0；"
    "涨停池按连板数降序、首封时间升序，炸板池按炸板次数降序，跌停池按成交额降序"
)
BREADTH_SERIES_DEFINITION = (
    "交易时段每分钟一点的上证+深证涨跌家数与涨停/跌停家数；"
    "服务重启造成的空窗不插值，gaps=true"
)
YESTERDAY_DEFINITION = (
    "昨日涨停股今日表现，涨跌幅均相对腾讯快照的昨收；"
    "开盘/最高/最低/现价取批量快照，现价为最近成交价（收盘后即收盘价）"
)
SINA_FLOW_DEFINITION = (
    "新浪资金流（个股主力=超大单 r0_net，行业/概念为净流入；厂商口径，仅作辅助参考）"
)
SINA_THEME_DEFINITION = "新浪概念板块（厂商口径）"
SINA_INDUSTRY_NOTE = (
    "行业块由行情网关提供（同花顺/新浪口径，非板块级行业分类）；"
    "没有板块代码与成分，R3–R6 暂停"
)


def weekday_pre_open(moment: datetime) -> bool:
    local = moment.astimezone(CN_TZ)
    return local.weekday() < 5 and local.hour * 60 + local.minute < 9 * 60 + 30


def _max_dt(values: Sequence[Optional[datetime]], fallback: datetime) -> datetime:
    present = [value for value in values if value is not None]
    return max(present) if present else fallback


def _stamp(text: Any) -> Optional[datetime]:
    if not isinstance(text, str) or not text:
        return None
    try:
        return parse_iso(text)
    except ValueError:
        return None


def to_exchange_code(code: str) -> Optional[str]:
    text = str(code or "").strip().upper()
    if not text:
        return None
    if "." in text:
        return text
    digits = text
    if len(digits) != 6 or not digits.isdigit():
        return None
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8", "92")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def compute_returns(
    bars: Sequence[HistoryBar], day: date, *, include_today: bool = False
) -> dict[str, Optional[float]]:
    closes = [bar.close for bar in bars if include_today or bar.day < day]
    result: dict[str, Optional[float]] = {"ret_5d_pct": None, "ret_20d_pct": None}
    if len(closes) < 2:
        return result
    last = closes[-1]
    if len(closes) >= 6 and closes[-6]:
        result["ret_5d_pct"] = round((last / closes[-6] - 1.0) * 100.0, 4)
    if len(closes) >= 21 and closes[-21]:
        result["ret_20d_pct"] = round((last / closes[-21] - 1.0) * 100.0, 4)
    return result


class Engine:
    def __init__(
        self,
        config: MarketConfig,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        client: Optional[Any] = None,
        store: Optional[AlertStore] = None,
        calendar: Optional[cal.TradingCalendar] = None,
        config_path: Optional[str | Path] = None,
        member_min_interval: Optional[float] = None,
    ) -> None:
        self.config = config
        self._clock = clock or (lambda: datetime.now(CN_TZ))
        self.config_path = Path(config_path or config.config_path) if (config_path or config.config_path) else None
        self.gateway = client or GatewayClient(
            config.gateway.url,
            timeout=config.polling.timeout_seconds,
            clock=self._clock,
        )
        self.client = self.gateway
        self.http = self.gateway
        self.store = store or AlertStore(config.runtime.db_path)
        self.calendar = calendar or cal.build_calendar(config.calendar_source, config.calendar_file)
        self.tencent = QuoteSource(self.gateway)
        self.breadth_source = BreadthSource(self.gateway)
        self.pool_source = LimitPoolSource(self.gateway)
        self.board_source = BoardSource(self.gateway)
        self.movers_source = MoversSource(self.gateway)
        self.flow_source = FlowSource(self.gateway)
        self.northbound_source = NorthboundSource(self.gateway)
        self.evaluator = RuleEvaluator(config.rules)
        self.evaluator.configure_cap(config.limits.alert_max_per_hour)
        self.evaluator.configure_suppression(
            config.suppression.enabled,
            config.suppression.open_minutes,
            config.suppression.close_minutes,
        )
        self.watchlist: tuple[str, ...] = load_watchlist(config.watchlist_file)
        self._lock = threading.RLock()
        self._index_block = Block(source="gateway.market_quote")
        self._stock_block = Block(source="gateway.market_quote")
        self._breadth_block = Block(source="gateway.market_overview")
        self._sw_block = Block(source="disabled")
        self._pool_block = Block(source="gateway.market_limit_pool")
        self._board_block = Block(source="gateway.market_sectors")
        self._member_blocks: dict[str, Block] = {}
        self._history_blocks: dict[str, Block] = {}
        self._history_returns: dict[str, dict[str, Optional[float]]] = {}
        self._trend_blocks: dict[str, Block] = {}
        self._movers_blocks: dict[str, Block] = {}
        self._flow_blocks: dict[str, Block] = {}
        self._northbound_block: Optional[Block] = None
        self._daily_spark_blocks: dict[str, Block] = {}
        self._theme_blocks: dict[str, Block] = {}
        self._yesterday_cache: Optional[tuple[datetime, dict[str, Any]]] = None
        self._backfill_lock = threading.Lock()
        self._backfill_state: dict[str, Any] = {
            "running": False,
            "done": 0,
            "total": 0,
            "failed": 0,
            "started_at": None,
            "finished_at": None,
        }
        self._backfill_thread: Optional[threading.Thread] = None
        self._post_close_day: Optional[date] = None
        self._sector_universe: tuple[SectorDef, ...] = ()
        self._sector_missing: list[dict[str, Any]] = []
        self._universe_checked_at: Optional[datetime] = None
        self._board_names: dict[str, str] = {}
        self._last_poll: dict[str, datetime] = {}
        self._spark: dict[str, deque[tuple[datetime, float]]] = {}
        self._sector_series: dict[str, deque[tuple[datetime, float]]] = {}
        self._rank_history: deque[tuple[datetime, dict[str, int]]] = deque(maxlen=6000)
        self._breadth_history: deque[tuple[datetime, float, str]] = deque(maxlen=2000)
        self._sector_zt_history: deque[tuple[datetime, dict[str, int]]] = deque(maxlen=4000)
        self._stock_history: dict[str, deque[tuple[datetime, float]]] = {}
        self._sector_change_history: dict[str, deque[tuple[datetime, float]]] = {}
        self._trading_state = "closed"
        self._state_note: Optional[str] = None
        self._config_mtime: Optional[float] = None
        self.config_reload_error: Optional[str] = None
        self._refresh_days: dict[str, date] = {}
        self._cold_start_done = False
        self._stopped = threading.Event()
        self._last_baseline_minute: Optional[datetime] = None
        self._member_min_interval = (
            config.polling.member_min_interval_seconds
            if member_min_interval is None
            else max(0.0, float(member_min_interval))
        )
        self._last_member_fetch: Optional[float] = None
        self._restore_snapshot()
        if self.config_path is not None:
            try:
                self._config_mtime = self.config_path.stat().st_mtime
            except OSError:
                self._config_mtime = None

    # ------------------------------------------------------------------
    # scheduling
    # ------------------------------------------------------------------
    def now(self) -> datetime:
        return self._clock().astimezone(CN_TZ)

    def bootstrap(self) -> None:
        """Load the snapshot (done in ``__init__``) and fetch every block once."""
        moment = self.now()
        with self._lock:
            self._trading_state = cal.trading_state(moment, self.calendar)
        self._ensure_cold_start(moment)
        self.start_backfill()

    def tick(self, now: Optional[datetime] = None) -> None:
        moment = (now or self.now()).astimezone(CN_TZ)
        self.maybe_reload_config()
        state = cal.trading_state(moment, self.calendar)
        with self._lock:
            self._trading_state = state
        cold = self._ensure_cold_start(moment)
        if state == "open":
            polled = self._poll_live(moment)
            if cold or polled:
                self.evaluate(moment)
        elif state == "lunch":
            if self._due("index", moment, max(30.0, self.config.polling.index_seconds)):
                self.poll_indexes(moment)
        elif state in {"pre_open", "closed", "holiday"}:
            if not cold and cal.in_refresh_window(moment, self.calendar):
                bucket = "pre_open" if weekday_pre_open(moment) else "closed"
                self._poll_once_per_day(moment, bucket)
            if state == "closed":
                self._maybe_post_close_snapshot(moment)
        else:  # pragma: no cover - defensive
            logger.warning("未知交易状态: %s", state)

    def _ensure_cold_start(self, moment: datetime) -> bool:
        with self._lock:
            if self._cold_start_done:
                return False
            self._cold_start_done = True
        logger.info("冷启动：立即完整取数一次（trading_state=%s）", self._trading_state)
        self._full_refresh(moment)
        if cal.in_refresh_window(moment, self.calendar):
            bucket = "pre_open" if weekday_pre_open(moment) else "closed"
            with self._lock:
                self._refresh_days[bucket] = moment.date()
        return True

    def _full_refresh(self, moment: datetime) -> None:
        for label, poller in (
            ("index", self.poll_indexes),
            ("breadth", self.poll_breadth),
            ("limit_pool", self.poll_limit_pool),
            ("boards", self.poll_boards),
            ("members", self.poll_all_members),
            ("movers", self.poll_movers),
            ("flows", self.poll_flows),
            ("themes", self.poll_themes),
            ("daily_spark", self.poll_daily_spark),
        ):
            self._safe_poll(label, poller, moment)
        with self._lock:
            for key in (
                "index", "breadth", "pool", "boards", "movers", "flows",
                "themes", "daily_spark",
            ):
                self._last_poll[key] = moment

    def _safe_poll(self, label: str, poller: Callable[[datetime], None], moment: datetime) -> None:
        try:
            poller(moment)
        except Exception:  # noqa: BLE001 - one source must never stop the others
            logger.exception("冷启动/轮询失败: %s", label)

    def _poll_once_per_day(self, moment: datetime, bucket: str) -> None:
        today = moment.date()
        with self._lock:
            if self._refresh_days.get(bucket) == today:
                return
            self._refresh_days[bucket] = today
        self._full_refresh(moment)

    def _due(self, key: str, moment: datetime, seconds: float) -> bool:
        with self._lock:
            last = self._last_poll.get(key)
            if last is None or (moment - last).total_seconds() >= seconds:
                self._last_poll[key] = moment
                return True
        return False

    def _poll_live(self, moment: datetime) -> bool:
        polling = self.config.polling
        polled = False
        if self._due("index", moment, polling.index_seconds):
            self.poll_indexes(moment)
            polled = True
        if self._due("breadth", moment, polling.breadth_seconds):
            self._safe_poll("breadth", self.poll_breadth, moment)
        if self._due("pool", moment, polling.limit_pool_seconds):
            self._safe_poll("limit_pool", self.poll_limit_pool, moment)
        if self._due("boards", moment, polling.breadth_seconds):
            self._safe_poll("boards", self.poll_boards, moment)
        if self._due("movers", moment, polling.movers_seconds):
            self._safe_poll("movers", self.poll_movers, moment)
        if self._due("flows", moment, polling.flows_seconds):
            self._safe_poll("flows", self.poll_flows, moment)
        if self._due("themes", moment, max(30.0, polling.flows_seconds)):
            self._safe_poll("themes", self.poll_themes, moment)
        if self._due("daily_spark", moment, polling.daily_spark_seconds):
            self._safe_poll("daily_spark", self.poll_daily_spark, moment)
        return polled

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------
    def _persist(self, name: str, block: Block, value: Any) -> None:
        try:
            self.store.save_block(
                name,
                value=value,
                as_of=block.as_of,
                fetched_at=block.fetched_at,
                source=block.source,
                reason=block.reason,
                updated_at=block.fetched_at or self.now(),
            )
        except Exception:  # noqa: BLE001 - persistence must not break polling
            logger.exception("持久化数据块失败: %s", name)

    def _mark_failure(
        self,
        block: Block,
        source: str,
        moment: datetime,
        reason: str,
        *,
        stale: bool = False,
    ) -> Block:
        """Keep the last valid value and attach the failure reason."""
        return Block(
            value=block.value,
            as_of=block.as_of,
            fetched_at=block.fetched_at,
            source=block.source or source,
            reason=reason,
            stale=block.stale or stale,
            fallback=block.fallback,
            fallback_reason=block.fallback_reason,
        )

    def _restore_snapshot(self) -> None:
        try:
            records = self.store.load_blocks()
        except Exception:  # noqa: BLE001 - an old/corrupt db must not block startup
            logger.exception("读取持久化数据块失败，按空库继续")
            return
        for name, record in records.items():
            block = Block(
                value=record.get("value"),
                as_of=_stamp(record.get("as_of")),
                fetched_at=_stamp(record.get("fetched_at")),
                source=str(record.get("source") or ""),
                reason=record.get("reason"),
            )
            try:
                if name == BLOCK_INDEX:
                    block.value = {
                        str(code): dataclass_from_dict(IndexQuote, item)
                        for code, item in (record.get("value") or {}).items()
                    }
                    self._index_block = block
                elif name == BLOCK_STOCK:
                    block.value = {
                        str(code): dataclass_from_dict(StockQuote, item)
                        for code, item in (record.get("value") or {}).items()
                    }
                    self._stock_block = block
                elif name == BLOCK_BREADTH:
                    block.value = dataclass_from_dict(Breadth, record.get("value"))
                    self._breadth_block = block
                elif name == BLOCK_POOL:
                    block.value = dataclass_from_dict(LimitPool, record.get("value"))
                    self._pool_block = block
                elif name == BLOCK_BOARDS:
                    payload = record.get("value") or {}
                    quotes = [
                        dataclass_from_dict(BoardQuote, item)
                        for item in payload.get("quotes", [])
                    ]
                    block.value = quotes
                    self._board_block = block
                    self._board_names = {
                        str(code): str(board)
                        for code, board in (payload.get("names") or {}).items()
                    }
                    self._sector_missing = list(payload.get("missing") or [])
                    self._universe_checked_at = _stamp(payload.get("checked_at")) or block.fetched_at
                elif name == BLOCK_SW:
                    block.value = record.get("value")
                    self._sw_block = block
                elif name.startswith(MEMBER_PREFIX):
                    code = name[len(MEMBER_PREFIX):]
                    block.value = [
                        dataclass_from_dict(MemberQuote, item)
                        for item in (record.get("value") or [])
                    ]
                    self._member_blocks[code] = block
                elif name.startswith(HISTORY_PREFIX):
                    code = name[len(HISTORY_PREFIX):]
                    block.value = dict(record.get("value") or {})
                    self._history_blocks[code] = block
                    self._history_returns[code] = block.value
                elif name.startswith(TREND_PREFIX):
                    code = name[len(TREND_PREFIX):]
                    points = []
                    for item in record.get("value") or []:
                        stamp = _stamp(item.get("t"))
                        if stamp is not None:
                            points.append(
                                TrendPoint(
                                    t=stamp,
                                    price=float(item.get("price") or 0.0),
                                    change_pct=item.get("change_pct"),
                                )
                            )
                    block.value = points
                    self._trend_blocks[code] = block
                elif name.startswith(MOVERS_PREFIX):
                    key = name[len(MOVERS_PREFIX):]
                    block.value = [
                        dataclass_from_dict(MoverRow, item)
                        for item in (record.get("value") or [])
                    ]
                    self._movers_blocks[key] = block
                elif name.startswith(FLOW_PREFIX):
                    key = name[len(FLOW_PREFIX):]
                    block.value = [
                        dataclass_from_dict(FlowRow, item)
                        for item in (record.get("value") or [])
                    ]
                    self._flow_blocks[key] = block
                elif name.startswith(DAILY_SPARK_PREFIX):
                    code = name[len(DAILY_SPARK_PREFIX):]
                    bars: list[HistoryBar] = []
                    for item in record.get("value") or []:
                        day = _stamp(str(item.get("day") or "") + "T00:00:00+08:00")
                        close = item.get("close")
                        if day is not None and close is not None:
                            bars.append(HistoryBar(day=day.date(), close=float(close)))
                    block.value = bars
                    self._daily_spark_blocks[code] = block
                elif name.startswith(THEME_PREFIX):
                    key = name[len(THEME_PREFIX):]
                    block.value = [
                        dataclass_from_dict(BoardQuote, item)
                        for item in (record.get("value") or [])
                    ]
                    self._theme_blocks[key] = block
            except (TypeError, ValueError, KeyError):
                logger.exception("恢复数据块失败，忽略: %s", name)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def poll_indexes(self, now: datetime) -> None:
        try:
            indexes, stocks = self.tencent.fetch_market(now, list(self.watchlist))
        except SourceError as exc:
            with self._lock:
                self._index_block = self._mark_failure(self._index_block, "gateway.market_quote", now, str(exc))
                self._stock_block = self._mark_failure(self._stock_block, "gateway.market_quote", now, str(exc))
            return
        today = now.date()
        as_of = _max_dt([quote.exch_time for quote in indexes.values()], now)
        with self._lock:
            self._index_block = Block(
                value=indexes, as_of=as_of, fetched_at=now, source="gateway.market_quote", stale=False
            )
            stock_as_of = _max_dt([quote.exch_time for quote in stocks.values()], now)
            self._stock_block = Block(
                value=stocks, as_of=stock_as_of, fetched_at=now, source="gateway.market_quote", stale=False
            )
            for code, quote in indexes.items():
                series = self._spark.setdefault(code, deque(maxlen=8000))
                series.append((quote.exch_time, quote.price))
            for code, quote in stocks.items():
                history = self._stock_history.setdefault(code, deque(maxlen=4000))
                history.append((now, quote.change_pct))
        self._persist(
            BLOCK_INDEX,
            self._index_block,
            {code: dataclass_to_dict(quote) for code, quote in indexes.items()},
        )
        self._persist(
            BLOCK_STOCK,
            self._stock_block,
            {code: dataclass_to_dict(quote) for code, quote in stocks.items()},
        )
        minute = now.replace(second=0, microsecond=0)
        with self._lock:
            if self._last_baseline_minute == minute:
                return
            self._last_baseline_minute = minute
        for code, quote in indexes.items():
            if quote.amount_yuan:
                self.store.record_daily_amount(f"idx:{code}", today, quote.amount_yuan)
        for code, quote in stocks.items():
            if quote.amount_yuan:
                self.store.record_daily_amount(f"stk:{code}", today, quote.amount_yuan)

    @staticmethod
    def _error_code(exc: BaseException) -> str:
        return str(getattr(exc, "code", "fallback_error"))

    @classmethod
    def _error_chain(cls, primary: BaseException, fallback: BaseException) -> str:
        return (
            f"{cls._error_code(primary)}: {primary}；"
            f"备用源失败: {cls._error_code(fallback)}: {fallback}"
        )

    def poll_breadth(self, now: datetime) -> None:
        try:
            breadth = self.breadth_source.fetch(now)
        except SourceError as exc:
            with self._lock:
                self._breadth_block = self._mark_failure(
                    self._breadth_block, "gateway.market_overview", now, str(exc)
                )
            return
        breadth = Breadth(
            up=breadth.up,
            down=breadth.down,
            flat=breadth.flat,
            up_ratio=breadth.up_ratio,
            amount_yuan=breadth.amount_yuan,
            as_of=breadth.as_of,
            fetched_at=now,
            source=breadth.source,
        )
        with self._lock:
            self._breadth_block = Block(
                value=breadth, as_of=breadth.as_of, fetched_at=now, source=breadth.source
            )
            if breadth.up_ratio is not None:
                self._breadth_history.append((now, breadth.up_ratio, breadth.source))
        self._persist(BLOCK_BREADTH, self._breadth_block, dataclass_to_dict(breadth))
        self._record_breadth_point(now)

    def poll_sw(self, now: datetime) -> None:
        """Shenwan health block was removed with the direct-source layer."""
        return

    def poll_limit_pool(self, now: datetime) -> None:
        try:
            pool = self.pool_source.fetch(now)
        except SourceError as exc:
            with self._lock:
                self._pool_block = self._mark_failure(
                    self._pool_block, "gateway.market_limit_pool", now, str(exc)
                )
            return
        with self._lock:
            self._pool_block = Block(
                value=pool, as_of=now, fetched_at=now, source="gateway.market_limit_pool", stale=False
            )
        self._persist(BLOCK_POOL, self._pool_block, dataclass_to_dict(pool))
        self._save_pool_details(now, pool)
        self._record_day_stats(now)

    def poll_boards(self, now: datetime) -> None:
        try:
            rows = self.board_source.fetch_all(now)
        except SourceError as exc:
            with self._lock:
                self._board_block = self._mark_failure(
                    self._board_block, "gateway.market_sectors", now, str(exc)
                )
            return
        quotes = [
            BoardQuote(
                code=row.code,
                name=row.name,
                change_pct=row.change_pct,
                amount_yuan=row.amount_yuan,
                up=row.up,
                down=row.down,
                flat=row.flat,
                leader_code=row.leader_code,
                leader_name=row.leader_name,
                leader_change_pct=row.leader_change_pct,
                price=row.price,
                prev_close=row.prev_close,
                as_of=row.provider_time or now,
                member_total=row.member_total,
            )
            for row in rows
        ]
        block = Block(
            value=quotes,
            as_of=_max_dt([quote.as_of for quote in quotes], now),
            fetched_at=now,
            source="gateway.market_sectors",
            fallback=True,
            fallback_reason="industry_taxonomy_changed",
        )
        with self._lock:
            self._board_block = block
            self._board_names = {row.code: row.name for row in rows}
            self._sector_missing = []
            self._universe_checked_at = now
            for quote in quotes:
                if quote.change_pct is None:
                    continue
                series = self._sector_change_history.setdefault(quote.code, deque(maxlen=4000))
                series.append((now, quote.change_pct))
        self._persist(
            BLOCK_BOARDS,
            block,
            {
                "quotes": [dataclass_to_dict(quote) for quote in quotes],
                "names": dict(self._board_names),
                "missing": [],
                "checked_at": fmt_iso(now),
            },
        )

    def poll_movers(self, now: datetime) -> None:
        """Refresh the three default all-A lists (Beijing excluded)."""
        for kind in MOVER_KINDS:
            self._poll_movers_kind(kind, now, include_bj=False)

    def _poll_movers_kind(
        self, kind: str, now: datetime, *, include_bj: bool
    ) -> Optional[Block]:
        key = f"{kind}:{1 if include_bj else 0}"
        with self._lock:
            block = self._movers_blocks.get(key)
        if (
            block is not None
            and block.value is not None
            and block.fetched_at is not None
            and (now - block.fetched_at).total_seconds() < MOVERS_TTL_SECONDS
        ):
            return block
        try:
            rows = self.movers_source.fetch(
                kind, now, include_bj=include_bj, cache_ttl=MOVERS_TTL_SECONDS
            )
        except SourceError as exc:
            with self._lock:
                self._movers_blocks[key] = self._mark_failure(
                    block if block is not None else Block(source="gateway.market_movers"),
                    "gateway.market_movers",
                    now,
                    str(exc),
                )
            return None
        new_block = Block(
            value=rows,
            as_of=now,
            fetched_at=now,
            source="gateway.market_movers",
        )
        with self._lock:
            self._movers_blocks[key] = new_block
        self._persist(
            f"{MOVERS_PREFIX}{key}",
            new_block,
            [dataclass_to_dict(row) for row in rows],
        )
        return new_block

    def _ensure_movers(
        self, kind: str, now: datetime, *, include_bj: bool, state: str
    ) -> Block:
        key = f"{kind}:{1 if include_bj else 0}"
        with self._lock:
            block = self._movers_blocks.get(key)
            age = (
                None
                if block is None or block.fetched_at is None
                else (now - block.fetched_at).total_seconds()
            )
        needs_fetch = block is None or (block.value is None and block.reason is None)
        if state == "open" and age is not None and age > MOVERS_TTL_SECONDS:
            needs_fetch = True
        if needs_fetch:
            refreshed = self._poll_movers_kind(kind, now, include_bj=include_bj)
            if refreshed is not None:
                return refreshed
            with self._lock:
                block = self._movers_blocks.get(key)
        return block if block is not None else Block(source="gateway.market_movers")

    def poll_flows(self, now: datetime) -> None:
        """Refresh the sector ranking and the two default stock directions."""
        self._poll_flow_sectors(now)
        self._poll_flow_stocks("stock_in", now, include_bj=False)
        self._poll_flow_stocks("stock_out", now, include_bj=False)

    # -- v1.4 pool persistence and intraday breadth ----------------------
    def _save_pool_details(self, now: datetime, pool: LimitPool) -> None:
        if not self.calendar.is_trading_day(now) or now.time() < time(9, 30):
            return
        for kind in pools_calc.POOL_KINDS:
            rows = pool.details.get(kind)
            if rows is None:
                continue
            count = {
                "zt": pool.limit_up,
                "zb": pool.broken,
                "dt": pool.limit_down,
            }[kind]
            try:
                self.store.save_pool_day(
                    now.date(),
                    kind,
                    count=count,
                    rows=rows,
                    fetched_at=now,
                    available=True,
                )
            except Exception:  # noqa: BLE001 - persistence must not break polling
                logger.exception("保存池明细失败: %s", kind)

    def _record_breadth_point(self, now: datetime) -> None:
        """Store one minute point while the market is open (first sample wins)."""
        with self._lock:
            state = self._trading_state
            block = self._breadth_block
            pool_block = self._pool_block
            breadth = block.value
            pool = pool_block.value
        if state != "open" or breadth is None:
            return
        if not self.calendar.is_trading_day(now):
            return
        limit_up = pool.limit_up if pool is not None else None
        limit_down = pool.limit_down if pool is not None else None
        if pool_block.fetched_at is None or pool_block.fetched_at.date() != now.date():
            limit_up = None
            limit_down = None
        try:
            self.store.save_breadth_point(
                now.date(),
                now.strftime("%H:%M"),
                up=breadth.up,
                down=breadth.down,
                flat=breadth.flat,
                limit_up=limit_up,
                limit_down=limit_down,
            )
            cutoff = self._breadth_cutoff(now)
            if cutoff is not None:
                self.store.prune_breadth_series(cutoff)
        except Exception:  # noqa: BLE001 - sampling is best effort
            logger.exception("保存宽度分钟点失败")

    def _breadth_cutoff(self, now: datetime) -> Optional[date]:
        days: list[date] = []
        cursor = now.date()
        while len(days) < BREADTH_KEEP_DAYS:
            if self.calendar.is_trading_day(
                datetime.combine(cursor, time(12, 0), tzinfo=CN_TZ)
            ):
                days.append(cursor)
            cursor -= timedelta(days=1)
            if (now.date() - cursor).days > 40:
                break
        return min(days) if len(days) >= BREADTH_KEEP_DAYS else None

    def _maybe_post_close_snapshot(self, moment: datetime) -> None:
        """After 15:05 take one final pool snapshot for the day (no retry storm)."""
        if moment.time() < time(15, 5) or not self.calendar.is_trading_day(moment):
            return
        with self._lock:
            if self._post_close_day == moment.date():
                return
            self._post_close_day = moment.date()
        fetched = None
        try:
            record = self.store.load_pool_day(moment.date(), "zt")
            fetched = _stamp(record.get("fetched_at")) if record else None
        except Exception:  # noqa: BLE001 - a missing snapshot just triggers a fetch
            logger.exception("读取当日池快照失败")
        if fetched is not None and fetched.time() >= time(15, 0):
            return
        self._safe_poll("limit_pool", self.poll_limit_pool, moment)

    def poll_themes(self, now: datetime) -> None:
        """Refresh the default concept-board ranking used by ``/themes``."""
        self._ensure_themes("change", now, state=self._trading_state, limit=20)

    def _ensure_themes(self, sort: str, now: datetime, *, state: str, limit: int) -> Block:
        key = f"concept:{sort}"
        with self._lock:
            block = self._theme_blocks.get(key)
            age = (
                None
                if block is None or block.fetched_at is None
                else (now - block.fetched_at).total_seconds()
            )
        needs_fetch = block is None or (block.value is None and block.reason is None)
        if state == "open" and age is not None and age > THEMES_TTL_SECONDS:
            needs_fetch = True
        if not needs_fetch:
            return block if block is not None else Block(source="gateway.market_sectors")
        try:
            rows = self.board_source.fetch_concepts(now, sort=sort)
        except SourceError as exc:
            with self._lock:
                self._theme_blocks[key] = self._mark_failure(
                    block if block is not None else Block(source="gateway.market_sectors"),
                    "gateway.market_sectors",
                    now,
                    str(exc),
                )
            return self._theme_blocks[key]
        new_block = Block(
            value=rows,
            as_of=now,
            fetched_at=now,
            source="gateway.market_sectors",
            fallback=True,
            fallback_reason="sina_concept_taxonomy",
        )
        with self._lock:
            self._theme_blocks[key] = new_block
        self._persist(
            f"{THEME_PREFIX}{key}",
            new_block,
            [dataclass_to_dict(row) for row in rows],
        )
        return new_block

    def _poll_flow_sectors(self, now: datetime) -> Optional[Block]:
        with self._lock:
            block = self._flow_blocks.get("sector")
        if (
            block is not None
            and block.value is not None
            and block.fetched_at is not None
            and (now - block.fetched_at).total_seconds() < FLOWS_TTL_SECONDS
        ):
            return block
        try:
            rows = self.flow_source.fetch_sector_flows(now, cache_ttl=FLOWS_TTL_SECONDS)
        except SourceError as exc:
            with self._lock:
                self._flow_blocks["sector"] = self._mark_failure(
                    block if block is not None else Block(source="gateway.market_fund_flow"),
                    "gateway.market_fund_flow",
                    now,
                    str(exc),
                )
            return None
        rows = flows_calc.sort_flows(rows, "sector_in")
        new_block = Block(
            value=rows,
            as_of=now,
            fetched_at=now,
            source="gateway.market_fund_flow",
            reason=None if rows else "行业资金流榜没有数据",
            fallback=True,
            fallback_reason="sina_flow_taxonomy",
        )
        with self._lock:
            self._flow_blocks["sector"] = new_block
        self._persist(
            f"{FLOW_PREFIX}sector",
            new_block,
            [dataclass_to_dict(row) for row in rows],
        )
        return new_block

    def _poll_flow_stocks(
        self, kind: str, now: datetime, *, include_bj: bool
    ) -> Optional[Block]:
        key = f"{kind}:{1 if include_bj else 0}"
        with self._lock:
            block = self._flow_blocks.get(key)
        if (
            block is not None
            and block.value is not None
            and block.fetched_at is not None
            and (now - block.fetched_at).total_seconds() < FLOWS_TTL_SECONDS
        ):
            return block
        try:
            rows = self.flow_source.fetch_stock_flows(
                kind, now, include_bj=include_bj, cache_ttl=FLOWS_TTL_SECONDS
            )
        except SourceError as exc:
            with self._lock:
                self._flow_blocks[key] = self._mark_failure(
                    block if block is not None else Block(source="gateway.market_fund_flow"),
                    "gateway.market_fund_flow",
                    now,
                    str(exc),
                )
            return None
        new_block = Block(
            value=rows,
            as_of=now,
            fetched_at=now,
            source="gateway.market_fund_flow",
            fallback=True,
            fallback_reason="sina_flow_taxonomy",
        )
        with self._lock:
            self._flow_blocks[key] = new_block
        self._persist(
            f"{FLOW_PREFIX}{key}",
            new_block,
            [dataclass_to_dict(row) for row in rows],
        )
        return new_block

    def _ensure_flow(
        self, kind: str, now: datetime, *, include_bj: bool, state: str
    ) -> Block:
        key = "sector" if kind in flows_calc.SECTOR_KINDS else f"{kind}:{1 if include_bj else 0}"
        with self._lock:
            block = self._flow_blocks.get(key)
            age = (
                None
                if block is None or block.fetched_at is None
                else (now - block.fetched_at).total_seconds()
            )
        needs_fetch = block is None or (block.value is None and block.reason is None)
        if state == "open" and age is not None and age > FLOWS_TTL_SECONDS:
            needs_fetch = True
        if needs_fetch:
            refreshed = (
                self._poll_flow_sectors(now)
                if kind in flows_calc.SECTOR_KINDS
                else self._poll_flow_stocks(kind, now, include_bj=include_bj)
            )
            if refreshed is not None:
                return refreshed
            with self._lock:
                block = self._flow_blocks.get(key)
        return block if block is not None else Block(source="gateway.market_movers")

    def _ensure_northbound(self, now: datetime) -> Block:
        with self._lock:
            block = self._northbound_block
            age = (
                None
                if block is None or block.fetched_at is None
                else (now - block.fetched_at).total_seconds()
            )
        if block is not None and age is not None and age < NORTHBOUND_TTL_SECONDS:
            return block
        try:
            value = self.northbound_source.fetch(now)
        except SourceError as exc:
            failed = Block(
                source="gateway.market_northbound", fetched_at=now, reason=str(exc)
            )
            with self._lock:
                self._northbound_block = failed
            return failed
        fresh = Block(
            value=value, as_of=now, fetched_at=now, source="gateway.market_northbound", stale=False
        )
        with self._lock:
            self._northbound_block = fresh
        return fresh

    def poll_daily_spark(self, now: datetime) -> None:
        """Cache the last 30 daily closes of every index (cold start included)."""
        for code in INDEX_CODES:
            with self._lock:
                block = self._daily_spark_blocks.get(code)
            if (
                block is not None
                and block.value
                and block.fetched_at is not None
                and (now - block.fetched_at).total_seconds()
                < self.config.polling.daily_spark_seconds
            ):
                continue
            try:
                bars = self.board_source.fetch_index_history(code, now)
            except SourceError as exc:
                with self._lock:
                    self._daily_spark_blocks[code] = self._mark_failure(
                        block if block is not None else Block(source="gateway.market_bars"),
                        "gateway.market_bars",
                        now,
                        str(exc),
                    )
                continue
            bars = bars[-DAILY_SPARK_POINTS:]
            last = bars[-1]
            new_block = Block(
                value=bars,
                as_of=datetime.combine(last.day, time(15, 0), tzinfo=CN_TZ),
                fetched_at=now,
                source="gateway.market_bars",
            )
            with self._lock:
                self._daily_spark_blocks[code] = new_block
            self._persist(
                f"{DAILY_SPARK_PREFIX}{code}",
                new_block,
                [{"day": bar.day.isoformat(), "close": bar.close} for bar in bars],
            )

    def poll_all_members(self, now: datetime) -> None:
        """Fetch every industry's constituents sequentially.

        The limit-up/broken counts are intersections of these code sets with the
        pool code lists, so all 31 industries need a member set even when the
        market is closed.  Requests are spaced by ``member_min_interval``.
        """
        if not self._board_block.value:
            return
        for item in list(self._sector_universe):
            try:
                self.ensure_members(item.code, now)
            except Exception:  # noqa: BLE001 - one bad industry must not stop the poller
                logger.exception("行业成分轮询失败: %s", item.code)

    def _pace_member_fetch(self) -> None:
        interval = self._member_min_interval
        if interval <= 0:
            return
        wait = 0.0
        with self._lock:
            current = _time.monotonic()
            if self._last_member_fetch is not None:
                wait = interval - (current - self._last_member_fetch)
            self._last_member_fetch = current + max(0.0, wait)
        if wait > 0:
            _time.sleep(wait)

    def ensure_members(self, sector: str, now: datetime) -> Optional[list[MemberQuote]]:
        stale_after = self.config.polling.members_seconds
        with self._lock:
            block = self._member_blocks.get(sector)
            if (
                block is not None
                and block.value is not None
                and block.fetched_at is not None
                and (now - block.fetched_at).total_seconds() < stale_after
            ):
                return block.value
            previous = block
        try:
            members, _total, as_of = self.board_source.fetch_members(
                sector, now, pace=self._pace_member_fetch
            )
        except SourceError as exc:
            with self._lock:
                if previous is not None and previous.value is not None:
                    self._member_blocks[sector] = self._mark_failure(
                        previous, "gateway.market_sectors", now, str(exc)
                    )
                    return previous.value
                self._member_blocks[sector] = Block(
                    source="gateway.market_sectors", fetched_at=now, reason=str(exc)
                )
            return None
        with self._lock:
            pool = self._pool_block.value
        zt_codes = {self._stock_code_key(code) for code in (pool.zt_codes if pool is not None else ())}
        dt_codes = {self._stock_code_key(code) for code in (pool.dt_codes if pool is not None else ())}
        rows: list[MemberQuote] = []
        for member in members:
            code = to_exchange_code(member.code) or member.code
            member_key = self._stock_code_key(member.code)
            rows.append(
                MemberQuote(
                    code=code,
                    name=member.name,
                    price=member.price if member.price is not None else 0.0,
                    change_pct=member.change_pct if member.change_pct is not None else 0.0,
                    amount_yuan=member.amount_yuan,
                    weight_pct=None,
                    limit_up=member_key in zt_codes,
                    limit_down=member_key in dt_codes,
                )
            )
        rows.sort(key=lambda row: (-(row.amount_yuan or 0.0), row.code))
        block = Block(
            value=rows,
            as_of=as_of,
            fetched_at=now,
            source="gateway.market_sectors",
            stale=False,
        )
        with self._lock:
            self._member_blocks[sector] = block
        self.store.save_members(
            sector,
            [
                StoredMember(
                    code=(row.code.split(".")[0] if "." in row.code else row.code),
                    name=row.name,
                    weight_pct=None,
                )
                for row in rows
            ],
            now,
        )
        self._persist(
            f"{MEMBER_PREFIX}{sector}",
            block,
            [dataclass_to_dict(row) for row in rows],
        )
        return rows

    def _fresh_members(self, sector: str, now: datetime) -> Optional[list[MemberQuote]]:
        with self._lock:
            block = self._member_blocks.get(sector)
        if block is None or block.value is None or block.fetched_at is None:
            return None
        age = (now - block.fetched_at).total_seconds()
        if age > self.config.polling.stale_after.get("members", 900.0):
            return None
        return block.value

    def ensure_history(self, sector: str, now: datetime) -> dict[str, Optional[float]]:
        with self._lock:
            block = self._history_blocks.get(sector)
            if (
                block is not None
                and block.fetched_at is not None
                and block.value is not None
                and (now - block.fetched_at).total_seconds() < self.config.polling.history_seconds
            ):
                return block.value
            previous = block
        try:
            bars = self.board_source.fetch_history(sector, now)
        except SourceError as exc:
            with self._lock:
                if previous is not None and previous.value is not None:
                    self._history_blocks[sector] = self._mark_failure(
                        previous, "gateway.market_bars", now, str(exc)
                    )
                    return previous.value
                self._history_blocks[sector] = Block(
                    source="gateway.market_bars", fetched_at=now, reason=str(exc)
                )
            return {"ret_5d_pct": None, "ret_20d_pct": None}
        returns = compute_returns(bars, now.date(), include_today=now.time() >= time(15, 0))
        block = Block(
            value=returns,
            as_of=now,
            fetched_at=now,
            source="gateway.market_bars",
            stale=False,
        )
        with self._lock:
            self._history_blocks[sector] = block
            self._history_returns[sector] = returns
        self._persist(f"{HISTORY_PREFIX}{sector}", block, returns)
        return returns

    def ensure_trend(self, sector: str, now: datetime) -> tuple[list[TrendPoint], Optional[str]]:
        with self._lock:
            block = self._trend_blocks.get(sector)
            if (
                block is not None
                and block.fetched_at is not None
                and (now - block.fetched_at).total_seconds() < 30.0
            ):
                return list(block.value or []), block.reason
            previous = block
        try:
            points, _pre_close = self.board_source.fetch_trend(sector, now)
        except SourceError as exc:
            with self._lock:
                if previous is not None and previous.value is not None:
                    self._trend_blocks[sector] = self._mark_failure(
                        previous, "gateway", now, str(exc)
                    )
                    return list(previous.value or []), str(exc)
                self._trend_blocks[sector] = Block(
                    source="gateway.market_sectors", fetched_at=now, reason=str(exc)
                )
            return [], str(exc)
        block = Block(
            value=points,
            as_of=points[-1].t if points else now,
            fetched_at=now,
            source="gateway",
            stale=False,
        )
        with self._lock:
            self._trend_blocks[sector] = block
        self._persist(
            f"{TREND_PREFIX}{sector}",
            block,
            [
                {
                    "t": fmt_iso(point.t),
                    "price": point.price,
                    "change_pct": point.change_pct,
                }
                for point in points
            ],
        )
        return points, None

    def _market_amount(self) -> Optional[float]:
        with self._lock:
            block = self._index_block
            quotes = block.value or {}
        sh = quotes.get("000001.SH")
        sz = quotes.get("399001.SZ")
        if sh is None or sz is None or sh.amount_yuan is None or sz.amount_yuan is None:
            return None
        return sh.amount_yuan + sz.amount_yuan

    def _record_day_stats(self, now: datetime) -> None:
        """Persist today's market amount / limit-up count for next-day comparison."""
        if self._trading_state == "pre_open" or not self.calendar.is_trading_day(now):
            return
        with self._lock:
            breadth_block = self._breadth_block
            pool_block = self._pool_block
            breadth = breadth_block.value
            pool = pool_block.value
        amount = breadth.amount_yuan if breadth is not None else None
        if breadth_block.fetched_at is None or breadth_block.fetched_at.date() != now.date():
            amount = None
        limit_up = pool.limit_up if pool is not None else None
        limit_down = pool.limit_down if pool is not None else None
        broken = pool.broken if pool is not None else None
        max_streak = pool.max_streak if pool is not None else None
        if pool_block.fetched_at is None or pool_block.fetched_at.date() != now.date():
            limit_up = None
            limit_down = None
            broken = None
            max_streak = None
        if (
            amount is None
            and limit_up is None
            and limit_down is None
            and broken is None
            and max_streak is None
        ):
            return
        try:
            self.store.save_day_stats(
                now.date(),
                amount_yuan=amount,
                limit_up=limit_up,
                limit_down=limit_down,
                broken=broken,
                max_streak=max_streak,
                updated_at=now,
            )
        except Exception:  # noqa: BLE001 - a snapshot failure must not break polling
            logger.exception("保存日快照失败")

    def _previous_day_stats(self, now: datetime) -> Optional[dict[str, Any]]:
        try:
            return self.store.previous_day_stats(now.date())
        except Exception:  # noqa: BLE001 - summary degrades without a baseline
            logger.exception("读取上一交易日快照失败")
            return None

    @staticmethod
    def _stock_code_key(code: Any) -> str:
        return str(code or "").strip().split(".", 1)[0]

    def _sector_member_codes(self, sector: str) -> Optional[set[str]]:
        with self._lock:
            block = self._member_blocks.get(sector)
        if block is None or not block.value:
            return None
        return {self._stock_code_key(row.code) for row in block.value if row.code}

    def _sector_limit_counts(
        self, now: datetime
    ) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
        """Intersect member code sets with the limit-up / broken pool codes.

        A stock can belong to several boards; it is counted once in every board
        that lists it and never summed across boards.  Sectors with no usable
        member set stay ``None`` and get a reason instead of an invented zero.
        """
        with self._lock:
            pool_block = self._pool_block
            pool = pool_block.value
            quotes = list(self._board_block.value or [])
        zt_codes = {
            self._stock_code_key(code) for code in (pool.zt_codes if pool is not None else ())
        }
        zb_codes = {
            self._stock_code_key(code) for code in (pool.zb_codes if pool is not None else ())
        }
        zt_available = pool is not None and pool.limit_up is not None
        zb_available = pool is not None and pool.broken is not None
        zt_counts: dict[str, int] = {}
        zb_counts: dict[str, int] = {}
        reasons: dict[str, str] = {}
        for quote in quotes:
            codes = self._sector_member_codes(quote.code)
            if codes is None:
                reasons[quote.code] = "行业成分不可用，无法按代码归属涨停/炸板"
                continue
            if zt_available:
                zt_counts[quote.code] = len(codes & zt_codes)
            else:
                reasons[quote.code] = (
                    pool.reason if pool is not None and pool.reason else "涨停池不可用"
                )
            if zb_available:
                zb_counts[quote.code] = len(codes & zb_codes)
        return zt_counts, zb_counts, reasons

    def _record_sector_zt(self, now: datetime) -> None:
        with self._lock:
            if self._board_block.fallback:
                return
        counts, _broken, _reasons = self._sector_limit_counts(now)
        if not counts:
            return
        with self._lock:
            self._sector_zt_history.append((now, dict(counts)))

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------
    def evaluate(self, now: Optional[datetime] = None) -> list[AlertDraft]:
        moment = (now or self.now()).astimezone(CN_TZ)
        self._record_ranks(moment)
        self._record_sector_zt(moment)
        view = self.build_view(moment)
        recent = self.store.count_alerts_since(moment - timedelta(hours=1))
        drafts = self.evaluator.evaluate(view, recent_alert_count=recent)
        for draft in drafts:
            self.store.insert_alert(
                ts=moment,
                rule_id=draft.rule_id,
                object_type=draft.object_type,
                object_code=draft.object_code,
                object_name=draft.object_name,
                severity=draft.severity,
                title=draft.title,
                detail=draft.detail,
                payload=draft.payload,
            )
        return drafts

    def _record_ranks(self, now: datetime) -> None:
        with self._lock:
            quotes = list(self._board_block.value or [])
        if not quotes:
            return
        ranks = metrics.rank_desc({quote.code: quote.change_pct for quote in quotes})
        with self._lock:
            self._rank_history.append((now, ranks))

    def build_view(self, now: datetime) -> MarketView:
        with self._lock:
            index_block = self._index_block
            stock_block = self._stock_block
            board_block = self._board_block
            breadth_block = self._breadth_block
            indexes = dict(index_block.value or {})
            stocks = dict(stock_block.value or {})
            board_quotes = list(board_block.value or [])
            breadth = breadth_block.value
        if self._stale("index", index_block, now):
            indexes = {}
        if self._stale("industry", board_block, now):
            board_quotes = []
        if self._stale("breadth", breadth_block, now):
            breadth = None
        ranks = metrics.rank_desc({quote.code: quote.change_pct for quote in board_quotes})
        ranks_30m = self._ranks_at(now - timedelta(minutes=30), now)
        zt_30m = self._zt_at(now - timedelta(minutes=30), now)
        zt_counts, broken_counts, _count_reasons = self._sector_limit_counts(now)
        hs300 = indexes.get("000300.SH")
        hs300_change = hs300.change_pct if hs300 is not None else None
        sector_rows: list[SectorView] = []
        for quote in board_quotes:
            member_count = quote.member_count
            sector_rows.append(
                SectorView(
                    code=quote.code,
                    name=quote.name,
                    change_pct=quote.change_pct,
                    amount_yuan=quote.amount_yuan,
                    up_ratio=metrics.up_ratio(quote.up, quote.down),
                    member_count=member_count,
                    rank=ranks.get(quote.code),
                    rank_30m_ago=ranks_30m.get(quote.code),
                    limit_up_count=zt_counts.get(quote.code),
                    limit_up_30m_ago=(zt_30m or {}).get(quote.code),
                    broken_count=broken_counts.get(quote.code),
                    rel_300_pct=metrics.rel_300_pct(quote.change_pct, hs300_change),
                    small=metrics.small_sector(member_count),
                )
            )
        up_ratio_30m = self._breadth_ratio_at(
            now - timedelta(minutes=30), now, breadth.source if breadth is not None else None
        )
        index_vr = {
            code: self._volume_ratio(f"idx:{code}", quote.amount_yuan, now)
            for code, quote in indexes.items()
        }
        stock_vr = {
            code: self._volume_ratio(f"stk:{code}", quote.amount_yuan, now)
            for code, quote in stocks.items()
        }
        with self._lock:
            stock_history = dict(self._stock_history)
            sector_history = dict(self._sector_change_history)
        stock_change_30m = {
            code: self._value_at(series, now - timedelta(minutes=30), now, 150.0)
            for code, series in stock_history.items()
        }
        sector_change_30m = {
            code: self._value_at(series, now - timedelta(minutes=30), now, 150.0)
            for code, series in sector_history.items()
        }
        return MarketView(
            now=now,
            indexes=indexes,
            index_volume_ratios=index_vr,
            breadth=breadth,
            breadth_up_ratio_30m_ago=up_ratio_30m,
            sectors=sector_rows,
            stocks=stocks,
            stock_volume_ratios=stock_vr,
            stock_change_30m_ago=stock_change_30m,
            sector_change_30m_ago=sector_change_30m,
            stock_sector=self.store.member_sector_map(now),
            watchlist=self.watchlist,
            sector_fallback=board_block.fallback,
        )

    def _volume_ratio(self, key: str, amount: Optional[float], now: datetime) -> Optional[float]:
        baseline, count = self.store.mean_daily_amount(key, now.date(), 5)
        if count == 0 and ":" in key:
            baseline, count = self.store.mean_daily_amount(key.split(":", 1)[1], now.date(), 5)
        if count == 0:
            return None
        return metrics.volume_ratio(amount, baseline, metrics.time_fraction(now))

    def _ranks_at(self, target: datetime, now: datetime) -> dict[str, int]:
        with self._lock:
            items = list(self._rank_history)
        for stamp, ranks in reversed(items):
            if stamp <= target:
                if (target - stamp).total_seconds() <= 150.0:
                    return ranks
                return {}
        return {}

    def _zt_at(self, target: datetime, now: datetime) -> Optional[dict[str, int]]:
        with self._lock:
            items = list(self._sector_zt_history)
        tolerance = max(180.0, self.config.polling.members_seconds * 1.5)
        merged: dict[str, int] = {}
        found = False
        for stamp, counts in reversed(items):
            if stamp <= target and (target - stamp).total_seconds() <= tolerance:
                found = True
                for code, value in counts.items():
                    merged.setdefault(code, value)
            elif stamp < target - timedelta(seconds=tolerance):
                break
        return merged if found else None

    def _breadth_ratio_at(
        self, target: datetime, now: datetime, source: Optional[str]
    ) -> Optional[float]:
        """R2's 30-minute drop may only compare two points from the same source."""
        if source is None:
            return None
        with self._lock:
            snapshot = list(self._breadth_history)
        for stamp, value, point_source in reversed(snapshot):
            if point_source != source:
                continue
            if stamp <= target:
                if (target - stamp).total_seconds() <= 150.0:
                    return value
                return None
        return None

    def _value_at(
        self,
        series: "deque[tuple[datetime, float]]",
        target: datetime,
        now: datetime,
        tolerance: float,
    ) -> Optional[float]:
        with self._lock:
            snapshot = list(series)
        for stamp, value in reversed(snapshot):
            if stamp <= target:
                if (target - stamp).total_seconds() <= tolerance:
                    return value
                return None
        return None

    # ------------------------------------------------------------------
    # v1.4 trading-day helpers, persistence and backfill
    # ------------------------------------------------------------------
    def _as_trading_day(self, day: date) -> bool:
        return self.calendar.is_trading_day(
            datetime.combine(day, time(12, 0), tzinfo=CN_TZ)
        )

    def _latest_trading_day(self, now: datetime) -> date:
        """Most recent day that already has (or just opened) a session."""
        cursor = now.date()
        if not (self._as_trading_day(cursor) and now.time() >= time(9, 30)):
            cursor -= timedelta(days=1)
        for _ in range(60):
            if self._as_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        return cursor

    def _trading_day_before(self, day: date) -> Optional[date]:
        cursor = day - timedelta(days=1)
        for _ in range(60):
            if self._as_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        return None

    def _last_trading_days(self, now: datetime, count: int) -> list[date]:
        days: list[date] = []
        cursor = self._latest_trading_day(now)
        for _ in range(count * 3 + 40):
            if self._as_trading_day(cursor):
                days.append(cursor)
                if len(days) >= count:
                    break
            cursor -= timedelta(days=1)
        return sorted(days)

    def _resolve_date(
        self, text: Optional[str], now: datetime
    ) -> tuple[Optional[date], Optional[dict[str, Any]]]:
        if text is None or not str(text).strip():
            return self._latest_trading_day(now), None
        raw = str(text).strip()
        if len(raw) != 10:
            return None, self._error("bad_request", "date 必须为 YYYY-MM-DD")
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None, self._error("bad_request", "date 必须为合法的 YYYY-MM-DD")
        if day > now.date():
            return None, self._error("bad_request", "date 不能是未来日期")
        if not self._as_trading_day(day):
            return None, self._error("not_trading_day", f"{raw} 不是交易日")
        return day, None

    @staticmethod
    def _pool_as_of(day: date, fetched_at: Optional[str]) -> Optional[str]:
        stamp = _stamp(fetched_at)
        if stamp is not None and stamp.date() == day:
            return fmt_iso(stamp)
        return fmt_iso(datetime.combine(day, time(15, 0), tzinfo=CN_TZ))

    def _ensure_pool_day(
        self, day: date, kind: str, now: datetime
    ) -> dict[str, Any]:
        """Read a persisted pool, otherwise fetch that one pool by date."""
        try:
            record = self.store.load_pool_day(day, kind)
        except Exception:  # noqa: BLE001 - a broken row is retried from the source
            logger.exception("读取池历史失败: %s %s", day, kind)
            record = None
        if record is not None:
            return record
        date_text = day.strftime("%Y%m%d")
        try:
            count, qdate, stocks = self.pool_source.fetch_pool(kind, date_text, now)
            if day == now.date() and qdate and qdate != date_text:
                raise SourceError("pool_stale", f"池日期 {qdate} 不是 {date_text}")
            rows = pools_calc.sort_pool_rows(pool_rows(stocks), kind)
            available = count > 0 and bool(rows)
            reason = None if available else "no_data_from_source"
            record = {
                "day": day.isoformat(),
                "kind": kind,
                "count": count,
                "rows": rows,
                "fetched_at": now.isoformat(),
                "available": available,
                "reason": reason,
            }
        except SourceError as exc:
            record = {
                "day": day.isoformat(),
                "kind": kind,
                "count": None,
                "rows": [],
                "fetched_at": now.isoformat(),
                "available": False,
                "reason": exc.code,
            }
        try:
            self.store.save_pool_day(
                day,
                kind,
                count=record.get("count"),
                rows=record.get("rows") or [],
                fetched_at=now,
                available=bool(record.get("available")),
                reason=record.get("reason"),
            )
        except Exception:  # noqa: BLE001 - the response still renders from memory
            logger.exception("保存现取的池失败: %s %s", day, kind)
        return record

    def _ensure_pool_day_full(self, day: date, now: datetime) -> dict[str, dict[str, Any]]:
        return {kind: self._ensure_pool_day(day, kind, now) for kind in pools_calc.POOL_KINDS}

    def backfill_state(self) -> dict[str, Any]:
        with self._backfill_lock:
            return dict(self._backfill_state)

    def _missing_backfill_days(self, now: datetime, days: int) -> list[date]:
        wanted = self._last_trading_days(now, days)
        missing: list[date] = []
        for day in wanted:
            try:
                kinds = self.store.pool_day_kinds(day)
            except Exception:  # noqa: BLE001 - treat an unreadable store as missing
                logger.exception("读取回补进度失败: %s", day)
                kinds = set()
            if not set(pools_calc.POOL_KINDS) <= kinds:
                missing.append(day)
        return sorted(missing, reverse=True)

    def start_backfill(
        self,
        *,
        days: int = BACKFILL_DAYS,
        background: bool = True,
        monotonic: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        min_interval: float = BACKFILL_MIN_INTERVAL,
    ) -> dict[str, Any]:
        """Backfill missing pool days once; never runs two passes at a time."""
        now = self.now()
        with self._backfill_lock:
            if self._backfill_state.get("running"):
                return dict(self._backfill_state)
        missing = self._missing_backfill_days(now, days)
        with self._backfill_lock:
            self._backfill_state = {
                "running": bool(missing),
                "done": 0,
                "total": len(missing),
                "failed": 0,
                "started_at": now.isoformat() if missing else None,
                "finished_at": None if missing else now.isoformat(),
            }
            if not missing:
                return dict(self._backfill_state)
        if not background:
            self._run_backfill(
                missing,
                now,
                monotonic=monotonic,
                sleep=sleep,
                min_interval=min_interval,
            )
            return self.backfill_state()
        thread = threading.Thread(
            target=self._run_backfill,
            args=(missing, now),
            kwargs={"min_interval": min_interval},
            name="market-watch-backfill",
            daemon=True,
        )
        with self._backfill_lock:
            self._backfill_thread = thread
            self._backfill_state["running"] = True
        thread.start()
        return self.backfill_state()

    def _run_backfill(
        self,
        days: list[date],
        now: datetime,
        *,
        monotonic: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        min_interval: float = BACKFILL_MIN_INTERVAL,
    ) -> None:
        clock = monotonic or _time.monotonic
        sleeper = sleep or _time.sleep
        last: Optional[float] = None
        failed = 0
        try:
            for day in days:
                if self._stopped.is_set():
                    break
                date_text = day.strftime("%Y%m%d")
                day_failed = False
                for kind in pools_calc.POOL_KINDS:
                    if self._stopped.is_set():
                        break
                    wait = 0.0 if last is None else min_interval - (clock() - last)
                    if wait > 0:
                        sleeper(wait)
                    last = clock()
                    try:
                        count, qdate, stocks = self.pool_source.fetch_pool(
                            kind, date_text, now, cache_ttl=0.0
                        )
                        if day == now.date() and qdate and qdate != date_text:
                            raise SourceError("pool_stale", f"池日期 {qdate} 不是 {date_text}")
                        rows = pools_calc.sort_pool_rows(pool_rows(stocks), kind)
                        available = count > 0 and bool(rows)
                        self.store.save_pool_day(
                            day,
                            kind,
                            count=count,
                            rows=rows,
                            fetched_at=self.now(),
                            available=available,
                            reason=None if available else "no_data_from_source",
                        )
                    except SourceError as exc:
                        day_failed = True
                        try:
                            self.store.save_pool_day(
                                day,
                                kind,
                                count=None,
                                rows=[],
                                fetched_at=self.now(),
                                available=False,
                                reason=exc.code,
                            )
                        except Exception:  # noqa: BLE001 - keep walking the remaining days
                            logger.exception("回补失败日期落库失败: %s %s", day, kind)
                    except Exception:  # noqa: BLE001 - one bad day must not stop the pass
                        day_failed = True
                        logger.exception("回补池失败: %s %s", day, kind)
                if day_failed:
                    failed += 1
                with self._backfill_lock:
                    self._backfill_state["done"] = int(self._backfill_state.get("done", 0)) + 1
                    self._backfill_state["failed"] = failed
        finally:
            with self._backfill_lock:
                self._backfill_state["running"] = False
                self._backfill_state["finished_at"] = self.now().isoformat()

    # ------------------------------------------------------------------
    # v1.4 HTTP payloads
    # ------------------------------------------------------------------
    def pool_dict(
        self,
        kind: str = "zt",
        date_text: Optional[str] = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if kind not in pools_calc.POOL_KINDS:
            return self._error("bad_request", "kind 只支持 zt/zb/dt")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= POOL_LIMIT_MAX:
            return self._error("bad_request", f"limit 必须是 1–{POOL_LIMIT_MAX} 的整数")
        now = self.now()
        day, error = self._resolve_date(date_text, now)
        if error is not None:
            return error
        assert day is not None
        record = self._ensure_pool_day(day, kind, now)
        rows = pools_calc.sort_pool_rows(record.get("rows") or [], kind)[:limit]
        with self._lock:
            state = self._trading_state
        fetched = _stamp(record.get("fetched_at"))
        stale = False
        if day == now.date() and state not in FROZEN_STATES and fetched is not None:
            stale = (now - fetched).total_seconds() > self.config.polling.stale_after.get(
                "limit_pool", 150.0
            )
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": self._pool_as_of(day, record.get("fetched_at")),
            "date": day.isoformat(),
            "kind": kind,
            "count": record.get("count") if record.get("count") is not None else len(rows),
            "rows": rows,
            "definition": POOL_DEFINITION,
            "source": "gateway.market_limit_pool",
            "stale": stale,
        }
        if not record.get("available"):
            payload["reason"] = record.get("reason") or "no_data_from_source"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    def pool_ladder_dict(self, date_text: Optional[str] = None) -> dict[str, Any]:
        now = self.now()
        day, error = self._resolve_date(date_text, now)
        if error is not None:
            return error
        assert day is not None
        record = self._ensure_pool_day(day, "zt", now)
        if not record.get("available"):
            return {
                "ok": True,
                "date": day.isoformat(),
                "max_streak": None,
                "tiers": [],
                "first_board_count": None,
                "definition": POOL_LADDER_DEFINITION,
                "source": "gateway.market_limit_pool",
                "reason": record.get("reason") or "no_data_from_source",
            }
        ladder = pools_calc.ladder_payload(record.get("rows") or [])
        payload: dict[str, Any] = {
            "ok": True,
            "date": day.isoformat(),
            "max_streak": ladder["max_streak"],
            "tiers": ladder["tiers"],
            "first_board_count": ladder["first_board_count"],
            "definition": POOL_LADDER_DEFINITION,
            "source": "gateway.market_limit_pool",
        }
        return payload

    def _stored_pool(self, day: date, kind: str) -> Optional[dict[str, Any]]:
        try:
            return self.store.load_pool_day(day, kind)
        except Exception:  # noqa: BLE001 - history degrades to "not backfilled"
            logger.exception("读取池历史失败: %s %s", day, kind)
            return None

    def pool_history_dict(self, days: int = 20) -> dict[str, Any]:
        if (
            isinstance(days, bool)
            or not isinstance(days, int)
            or not POOL_HISTORY_DAYS[0] <= days <= POOL_HISTORY_DAYS[1]
        ):
            return self._error(
                "bad_request", f"days 必须是 {POOL_HISTORY_DAYS[0]}–{POOL_HISTORY_DAYS[1]} 的整数"
            )
        now = self.now()
        wanted = self._last_trading_days(now, days)
        rows: list[dict[str, Any]] = []
        first_previous = self._trading_day_before(wanted[0]) if wanted else None
        previous: Optional[dict[str, dict[str, Any]]] = (
            {kind: self._stored_pool(first_previous, kind) for kind in pools_calc.POOL_KINDS}
            if first_previous is not None
            else None
        )
        for day in wanted:
            current = {kind: self._stored_pool(day, kind) for kind in pools_calc.POOL_KINDS}
            reasons: list[str] = []
            for kind in pools_calc.POOL_KINDS:
                record = current.get(kind)
                if record is None:
                    reasons.append(f"{kind}:尚未回补")
                elif not record.get("available"):
                    reasons.append(f"{kind}:{record.get('reason') or 'no_data_from_source'}")
            available = not reasons
            zt_rows = (current.get("zt") or {}).get("rows") or []
            zb_rows = (current.get("zb") or {}).get("rows") or []
            zt_count = (current.get("zt") or {}).get("count")
            zb_count = (current.get("zb") or {}).get("count")
            dt_count = (current.get("dt") or {}).get("count")
            streaks = [row.get("streak") for row in zt_rows if isinstance(row.get("streak"), int)]
            promotions: dict[str, Optional[float]] = {
                "promote_1to2_pct": None,
                "promote_2to3_pct": None,
                "promote_3up_pct": None,
            }
            previous_zt = (previous or {}).get("zt") if previous is not None else None
            if previous_zt is not None and previous_zt.get("available"):
                previous_rows = previous_zt.get("rows") or []
                promotions["promote_1to2_pct"] = pools_calc.promotion_pct(
                    previous_rows, zt_rows, "1to2"
                )
                promotions["promote_2to3_pct"] = pools_calc.promotion_pct(
                    previous_rows, zt_rows, "2to3"
                )
                promotions["promote_3up_pct"] = pools_calc.promotion_pct(
                    previous_rows, zt_rows, "3up"
                )
            row: dict[str, Any] = {
                "date": day.isoformat(),
                "zt": zt_count if available else None,
                "dt": dt_count if available else None,
                "zb": zb_count if available else None,
                "seal_ratio_pct": (
                    pools_calc.seal_ratio_pct(zt_count, zb_count) if available else None
                ),
                "max_streak": max(streaks) if available and streaks else (
                    0 if available else None
                ),
                **promotions,
                "available": available,
            }
            if not available:
                row["reason"] = "；".join(dict.fromkeys(reasons))
            rows.append(row)
            previous = current
        return {
            "ok": True,
            "as_of": fmt_iso(now),
            "days": rows,
            "backfill": self.backfill_state(),
            "definition": POOL_HISTORY_DEFINITION,
            "source": "gateway.market_limit_pool+sqlite",
        }

    def pool_by_industry_dict(self, date_text: Optional[str] = None) -> dict[str, Any]:
        now = self.now()
        day, error = self._resolve_date(date_text, now)
        if error is not None:
            return error
        assert day is not None
        records = {kind: self._ensure_pool_day(day, kind, now) for kind in ("zt", "zb")}
        reasons = []
        for kind, record in records.items():
            if not record.get("available"):
                reasons.append(f"{kind}:{record.get('reason') or 'no_data_from_source'}")
        rows = pools_calc.by_industry(
            records["zt"].get("rows") or [], records["zb"].get("rows") or []
        )
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": self._pool_as_of(day, records["zt"].get("fetched_at")),
            "date": day.isoformat(),
            "rows": rows,
            "definition": BY_INDUSTRY_DEFINITION,
            "source": "gateway.market_limit_pool",
        }
        if reasons:
            payload["reason"] = "；".join(dict.fromkeys(reasons))
        return payload

    def pool_yesterday_dict(self) -> dict[str, Any]:
        now = self.now()
        with self._lock:
            state = self._trading_state
        if state == "pre_open":
            return {
                "ok": True,
                "date": now.date().isoformat(),
                "prev_date": None,
                "avg_open_pct": None,
                "avg_high_pct": None,
                "avg_close_pct": None,
                "win_ratio_pct": None,
                "rows": [],
                "definition": YESTERDAY_DEFINITION,
                "source": "gateway.market_limit_pool+gateway.market_quote",
                "reason": "今日尚未开盘，无今日快照",
            }
        target = self._latest_trading_day(now)
        previous = self._trading_day_before(target)
        if previous is None:
            return {
                "ok": True,
                "date": target.isoformat(),
                "prev_date": None,
                "avg_open_pct": None,
                "avg_high_pct": None,
                "avg_close_pct": None,
                "win_ratio_pct": None,
                "rows": [],
                "definition": YESTERDAY_DEFINITION,
                "source": "gateway.market_limit_pool+gateway.market_quote",
                "reason": "找不到上一交易日",
            }
        cached = self._yesterday_cache
        if cached is not None and (now - cached[0]).total_seconds() < YESTERDAY_TTL_SECONDS:
            return cached[1]
        record = self._ensure_pool_day(previous, "zt", now)
        if not record.get("available"):
            payload = {
                "ok": True,
                "date": target.isoformat(),
                "prev_date": previous.isoformat(),
                "avg_open_pct": None,
                "avg_high_pct": None,
                "avg_close_pct": None,
                "win_ratio_pct": None,
                "rows": [],
                "definition": YESTERDAY_DEFINITION,
                "source": "gateway.market_limit_pool+gateway.market_quote",
                "reason": f"上一交易日涨停池不可用: {record.get('reason') or 'no_data_from_source'}",
            }
            with self._lock:
                self._yesterday_cache = (now, payload)
            return payload
        previous_rows = record.get("rows") or []
        codes = [str(row.get("code")) for row in previous_rows if row.get("code")]
        try:
            quotes = self.tencent.fetch_stock_rows(codes, now) if codes else {}
        except SourceError as exc:
            quotes = {}
            reason = f"腾讯快照不可用: {exc.code}"
        else:
            reason = None
        result = pools_calc.yesterday_payload(previous_rows, quotes)
        payload = {
            "ok": True,
            "as_of": fmt_iso(now),
            "date": target.isoformat(),
            "prev_date": previous.isoformat(),
            **result,
            "definition": YESTERDAY_DEFINITION,
            "source": "gateway.market_limit_pool+gateway.market_quote",
            "fetched_at": fmt_iso(now),
            "stale": False,
        }
        if not result["rows"]:
            payload["reason"] = reason or "取不到昨日涨停股的今日快照"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        with self._lock:
            self._yesterday_cache = (now, payload)
        return payload

    def breadth_series_dict(self, date_text: Optional[str] = None) -> dict[str, Any]:
        now = self.now()
        day, error = self._resolve_date(date_text, now)
        if error is not None:
            return error
        assert day is not None
        try:
            stored = self.store.load_breadth_series(day)
        except Exception:  # noqa: BLE001 - a broken db degrades to empty points
            logger.exception("读取宽度序列失败: %s", day)
            stored = []
        points = [
            {
                "t": str(row.get("t")),
                "up": row.get("up"),
                "down": row.get("down"),
                "flat": row.get("flat"),
                "limit_up": row.get("limit_up"),
                "limit_down": row.get("limit_down"),
            }
            for row in stored
        ]
        expected = self._expected_breadth_minutes(day, now)
        present = {point["t"] for point in points}
        gaps = bool(expected) and (len(present & expected) < len(expected))
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(now),
            "date": day.isoformat(),
            "points": points,
            "gaps": gaps,
            "definition": BREADTH_SERIES_DEFINITION,
            "source": "gateway.market_overview+gateway.market_limit_pool",
        }
        if not points:
            payload["reason"] = "该交易日没有已采样的宽度点"
        return payload

    def _expected_breadth_minutes(self, day: date, now: datetime) -> set[str]:
        """Minute grid the engine should have sampled for ``day``."""
        with self._lock:
            state = self._trading_state
        if day > now.date():
            return set()
        if day < now.date():
            return set(self._session_minutes(240))
        if state in {"open", "lunch"}:
            minutes = now.hour * 60 + now.minute
            if state == "lunch" or minutes >= 13 * 60:
                count = 120 + min(120, max(0, minutes - 13 * 60))
            else:
                count = max(0, min(120, minutes - (9 * 60 + 30)))
            return set(self._session_minutes(count))
        if state == "closed":
            return set(self._session_minutes(240))
        return set()

    @staticmethod
    def _session_minutes(count: int) -> list[str]:
        labels: list[str] = []
        for minute in range(9 * 60 + 30, 11 * 60 + 30):
            labels.append(f"{minute // 60:02d}:{minute % 60:02d}")
        for minute in range(13 * 60, 15 * 60):
            labels.append(f"{minute // 60:02d}:{minute % 60:02d}")
        return labels[: max(0, min(count, len(labels)))]

    def themes_dict(
        self,
        kind: str = "concept",
        limit: int = 20,
        sort: str = "change",
    ) -> dict[str, Any]:
        if kind != "concept":
            return self._error("bad_request", "kind 只支持 concept")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 5 <= limit <= 30:
            return self._error("bad_request", "limit 必须是 5–30 的整数")
        if sort not in THEME_SORTS:
            return self._error("bad_request", "sort 只支持 change/amount")
        now = self.now()
        with self._lock:
            state = self._trading_state
        block = self._ensure_themes(sort, now, state=state, limit=limit)
        rows = pools_calc.theme_rows(
            [dataclass_to_dict(row) for row in (block.value or [])],
            limit,
            require_bk=not block.fallback,
        )
        stale = block.stale
        if state not in FROZEN_STATES:
            stale = block.stale or block.fetched_at is None or (
                now - block.fetched_at
            ).total_seconds() > THEMES_STALE_SECONDS
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(block.as_of or block.fetched_at),
            "kind": kind,
            "sort": sort,
            "rows": rows,
            "definition": SINA_THEME_DEFINITION if block.fallback else THEME_DEFINITION,
            "source": block.source or "gateway.market_sectors",
            "stale": bool(stale),
            "fallback": bool(block.fallback),
            "fallback_reason": block.fallback_reason,
            "taxonomy": "sina_concept" if block.fallback else "gateway_concept",
        }
        if not rows:
            payload["reason"] = block.reason or "当前过滤条件下没有概念板块"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    # ------------------------------------------------------------------
    # configuration hot reload
    # ------------------------------------------------------------------
    def maybe_reload_config(self) -> None:
        if self.config_path is None:
            return
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            return
        if self._config_mtime is not None and mtime == self._config_mtime:
            return
        try:
            new_config = load_config(self.config_path)
        except Exception as exc:  # noqa: BLE001 - any config failure keeps the old values
            self.config_reload_error = f"{type(exc).__name__}: {exc}"
            self._config_mtime = mtime
            logger.warning("配置热更新失败，保留旧配置: %s", exc)
            return
        with self._lock:
            self.config = new_config
            self.evaluator.update_config(new_config.rules)
            self.evaluator.configure_cap(new_config.limits.alert_max_per_hour)
            self.evaluator.configure_suppression(
                new_config.suppression.enabled,
                new_config.suppression.open_minutes,
                new_config.suppression.close_minutes,
            )
            self.watchlist = load_watchlist(new_config.watchlist_file)
        self.config_reload_error = None
        self._config_mtime = mtime
        logger.info("配置已热更新: %s", self.config_path)

    # ------------------------------------------------------------------
    # contract rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _health_block(blocks: Sequence[Optional[Block]], source: str) -> Block:
        present = [block for block in blocks if block is not None]
        if not present:
            return Block(source=source)
        fetched = [block.fetched_at for block in present if block.fetched_at is not None]
        stamps = [block.as_of for block in present if block.as_of is not None]
        reasons = [block.reason for block in present if block.reason]
        incomplete = len(present) < len(blocks) or any(block.value is None for block in present)
        reason = "；".join(dict.fromkeys(reasons)) if reasons else None
        if reason is None and incomplete:
            reason = "部分数据块不可用"
        return Block(
            value=present,
            as_of=max(stamps) if stamps else None,
            fetched_at=max(fetched) if fetched else None,
            source=source,
            reason=reason,
            fallback=any(block.fallback for block in present),
            fallback_reason=next(
                (block.fallback_reason for block in present if block.fallback_reason), None
            ),
        )

    def _block_info(
        self,
        block: Block,
        now: datetime,
        client_health: dict[str, Any],
        client_name: str,
        *,
        primary: Optional[str] = None,
        fallback_source: Optional[str] = None,
    ) -> dict[str, Any]:
        info = dict(client_health.get(client_name, {"ok": True, "age_s": None}))
        if block.fetched_at is None and block.value is None:
            info["ok"] = False
            info.setdefault("last_error", "尚未取数")
        if block.reason:
            info["ok"] = False
            info["last_error"] = block.reason
        elif block.fetched_at is not None:
            info["ok"] = True
            info["last_error"] = None
        info["age_s"] = (
            None
            if block.fetched_at is None
            else round((now - block.fetched_at).total_seconds(), 1)
        )
        info["primary"] = primary or client_name
        info["fallback_source"] = fallback_source
        info["active"] = (
            "none"
            if info["ok"] is False
            else ("fallback" if block.fallback else "primary")
        )
        info["fallback"] = bool(block.fallback)
        info["fallback_reason"] = block.fallback_reason
        info.setdefault("last_error", None)
        if block.fallback and block.fallback_reason:
            info["last_error"] = block.fallback_reason
        return info

    def health_dict(self) -> dict[str, Any]:
        now = self.now()
        with self._lock:
            state = self._trading_state
            blocks = {
                "index": self._index_block,
                "breadth": self._breadth_block,
                "limit_pool": self._pool_block,
                "industry": self._board_block,
                "movers": self._health_block(
                    [self._movers_blocks.get(f"{kind}:0") for kind in MOVER_KINDS],
                    "gateway.market_movers",
                ),
                "flows": self._health_block(
                    [
                        self._flow_blocks.get("sector"),
                        self._flow_blocks.get("stock_in:0"),
                        self._flow_blocks.get("stock_out:0"),
                    ],
                    "gateway.market_fund_flow",
                ),
                "themes": self._theme_blocks.get("concept:change")
                or self._theme_blocks.get("concept:amount")
                or Block(source="gateway.market_sectors"),
                "daily_spark": self._health_block(
                    [self._daily_spark_blocks.get(code) for code in INDEX_CODES],
                    "gateway.market_bars",
                ),
            }
            row_count = len(self._board_block.value or [])
        sources: dict[str, Any] = {}
        for name, block in blocks.items():
            sources[name] = {
                "ok": block.fetched_at is not None and block.reason is None,
                "age_s": (
                    None
                    if block.fetched_at is None
                    else round((now - block.fetched_at).total_seconds(), 1)
                ),
                "primary": block.source or f"gateway.{name}",
                "last_error": block.reason,
                "fallback": bool(block.fallback),
                "fallback_reason": block.fallback_reason,
            }
        try:
            pool_summary = self.store.pool_day_summary()
        except Exception:  # noqa: BLE001 - health must always render
            logger.exception("读取池历史统计失败")
            pool_summary = {"days": 0, "last_day": None, "last_fetched_at": None, "available_rows": 0}
        last_pool_fetch = _stamp(pool_summary.get("last_fetched_at"))
        sources["pool_history"] = {
            "ok": bool(pool_summary.get("days")),
            "days": pool_summary.get("days", 0),
            "available_rows": pool_summary.get("available_rows", 0),
            "last_date": pool_summary.get("last_day"),
            "age_s": (
                None
                if last_pool_fetch is None
                else round((now - last_pool_fetch).total_seconds(), 1)
            ),
            "last_error": None if pool_summary.get("days") else "尚无池历史",
            "primary": "internal.pool_history",
        }
        try:
            breadth_summary = self.store.breadth_series_summary()
        except Exception:  # noqa: BLE001 - health must always render
            logger.exception("读取宽度序列统计失败")
            breadth_summary = {"days": 0, "points": 0, "last_day": None}
        sources["breadth_series"] = {
            "ok": bool(breadth_summary.get("points")),
            "days": breadth_summary.get("days", 0),
            "points": breadth_summary.get("points", 0),
            "last_date": breadth_summary.get("last_day"),
            "last_error": None if breadth_summary.get("points") else "尚无宽度分钟点",
            "primary": "internal.breadth_series",
        }
        suppressed = dict(self.evaluator.suppressed_counts())
        suppressed.update(
            {rule_id: "sector_taxonomy_changed" for rule_id in ("R3", "R4", "R5", "R6")}
        )
        gateway_health = self.gateway.health(now) if hasattr(self.gateway, "health") else {}
        payload = {
            "ok": True,
            "as_of": fmt_iso(now),
            "trading_state": state,
            "gateway": gateway_health,
            "sources": sources,
            "sector_universe": {
                "configured": 0,
                "valid": row_count,
                "source": "gateway.market_sectors",
                "taxonomy": "gateway_industry",
                "note": "行业分类改由网关提供（同花顺/新浪口径），不再使用东财 BK 代码",
            },
            "rules": {
                "enabled": self.evaluator.enabled_ids(),
                "suppressed": suppressed,
                "suppressed_counts": self.evaluator.suppressed_counts(),
                "suppressed_reasons": suppressed,
            },
            "limits": {
                "alerts": {
                    "max_per_hour": self.config.limits.alert_max_per_hour,
                    "suppressed_total": self.evaluator.suppressed_total,
                }
            },
            "calendar_status": self.calendar.status,
            "backfill": self.backfill_state(),
            "no_fallback": [
                "board_history",
                "board_trend",
                "board_members",
                "sector_codes",
                "limit_up_count",
            ],
        }
        if self.config_reload_error:
            payload["config_reload_error"] = self.config_reload_error
        return payload

    def overview_dict(self) -> dict[str, Any]:
        now = self.now()
        with self._lock:
            state = self._trading_state
            index_block = self._index_block
            breadth_block = self._breadth_block
            pool_block = self._pool_block
            quotes = dict(index_block.value or {})
        frozen = state in FROZEN_STATES
        index_rows = []
        for code in INDEX_CODES:
            quote = quotes.get(code)
            spark, spark_kind = self._spark_rows(code, now, state)
            if quote is None:
                index_rows.append(
                    {
                        "code": code,
                        "name": INDEX_NAMES[code],
                        "price": None,
                        "prev_close": None,
                        "change_pct": None,
                        "amount_yuan": None,
                        "volume_ratio": None,
                        "spark": spark,
                        "spark_kind": spark_kind,
                        "as_of": None,
                        "fetched_at": fmt_iso(index_block.fetched_at),
                        "source": "gateway.market_quote",
                        "stale": False,
                        "reason": index_block.reason or "指数数据不可用",
                    }
                )
                continue
            index_rows.append(
                {
                    "code": code,
                    "name": quote.name or INDEX_NAMES[code],
                    "price": quote.price,
                    "prev_close": quote.prev_close,
                    "change_pct": quote.change_pct,
                    "amount_yuan": quote.amount_yuan,
                    "volume_ratio": self._volume_ratio(f"idx:{code}", quote.amount_yuan, now),
                    "spark": spark,
                    "spark_kind": spark_kind,
                    "as_of": fmt_iso(quote.exch_time),
                    "fetched_at": fmt_iso(index_block.fetched_at),
                    "source": "gateway.market_quote",
                    "stale": False if frozen else self._stale("index", index_block, now),
                }
            )
        breadth = self._breadth_payload(now, state)
        conditions = self.evaluator.conditions
        risk_reasons: list[str] = []
        if conditions.get("R1"):
            risk_reasons.append("R1 指数放量下跌处于触发窗口")
        if conditions.get("R2"):
            risk_reasons.append("R2 宽度恶化/背离处于触发窗口")
        main_changes = [
            quotes.get("000001.SH").change_pct if quotes.get("000001.SH") else None,
            quotes.get("399001.SZ").change_pct if quotes.get("399001.SZ") else None,
            quotes.get("000300.SH").change_pct if quotes.get("000300.SH") else None,
        ]
        label, reasons = metrics.regime(
            breadth.get("up_ratio"),
            main_changes,
            risk_reasons,
        )
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(_max_dt([index_block.as_of, breadth_block.as_of], now)),
            "trading_state": state,
            "indexes": index_rows,
            "breadth": breadth,
            "regime": {"label": label, "reasons": reasons},
        }
        if frozen:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    def _breadth_payload(self, now: datetime, state: str) -> dict[str, Any]:
        with self._lock:
            block = self._breadth_block
            pool_block = self._pool_block
            breadth = block.value
            pool = pool_block.value
        if breadth is None:
            return {
                "up": None,
                "down": None,
                "flat": None,
                "up_ratio": None,
                "limit_up": None,
                "limit_down": None,
                "broken": None,
                "seal_ratio": None,
                "max_streak": None,
                "amount_yuan": None,
                "as_of": None,
                "fetched_at": fmt_iso(block.fetched_at),
                "source": block.source or "gateway.market_overview",
                "stale": False,
                "fallback": bool(block.fallback),
                "fallback_reason": block.fallback_reason,
                "reason": block.reason or "宽度数据不可用",
            }
        reasons = []
        if block.reason:
            reasons.append(block.reason)
        if pool is None:
            reasons.append(pool_block.reason or "涨停/炸板池不可用")
        stale = False if state in FROZEN_STATES else self._stale("breadth", block, now)
        row: dict[str, Any] = {
            "up": breadth.up,
            "down": breadth.down,
            "flat": breadth.flat,
            "up_ratio": breadth.up_ratio,
            "limit_up": pool.limit_up if pool else None,
            "limit_down": pool.limit_down if pool else None,
            "broken": pool.broken if pool else None,
            "seal_ratio": pool.seal_ratio if pool else None,
            "max_streak": pool.max_streak if pool else None,
            "amount_yuan": breadth.amount_yuan,
            "as_of": fmt_iso(breadth.as_of),
            "fetched_at": fmt_iso(breadth.fetched_at),
            "source": breadth.source,
            "stale": stale,
            "fallback": bool(block.fallback),
            "fallback_reason": block.fallback_reason,
        }
        if pool is not None and pool.reason:
            reasons.append(pool.reason)
        if reasons:
            row["reason"] = "；".join(dict.fromkeys(reasons))
        previous = self._previous_day_stats(now)
        if previous is not None:
            row["previous_day"] = {
                "day": previous.get("day"),
                "amount_yuan": previous.get("amount_yuan"),
                "limit_up": previous.get("limit_up"),
            }
        return row

    def movers_dict(
        self,
        kind: str = "gainers",
        limit: int = 10,
        *,
        include_st: bool = False,
        include_new: bool = False,
        include_bj: bool = False,
    ) -> dict[str, Any]:
        if kind not in MOVER_KINDS:
            return self._error("bad_request", f"kind 只支持 {'/'.join(MOVER_KINDS)}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 5 <= limit <= 20:
            return self._error("bad_request", "limit 必须是 5–20 的整数")
        now = self.now()
        with self._lock:
            state = self._trading_state
        block = self._ensure_movers(kind, now, include_bj=include_bj, state=state)
        selected = movers_calc.select_movers(
            list(block.value or []),
            kind,
            limit,
            include_st=include_st,
            include_new=include_new,
            include_bj=include_bj,
        )
        rows: list[dict[str, Any]] = []
        for rank, row in enumerate(selected, start=1):
            item = {
                "rank": rank,
                "code": row.code,
                "name": row.name,
                "price": row.price,
                "change_pct": row.change_pct,
                "amount_yuan": row.amount_yuan,
            }
            if row.turnover_pct is not None:
                item["turnover_pct"] = row.turnover_pct
            if row.industry:
                item["industry"] = row.industry
            rows.append(item)
        stale = block.stale
        if state not in FROZEN_STATES:
            stale = block.stale or block.fetched_at is None or (
                now - block.fetched_at
            ).total_seconds() > MOVERS_STALE_SECONDS
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(block.as_of or block.fetched_at),
            "kind": kind,
            "rows": rows,
            "filters": {
                "include_st": include_st,
                "include_new": include_new,
                "include_bj": include_bj,
            },
            "source": block.source or "gateway.market_sectors",
            "stale": bool(stale),
            "fallback": bool(block.fallback),
            "fallback_reason": block.fallback_reason,
        }
        if not rows:
            if block.reason:
                payload["reason"] = block.reason
            elif block.value:
                payload["reason"] = "当前过滤条件下没有可展示的股票"
            else:
                payload["reason"] = "榜单数据不可用"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    def flows_dict(
        self,
        kind: str = "sector_in",
        limit: int = 10,
        *,
        include_st: bool = False,
        include_new: bool = False,
        include_bj: bool = False,
    ) -> dict[str, Any]:
        if kind not in FLOW_KINDS:
            return self._error("bad_request", f"kind 只支持 {'/'.join(FLOW_KINDS)}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 5 <= limit <= 20:
            return self._error("bad_request", "limit 必须是 5–20 的整数")
        now = self.now()
        with self._lock:
            state = self._trading_state
        block = self._ensure_flow(kind, now, include_bj=include_bj, state=state)
        selected = flows_calc.select_flows(
            list(block.value or []),
            kind,
            limit,
            include_st=include_st,
            include_new=include_new,
            include_bj=include_bj,
        )
        rows: list[dict[str, Any]] = []
        for rank, row in enumerate(selected, start=1):
            rows.append(
                {
                    "rank": rank,
                    "code": row.code,
                    "name": row.name,
                    "main_net_yuan": row.main_net_yuan,
                    "main_net_pct": row.main_net_pct,
                    "change_pct": row.change_pct,
                    "amount_yuan": row.amount_yuan,
                }
            )
        stale = block.stale
        if state not in FROZEN_STATES:
            stale = block.stale or block.fetched_at is None or (
                now - block.fetched_at
            ).total_seconds() > FLOWS_STALE_SECONDS
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(block.as_of or block.fetched_at),
            "kind": kind,
            "rows": rows,
            "definition": (
                SINA_FLOW_DEFINITION if block.fallback else flows_calc.FLOW_DEFINITION
            ),
            "source": block.source or "gateway.market_sectors",
            "stale": bool(stale),
            "fallback": bool(block.fallback),
            "fallback_reason": block.fallback_reason,
        }
        if kind in flows_calc.SECTOR_KINDS:
            payload["taxonomy"] = (
                "gateway_industry"
            )
        if kind in flows_calc.STOCK_KINDS:
            payload["filters"] = {
                "include_st": include_st,
                "include_new": include_new,
                "include_bj": include_bj,
            }
        if not rows:
            if block.reason:
                payload["reason"] = block.reason
            elif block.value:
                payload["reason"] = "当前过滤条件下没有可展示的股票"
            else:
                payload["reason"] = "资金流数据不可用"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    def northbound_dict(self) -> dict[str, Any]:
        now = self.now()
        block = self._ensure_northbound(now)
        value = block.value if isinstance(block.value, dict) else None
        if value is None:
            return {
                "ok": True,
                "available": False,
                "reason": block.reason or "北向资金数据不可用",
            }
        if value.get("available"):
            return {
                "ok": True,
                "available": True,
                "net_yuan": value.get("net_yuan"),
                "as_of": value.get("as_of"),
            }
        return {
            "ok": True,
            "available": False,
            "reason": value.get("reason") or block.reason or "免费日内北向净流入源不可用",
        }

    def summary_dict(self) -> dict[str, Any]:
        now = self.now()
        overview = self.overview_dict()
        sectors = self.sectors_dict()
        movers = self.movers_dict("gainers", 10)
        previous = self._previous_day_stats(now)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            alerts = self.store.recent_alerts(day_start, 20)
        except Exception:  # noqa: BLE001 - summary must still render without alerts
            logger.exception("读取当日告警失败，摘要省略风险提示")
            alerts = []
        generated = summary_calc.build_summary(
            overview=overview,
            sectors=sectors,
            movers=movers,
            previous_day=previous,
            alerts=alerts,
        )
        payload: dict[str, Any] = {"ok": True, "as_of": fmt_iso(now)}
        payload.update(generated)
        return payload

    def _spark_rows(
        self, code: str, now: datetime, state: str
    ) -> tuple[list[dict[str, Any]], str]:
        """Intraday down-sample while trading; otherwise the last 30 daily closes."""
        with self._lock:
            series = list(self._spark.get(code, ()))
        today = [item for item in series if item[0].date() == now.date()]
        thinned = metrics.downsample(today, 120)
        intraday = [{"t": fmt_iso(stamp), "p": round(price, 4)} for stamp, price in thinned]
        if state in {"open", "lunch"} and intraday:
            return intraday, "intraday"
        daily = self._daily_spark_series(code)
        if daily:
            return daily, "daily"
        if state in FROZEN_STATES:
            return [], "daily"
        return intraday, "intraday" if intraday else "daily"

    def _daily_spark_series(self, code: str) -> list[dict[str, Any]]:
        with self._lock:
            block = self._daily_spark_blocks.get(code)
        bars = list(block.value or []) if block is not None else []
        if not bars:
            return []
        points = [
            (datetime.combine(bar.day, time(15, 0), tzinfo=CN_TZ), bar.close)
            for bar in bars[-DAILY_SPARK_POINTS:]
        ]
        return [{"t": fmt_iso(stamp), "p": round(price, 4)} for stamp, price in points]

    def _stale(self, key: str, block: Block, now: datetime) -> bool:
        if block.stale or block.fetched_at is None:
            return True
        age = (now - block.fetched_at).total_seconds()
        return age > self.config.polling.stale_after.get(key, 60.0)

    def _known_sector(self, code: str) -> Optional[SectorDef]:
        universe = self._sector_universe
        for item in universe:
            if item.code == code:
                return item
        with self._lock:
            quotes = list(self._board_block.value or [])
        for quote in quotes:
            if quote.code == code:
                return SectorDef(code=quote.code, name=quote.name)
        return None

    def sectors_dict(self, level: str = "sw1") -> dict[str, Any]:
        if level not in {"sw1", "industry"}:
            return self._error("invalid_level", f"暂不支持 level={level!r}，只支持 sw1/industry")
        now = self.now()
        with self._lock:
            state = self._trading_state
            block = self._board_block
            quotes = list(block.value or [])
            missing = list(self._sector_missing)
        market_amount = self._market_amount()
        ranks = metrics.rank_desc({quote.code: quote.change_pct for quote in quotes})
        ranks_30m = self._ranks_at(now - timedelta(minutes=30), now)
        if block.fallback:
            zt_30m: Optional[dict[str, int]] = {}
            zt_counts: dict[str, int] = {}
            zt_reasons: dict[str, str] = {}
        else:
            zt_30m = self._zt_at(now - timedelta(minutes=30), now)
            zt_counts, _broken, zt_reasons = self._sector_limit_counts(now)
        rows = [
            self._sector_row(
                quote, now, state, ranks, ranks_30m, zt_30m, market_amount, block,
                zt_counts, zt_reasons,
            )
            for quote in quotes
        ]
        if block.fallback:
            for row in rows:
                # The gateway taxonomy has no board code, constituents or
                # limit-pool attribution; up/down counts are kept when present.
                row["limit_up_count"] = None
                row["laggards"] = []
                row["source"] = block.source
                row.pop("reason", None)
                if row["member_count"] is None:
                    row["reason"] = SINA_INDUSTRY_NOTE
        rows.sort(
            key=lambda row: (
                -(row["change_pct"] if row["change_pct"] is not None else -1e9),
                row["code"],
            )
        )
        payload: dict[str, Any] = {
            "ok": True,
            "as_of": fmt_iso(block.as_of or now),
            "level": level,
            "source": block.source if block.fallback else "gateway.market_sectors",
            "rows": rows,
            "sort": "change_pct",
            "fallback": bool(block.fallback),
            "fallback_reason": block.fallback_reason,
            "taxonomy": "gateway_industry",
        }
        if block.fallback:
            payload["note"] = SINA_INDUSTRY_NOTE
            payload["taxonomy"] = "gateway_industry"
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        if not rows:
            payload["reason"] = block.reason or (
                f"行业清单校验未通过（{len(missing)} 个未匹配）" if missing else "板块数据不可用"
            )
        return payload

    def _sector_row(
        self,
        quote: BoardQuote,
        now: datetime,
        state: str,
        ranks: dict[str, int],
        ranks_30m: dict[str, int],
        zt_30m: Optional[dict[str, int]],
        market_amount: Optional[float],
        block: Block,
        zt_counts: dict[str, int],
        zt_reasons: dict[str, str],
    ) -> dict[str, Any]:
        member_count = quote.member_count
        up = quote.up
        down = quote.down
        limit_up = zt_counts.get(quote.code)
        leaders: list[dict[str, Any]] = []
        laggards: list[dict[str, Any]] = []
        if quote.leader_code:
            leaders.append(
                {
                    "code": to_exchange_code(quote.leader_code) or quote.leader_code,
                    "name": quote.leader_name or "",
                    "change_pct": quote.leader_change_pct,
                }
            )
        member_rows = self._fresh_members(quote.code, now)
        if member_rows:
            ordered = sorted(member_rows, key=lambda row: (-row.change_pct, row.code))
            laggards = [
                {"code": row.code, "name": row.name, "change_pct": row.change_pct}
                for row in reversed(ordered[-3:])
            ]
        rank_30m = ranks_30m.get(quote.code)
        row: dict[str, Any] = {
            "code": None if quote.code == quote.name else quote.code,
            "name": quote.name,
            "change_pct": quote.change_pct,
            "amount_yuan": quote.amount_yuan,
            "amount_share_ratio": metrics.amount_share_ratio(quote.amount_yuan, market_amount),
            "rel_300_pct": self._rel_300(quote.change_pct),
            "up_count": up,
            "down_count": down,
            "limit_up_count": limit_up,
            "member_count": member_count,
            "rank": ranks.get(quote.code),
            "rank_30m_ago": rank_30m,
            "rank_change_30m": metrics.rank_change(ranks.get(quote.code), rank_30m),
            "leaders": leaders,
            "laggards": laggards,
            "as_of": fmt_iso(quote.as_of),
            "fetched_at": fmt_iso(block.fetched_at),
            "source": "gateway.market_sectors",
            "stale": False if state in FROZEN_STATES else self._stale("industry", block, now),
        }
        if metrics.small_sector(member_count):
            row["small"] = True
        reasons = []
        if block.reason:
            reasons.append(block.reason)
        if member_count is None:
            reasons.append("成分家数不可用")
        if quote.change_pct is None:
            reasons.append("涨跌幅不可用")
        if quote.amount_yuan is None:
            reasons.append("成交额不可用")
        if limit_up is None:
            reasons.append(zt_reasons.get(quote.code, "涨停池无该行业代码归属"))
        if quote.leader_code and quote.leader_change_pct is None:
            reasons.append("领涨股涨跌幅不可用")
        if row["rel_300_pct"] is None:
            reasons.append("沪深300涨跌幅不可用")
        if row["amount_share_ratio"] is None:
            reasons.append("全市场成交额不可用")
        if reasons:
            row["reason"] = "；".join(reasons)
        return row

    def _rel_300(self, change_pct: Optional[float]) -> Optional[float]:
        with self._lock:
            block = self._index_block
            quotes = block.value or {}
        hs300 = quotes.get("000300.SH")
        if hs300 is None:
            return None
        return metrics.rel_300_pct(change_pct, hs300.change_pct)

    def sector_dict(self, code: str) -> dict[str, Any]:
        now = self.now()
        known = self._known_sector(code)
        if known is None:
            return self._error("unknown_sector", f"未知一级行业板块: {code}")
        with self._lock:
            state = self._trading_state
            block = self._board_block
            quotes = list(block.value or [])
        quote = next((item for item in quotes if item.code == code), None)
        if quote is None:
            return self._error("unknown_sector", f"未知一级行业板块: {code}")
        market_amount = self._market_amount()
        ranks = metrics.rank_desc({item.code: item.change_pct for item in quotes})
        ranks_30m = self._ranks_at(now - timedelta(minutes=30), now)
        zt_counts, _broken, zt_reasons = self._sector_limit_counts(now)
        row = self._sector_row(
            quote,
            now,
            state,
            ranks,
            ranks_30m,
            self._zt_at(now - timedelta(minutes=30), now),
            market_amount,
            block,
            zt_counts,
            zt_reasons,
        )
        returns = self.ensure_history(code, now)
        points, trend_reason = self.ensure_trend(code, now)
        series = [(point.t, point.change_pct) for point in points if point.change_pct is not None]
        thinned = metrics.downsample(series, 240)
        with self._lock:
            history_block = self._history_blocks.get(code)
        history = {
            "ret_5d_pct": returns.get("ret_5d_pct"),
            "ret_20d_pct": returns.get("ret_20d_pct"),
            "rank_5d": self._history_rank("ret_5d_pct", code),
            "rank_20d": self._history_rank("ret_20d_pct", code),
            "as_of": fmt_iso(history_block.fetched_at if history_block else None),
            "source": "gateway.market_sectors",
        }
        row["trend"] = [
            {"t": fmt_iso(stamp), "change_pct": round(value, 4)} for stamp, value in thinned
        ]
        row["history"] = history
        reasons = []
        if row.get("reason"):
            reasons.append(row["reason"])
        if history_block is not None and history_block.reason:
            history["reason"] = history_block.reason
            reasons.append(history_block.reason)
        if trend_reason:
            reasons.append(f"分时: {trend_reason}")
        if reasons:
            row["reason"] = "；".join(dict.fromkeys(reasons))
        payload = {"ok": True, "as_of": fmt_iso(block.as_of or now), "level": "industry"}
        payload.update(row)
        if state in FROZEN_STATES:
            payload["state_note"] = INDEX_STATE_NOTE
        return payload

    def _history_rank(self, key: str, code: str) -> Optional[int]:
        with self._lock:
            values = {
                sector: returns.get(key)
                for sector, returns in self._history_returns.items()
                if returns.get(key) is not None
            }
        if len(values) < 10 or code not in values:
            return None
        return metrics.rank_desc(values).get(code)

    def members_dict(self, code: str) -> dict[str, Any]:
        now = self.now()
        known = self._known_sector(code)
        if known is None:
            return self._error("unknown_sector", f"未知一级行业板块: {code}")
        rows = self.ensure_members(code, now)
        if rows is None:
            with self._lock:
                block = self._member_blocks.get(code)
            return {
                "ok": True,
                "code": code,
                "name": known.name,
                "as_of": None,
                "rows": [],
                "reason": (block.reason if block else None) or "成分数据不可用",
            }
        payload_rows = []
        for row in rows[:100]:
            item = {
                "code": row.code,
                "name": row.name,
                "price": row.price,
                "change_pct": row.change_pct,
                "amount_yuan": row.amount_yuan,
                "limit_up": row.limit_up,
                "limit_down": row.limit_down,
            }
            if row.weight_pct is not None:
                item["weight_pct"] = row.weight_pct
            payload_rows.append(item)
        with self._lock:
            block = self._member_blocks.get(code)
        payload = {
            "ok": True,
            "code": code,
            "name": known.name,
            "as_of": fmt_iso(block.as_of if block else now),
            "fetched_at": fmt_iso(block.fetched_at if block else None),
            "source": "gateway.market_sectors",
            "stale": False if block is None else self._stale("members", block, now),
            "rows": payload_rows,
        }
        if block is not None and block.reason:
            payload["reason"] = block.reason
        return payload

    def alerts_dict(self, since_id: int = 0, limit: int = 50) -> dict[str, Any]:
        if since_id < 0:
            return self._error("invalid_param", "since_id 必须是非负整数")
        limit = max(0, min(int(limit), 200))
        rows = self.store.list_alerts(since_id=since_id, limit=limit)
        next_id = rows[-1]["id"] if rows else since_id
        return {"ok": True, "alerts": rows, "next_id": next_id}

    def rules_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "as_of": fmt_iso(self.now()),
            "rules": self.evaluator.payload(),
        }

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message}}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def run(self, stop: Optional[threading.Event] = None) -> None:
        event = stop or self._stopped
        while not event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the poller must survive one bad cycle
                logger.exception("轮询周期失败")
            event.wait(1.0)

    def stop(self) -> None:
        self._stopped.set()

