"""R1-R6 cross-sectional alert rules with confirm/cooldown/suppression/aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from .calc import metrics
from .config import RuleConfig
from .models import Breadth, IndexQuote, StockQuote

MAIN_INDEX_CODES = ("000001.SH", "399001.SZ", "000300.SH")


@dataclass(frozen=True)
class SectorView:
    code: str
    name: str
    change_pct: Optional[float]
    amount_yuan: Optional[float]
    up_ratio: Optional[float]
    member_count: Optional[int]
    rank: Optional[int]
    rank_30m_ago: Optional[int]
    limit_up_count: Optional[int]
    limit_up_30m_ago: Optional[int]
    rel_300_pct: Optional[float]
    broken_count: Optional[int] = None
    small: bool = False


@dataclass(frozen=True)
class MarketView:
    now: datetime
    indexes: dict[str, IndexQuote]
    index_volume_ratios: dict[str, Optional[float]]
    breadth: Optional[Breadth]
    breadth_up_ratio_30m_ago: Optional[float]
    sectors: Sequence[SectorView]
    stocks: dict[str, StockQuote]
    stock_volume_ratios: dict[str, Optional[float]]
    stock_change_30m_ago: dict[str, Optional[float]]
    sector_change_30m_ago: dict[str, Optional[float]]
    stock_sector: dict[str, str]
    watchlist: tuple[str, ...] = ()
    #: R3-R6 depend on board codes/constituents/limit attribution; they pause
    #: while the gateway industry taxonomy does not provide them.
    sector_fallback: bool = False

    def sector(self, code: str) -> Optional[SectorView]:
        for row in self.sectors:
            if row.code == code:
                return row
        return None


@dataclass(frozen=True)
class AlertDraft:
    rule_id: str
    object_type: str
    object_code: str
    object_name: str
    severity: str
    title: str
    detail: str
    payload: dict[str, Any]


@dataclass
class RuleState:
    armed: bool = True
    retreated: bool = False
    confirm_count: int = 0
    last_fired_at: Optional[datetime] = None
    suppressed: int = 0


@dataclass
class _Candidate:
    rule_id: str
    object_type: str
    object_code: str
    object_name: str
    condition: bool
    title: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def _pct(value: Optional[float], digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _ratio(value: Optional[float], digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


class RuleEvaluator:
    def __init__(self, rules: Sequence[RuleConfig]) -> None:
        self.rules: dict[str, RuleConfig] = {rule.id: rule for rule in rules}
        self.states: dict[tuple[str, str], RuleState] = {}
        self.last_rs: dict[str, float] = {}
        self.r5_direction: dict[str, str] = {}
        self.suppressed_total = 0
        self.conditions: dict[str, bool] = {}
        self.last_evaluated_at: Optional[datetime] = None

    # -- configuration ---------------------------------------------------
    def update_config(self, rules: Sequence[RuleConfig]) -> None:
        self.rules = {rule.id: rule for rule in rules}

    def enabled_ids(self) -> list[str]:
        return [rule.id for rule in self.rules.values() if rule.enabled]

    def payload(self) -> list[dict[str, Any]]:
        return [rule.as_dict() for rule in self.rules.values()]

    def _state(self, rule_id: str, key: str) -> RuleState:
        return self.states.setdefault((rule_id, key), RuleState())

    # -- evaluation ------------------------------------------------------
    def evaluate(self, view: MarketView, *, recent_alert_count: int = 0) -> list[AlertDraft]:
        candidates: list[_Candidate] = []
        if self._enabled("R1"):
            candidates.extend(self._r1(view))
        if self._enabled("R2"):
            candidates.extend(self._r2(view))
        if not view.sector_fallback:
            if self._enabled("R3"):
                candidates.extend(self._r3(view))
            if self._enabled("R4"):
                candidates.extend(self._r4(view))
            if self._enabled("R5"):
                candidates.extend(self._r5(view))
            if self._enabled("R6"):
                candidates.extend(self._r6(view))

        self.conditions = {
            "R1": any(item.condition for item in candidates if item.rule_id == "R1"),
            "R2": any(item.condition for item in candidates if item.rule_id == "R2"),
        }

        fired: list[_Candidate] = []
        by_rule: dict[str, list[_Candidate]] = {}
        for item in candidates:
            by_rule.setdefault(item.rule_id, []).append(item)

        for rule_id, rule in self.rules.items():
            if not rule.enabled:
                continue
            group = by_rule.get(rule_id, [])
            seen = {item.object_code for item in group}
            for (state_rule, key), state in list(self.states.items()):
                if state_rule == rule_id and key not in seen:
                    state.confirm_count = 0
                    if state.last_fired_at is None or view.now - state.last_fired_at >= timedelta(
                        minutes=rule.cooldown_minutes
                    ):
                        state.armed = True
            cooldown = timedelta(minutes=rule.cooldown_minutes)
            for item in group:
                state = self._state(rule_id, item.object_code)
                if item.condition:
                    state.confirm_count += 1
                    if (
                        not state.armed
                        and state.retreated
                        and (state.last_fired_at is None or view.now - state.last_fired_at >= cooldown)
                    ):
                        state.armed = True
                else:
                    state.confirm_count = 0
                    state.retreated = True
                    if state.last_fired_at is None or view.now - state.last_fired_at >= cooldown:
                        state.armed = True
                if not item.condition:
                    continue
                if state.confirm_count < rule.confirm:
                    continue
                if not state.armed:
                    continue
                if state.last_fired_at is not None and view.now - state.last_fired_at < cooldown:
                    continue
                fired.append(item)

        if not fired:
            self._update_rs(view)
            self.last_evaluated_at = view.now
            return []

        if self._suppressed(view.now):
            for item in fired:
                self._state(item.rule_id, item.object_code).suppressed += 1
                self.suppressed_total += 1
            self._update_rs(view)
            self.last_evaluated_at = view.now
            return []

        allowance = max(0, int(self._storm_cap()) - max(0, int(recent_alert_count)))
        drafts: list[AlertDraft] = []
        emitted: dict[str, list[_Candidate]] = {}
        for item in fired:
            if allowance <= 0:
                state = self._state(item.rule_id, item.object_code)
                state.suppressed += 1
                self.suppressed_total += 1
                continue
            allowance -= 1
            state = self._state(item.rule_id, item.object_code)
            state.last_fired_at = view.now
            state.armed = False
            state.retreated = False
            emitted.setdefault(item.rule_id, []).append(item)

        for rule_id, items in emitted.items():
            rule = self.rules[rule_id]
            first = items[0]
            objects = [
                {
                    "type": item.object_type,
                    "code": item.object_code,
                    "name": item.object_name,
                    "metrics": item.metrics,
                }
                for item in items
            ]
            if len(items) == 1:
                title = first.title
            else:
                title = f"{rule.name}：{len(items)} 个对象"
            detail = "；".join(item.detail for item in items)
            drafts.append(
                AlertDraft(
                    rule_id=rule_id,
                    object_type=first.object_type,
                    object_code=first.object_code,
                    object_name=first.object_name,
                    severity=rule.level,
                    title=title,
                    detail=detail,
                    payload={
                        "rule_id": rule_id,
                        "rule_name": rule.name,
                        "count": len(items),
                        "objects": objects,
                        "confirm_count": rule.confirm,
                        "cooldown_minutes": rule.cooldown_minutes,
                    },
                )
            )
        self._update_rs(view)
        self.last_evaluated_at = view.now
        return drafts

    def _enabled(self, rule_id: str) -> bool:
        rule = self.rules.get(rule_id)
        return bool(rule and rule.enabled)

    def _storm_cap(self) -> int:
        # The cap is injected through ``configure_cap`` so rules stay pure config.
        return getattr(self, "_alert_cap", 10)

    def configure_cap(self, cap: int) -> None:
        self._alert_cap = max(1, int(cap))

    def _suppressed(self, now: datetime) -> bool:
        window = getattr(self, "_suppression", None)
        if window is None:
            return False
        enabled, open_minutes, close_minutes = window
        if not enabled:
            return False
        from .calendar import in_alert_suppression

        return in_alert_suppression(
            now, open_minutes=open_minutes, close_minutes=close_minutes
        )

    def configure_suppression(self, enabled: bool, open_minutes: int, close_minutes: int) -> None:
        self._suppression = (enabled, open_minutes, close_minutes)

    # -- rules -----------------------------------------------------------
    def _r1(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R1"]
        params = rule.params
        items: list[_Candidate] = []
        for code, quote in view.indexes.items():
            vr = view.index_volume_ratios.get(code)
            condition = (
                quote.change_pct <= params["change_pct_max"]
                and vr is not None
                and vr >= params["volume_ratio_min"]
            )
            basis = "5日累计成交额×已交易分钟占比" if vr is not None else "缺少5日基线"
            items.append(
                _Candidate(
                    rule_id="R1",
                    object_type="index",
                    object_code=code,
                    object_name=quote.name,
                    condition=condition,
                    title=f"指数放量下跌：{quote.name} {_pct(quote.change_pct)}",
                    detail=(
                        f"{quote.name} 涨跌幅 {_pct(quote.change_pct)}，"
                        f"放量倍数 {_ratio(vr)}（{basis}）"
                    ),
                    metrics={
                        "change_pct": quote.change_pct,
                        "volume_ratio": vr,
                        "volume_ratio_basis": basis,
                        "amount_yuan": quote.amount_yuan,
                    },
                )
            )
        return items

    def _r2(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R2"]
        params = rule.params
        breadth = view.breadth
        if breadth is None or breadth.up_ratio is None:
            return []
        hs300 = view.indexes.get("000300.SH")
        hs300_change = hs300.change_pct if hs300 is not None else None
        drop = None
        if view.breadth_up_ratio_30m_ago is not None:
            # Positive = breadth deteriorated over the window.
            drop = view.breadth_up_ratio_30m_ago - breadth.up_ratio
        branch_weak = (
            breadth.up_ratio <= params["up_ratio_max"]
            and hs300_change is not None
            and hs300_change >= params["index_change_pct_min"]
        )
        branch_drop = drop is not None and drop >= params["up_ratio_drop_min"]
        return [
            _Candidate(
                rule_id="R2",
                object_type="index",
                object_code="000300.SH",
                object_name="市场宽度",
                condition=bool(branch_weak or branch_drop),
                title=f"宽度恶化/背离：上涨家数占比 {_ratio(breadth.up_ratio)}",
                detail=(
                    f"上涨家数占比 {_ratio(breadth.up_ratio)}，沪深300 "
                    f"{_pct(hs300_change)}，30分钟变化 "
                    f"{'—' if drop is None else f'{drop:+.2f}'}"
                ),
                metrics={
                    "up_ratio": breadth.up_ratio,
                    "up_ratio_30m_ago": view.breadth_up_ratio_30m_ago,
                    "up_ratio_drop": drop,
                    "hs300_change_pct": hs300_change,
                },
            )
        ]

    def _r3(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R3"]
        params = rule.params
        items: list[_Candidate] = []
        for row in view.sectors:
            improvement = metrics.rank_change(row.rank, row.rank_30m_ago)
            condition = bool(
                row.rank is not None
                and row.rank_30m_ago is not None
                and improvement is not None
                and row.rank <= params["rank_max"]
                and row.rank_30m_ago >= params["rank_before_min"]
                and improvement >= params["rank_improvement_min"]
                and row.change_pct is not None
                and row.change_pct >= params["change_pct_min"]
                and row.up_ratio is not None
                and row.up_ratio >= params["up_ratio_min"]
                and row.member_count is not None
                and row.member_count >= params["min_members"]
                and row.amount_yuan is not None
                and row.amount_yuan >= params["min_amount_yuan"]
            )
            items.append(
                _Candidate(
                    rule_id="R3",
                    object_type="sector",
                    object_code=row.code,
                    object_name=row.name,
                    condition=condition,
                    title=f"板块排名跃升：{row.name} 第{row.rank}名",
                    detail=(
                        f"{row.name} 排名 {row.rank_30m_ago}→{row.rank}"
                        f"（{'+' if (improvement or 0) >= 0 else ''}{improvement}），"
                        f"涨跌幅 {_pct(row.change_pct)}，上涨占比 {_ratio(row.up_ratio)}"
                    ),
                    metrics={
                        "rank": row.rank,
                        "rank_30m_ago": row.rank_30m_ago,
                        "rank_change": improvement,
                        "change_pct": row.change_pct,
                        "up_ratio": row.up_ratio,
                        "member_count": row.member_count,
                        "amount_yuan": row.amount_yuan,
                    },
                )
            )
        return items

    def _r4(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R4"]
        params = rule.params
        items: list[_Candidate] = []
        for row in view.sectors:
            increase = None
            if row.limit_up_count is not None and row.limit_up_30m_ago is not None:
                increase = row.limit_up_count - row.limit_up_30m_ago
            condition = bool(
                increase is not None
                and increase >= params["zt_increase_min"]
                and row.limit_up_count is not None
                and row.limit_up_count >= params["zt_min"]
                and row.up_ratio is not None
                and row.up_ratio >= params["up_ratio_min"]
                and row.member_count is not None
                and row.member_count >= params["min_members"]
                and row.amount_yuan is not None
                and row.amount_yuan >= params["min_amount_yuan"]
            )
            items.append(
                _Candidate(
                    rule_id="R4",
                    object_type="sector",
                    object_code=row.code,
                    object_name=row.name,
                    condition=condition,
                    title=f"板块涨停骤增：{row.name} 涨停 {row.limit_up_count} 家",
                    detail=(
                        f"{row.name} 涨停 {row.limit_up_30m_ago}→{row.limit_up_count} 家"
                        f"（30分钟 +{increase if increase is not None else '—'}），"
                        f"上涨占比 {_ratio(row.up_ratio)}"
                    ),
                    metrics={
                        "limit_up_count": row.limit_up_count,
                        "limit_up_30m_ago": row.limit_up_30m_ago,
                        "increase": increase,
                        "up_ratio": row.up_ratio,
                        "member_count": row.member_count,
                        "amount_yuan": row.amount_yuan,
                    },
                )
            )
        return items

    def _r5(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R5"]
        buffer = float(rule.params["buffer_pct"])
        hs300 = view.indexes.get("000300.SH")
        benchmark = hs300.change_pct if hs300 is not None else None
        items: list[_Candidate] = []
        for row in view.sectors:
            if benchmark is None or row.change_pct is None:
                continue
            current = row.change_pct - benchmark
            previous = self.last_rs.get(row.code)
            latch = self.r5_direction.get(row.code)
            if -buffer < current < buffer:
                latch = None
            elif current >= buffer:
                latch = "up"
            elif current <= -buffer:
                latch = "down"
            self.r5_direction[row.code] = latch or ""
            up_cross = latch == "up"
            down_cross = latch == "down"
            same_direction = (up_cross and row.change_pct > 0) or (down_cross and row.change_pct < 0)
            condition = bool(same_direction)
            direction = "上穿" if up_cross else "下穿" if down_cross else "未穿越"
            items.append(
                _Candidate(
                    rule_id="R5",
                    object_type="sector",
                    object_code=row.code,
                    object_name=row.name,
                    condition=condition,
                    title=f"板块相对强弱{direction}0轴：{row.name}",
                    detail=(
                        f"{row.name} 相对沪深300 {_pct(current)}，"
                        f"上一采样 {_pct(previous)}，缓冲 ±{buffer:.2f} 个百分点"
                    ),
                    metrics={
                        "rel_300_pct": current,
                        "previous_rel_300_pct": previous,
                        "buffer_pct": buffer,
                        "direction": direction,
                        "sector_change_pct": row.change_pct,
                        "hs300_change_pct": benchmark,
                    },
                )
            )
        return items

    def _r6(self, view: MarketView) -> list[_Candidate]:
        rule = self.rules["R6"]
        params = rule.params
        items: list[_Candidate] = []
        for code in view.watchlist:
            stock = view.stocks.get(code)
            if stock is None:
                continue
            if (
                metrics.is_st_stock(stock.name)
                or metrics.is_new_stock(stock.name)
                or metrics.is_b_share(code)
                or metrics.is_limit_up(stock.price, stock.limit_up)
                or metrics.is_limit_down(stock.price, stock.limit_down)
            ):
                continue
            sector_code = view.stock_sector.get(code)
            sector = view.sector(sector_code) if sector_code else None
            if sector is None or sector.change_pct is None:
                continue
            if sector.small or (
                sector.member_count is not None and sector.member_count < params["min_members"]
            ):
                continue
            stock_30 = view.stock_change_30m_ago.get(code)
            sector_30 = view.sector_change_30m_ago.get(sector.code)
            if stock_30 is None or sector_30 is None:
                continue
            divergence = (stock.change_pct - stock_30) - (sector.change_pct - sector_30)
            vr = view.stock_volume_ratios.get(code)
            condition = (
                divergence <= params["divergence_pct_max"]
                and vr is not None
                and vr >= params["volume_ratio_min"]
            )
            items.append(
                _Candidate(
                    rule_id="R6",
                    object_type="stock",
                    object_code=code,
                    object_name=stock.name,
                    condition=condition,
                    title=f"个股-板块背离：{stock.name} 跑输 {sector.name}",
                    detail=(
                        f"{stock.name} 30分钟相对 {sector.name} 背离 "
                        f"{divergence:+.2f} 个百分点，个股放量倍数 {_ratio(vr)}"
                    ),
                    metrics={
                        "divergence_pct": divergence,
                        "stock_change_pct": stock.change_pct,
                        "sector_change_pct": sector.change_pct,
                        "stock_change_30m_ago": stock_30,
                        "sector_change_30m_ago": sector_30,
                        "stock_volume_ratio": vr,
                        "sector_code": sector.code,
                        "sector_name": sector.name,
                    },
                )
            )
        return items

    def _update_rs(self, view: MarketView) -> None:
        if view.sector_fallback:
            self.last_rs.clear()
            self.r5_direction.clear()
            return
        hs300 = view.indexes.get("000300.SH")
        benchmark = hs300.change_pct if hs300 is not None else None
        if benchmark is None or not view.sectors:
            self.last_rs.clear()
            self.r5_direction.clear()
            return
        for row in view.sectors:
            if row.change_pct is None:
                continue
            self.last_rs[row.code] = row.change_pct - benchmark

    # -- observability ---------------------------------------------------
    def suppressed_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for (rule_id, _key), state in self.states.items():
            if state.suppressed:
                result[rule_id] = result.get(rule_id, 0) + state.suppressed
        return result
