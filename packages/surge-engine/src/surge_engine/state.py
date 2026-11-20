"""Per-stock round state machines from ``docs/strategy/zhushenglang-spec.md`` v1.

One ``Round`` object covers sections 1-5 for a single code.  ``round.step`` is
the only entry point and consumes one *market* day context, including days where
the stock is suspended (``bar is None``), because suspension days still occupy
the 45-day, support-observation and MA10-observation windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .spec import (
    CONFIRM_EXTRA,
    CONFIRM_WINDOW,
    MA_FLOOR_END,
    MA_FLOOR_START,
    MAX_K,
    SPEC_VERSION,
    convergence_satisfied,
    is_converged,
    main_wave_score,
    support_score,
    time_score,
    total_score,
    volume_score,
)

# Event names mirror spec section 6.
FIRST_BOARD = "首板"
SECOND_BOARD = "二板"
ENTER_FIRST_POOL = "入首板池"
START = "启动"
PRIORITY1 = "优先级一确定"
PRIORITY2 = "优先级二确定"
NORMAL_GRADE = "普通观察级"
CONFIRM_FAILED = "确认失败移出"
SUPPORT_BREAK = "支撑跌破"
SUPPORT_RECOVER = "支撑收复"
SUPPORT_BROKEN = "支撑最终破位"
EXPIRED = "到期移出"
ENTER_MAIN_POOL = "入主升浪池"
MA10_BREAK = "MA10跌破"
MA10_REPAIR = "MA10修复"
MAIN_EXIT = "主升浪移出"


@dataclass(frozen=True)
class BarView:
    """The fields of a daily bar the engine needs (already forward-adjusted)."""

    close: float
    low: float
    high: float
    volume: int


@dataclass(frozen=True)
class DayContext:
    """Everything the state machines may read for one code on one market day."""

    date: date
    day_index: int
    bar: BarView | None
    limit_up: bool
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    vol_ratio: float | None = None


@dataclass
class Event:
    code: str
    round_id: int
    date: date
    event: str
    values: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> tuple[str, int, str, str, str]:
        import json

        return (
            self.code,
            self.round_id,
            self.date.isoformat(),
            self.event,
            json.dumps(self.values, ensure_ascii=False, sort_keys=True, default=str),
        )


@dataclass
class SupportState:
    """Section 3.3 support sub-state machine (one per support line)."""

    name: str
    price: float
    status: str = "normal"  # normal | observing | broken
    recovered: bool = False
    obs_left: int = 0


@dataclass
class Round:
    """One round for one code; a code has at most one active round (section 0).

    Spec section 8.2 (v1): a started row stays in the first-pool list until a
    confirmation failure removes it from that list or the main-wave MA10 rule
    removes it from both pools.
    """

    code: str
    round_id: int
    F: date
    f_index: int
    C_F: float
    L_F: float
    G: float
    M: float
    m: float
    drawdown: float
    k: int = 0
    branch: str | None = None  # None (F day) | first | second
    in_first_pool: bool = False
    in_main_pool: bool = False
    out: bool = False
    started: bool = False
    T_star: date | None = None
    t_star_index: int | None = None
    P_star: float | None = None
    k_start: int | None = None
    st_value: float | None = None
    hb: float = 0.0
    vr: float | None = None
    sv: int = 0
    priority: str | None = None  # None | p1 | p2 | normal
    priority_date: date | None = None
    confirm_pending: bool = False
    above_day1: bool = False
    conv_flags: list[bool] = field(default_factory=list)
    sm_satisfied: bool = False
    floor_active: bool = False
    s1: SupportState = field(default_factory=lambda: SupportState("S1", 0.0))
    s2: SupportState = field(default_factory=lambda: SupportState("S2", 0.0))
    first_in_date: date | None = None
    first_in_index: int | None = None
    first_out_date: date | None = None
    first_out_index: int | None = None
    first_out_reason: str | None = None
    entry_date: date | None = None
    e_index: int | None = None
    basis: float | None = None
    hmax: float | None = None
    ma10_count: int = 0
    ma10_seen_above: bool = True
    ma10_obs_left: int = 0
    main_out_date: date | None = None
    main_out_index: int | None = None
    main_out_reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        code: str,
        round_id: int,
        F: date,
        f_index: int,
        C_F: float,
        L_F: float,
        G: float,
        M: float,
        m: float,
        drawdown: float,
    ) -> "Round":
        """Section 1 record; the round stays pending until F+1 (section 2)."""

        return cls(
            code=code,
            round_id=round_id,
            F=F,
            f_index=f_index,
            C_F=C_F,
            L_F=L_F,
            G=G,
            M=M,
            m=m,
            drawdown=drawdown,
            hb=C_F,
            s1=SupportState("S1", G),
            s2=SupportState("S2", L_F),
        )

    # -- stepping ----------------------------------------------------------
    def step(self, ctx: DayContext) -> list[Event]:
        """Advance exactly one market day and return the events it produced."""

        if self.out:
            return []
        events: list[Event] = []
        self.k = ctx.day_index - self.f_index
        if self.branch is None:
            self._branch(ctx, events)

        if self.in_first_pool and self.k >= 1:
            self._update_ma_convergence(ctx)

        if self.in_first_pool and not self.started:
            if ctx.bar is not None and ctx.bar.close > self.hb:
                self._start(ctx, events)
            if not self.started:
                self._check_supports(ctx, events)
            if not self.started and self.in_first_pool and self.k >= MAX_K:
                self._expire(ctx, events)

        if self.started and self.confirm_pending:
            self._check_confirm(ctx, events)

        if self.in_main_pool and ctx.bar is not None:
            self.hmax = max(self.hmax or ctx.bar.close, ctx.bar.close)
            if self.e_index is not None and ctx.day_index > self.e_index:
                self._check_ma10(ctx, events)

        if not self.started and ctx.bar is not None:
            self.hb = max(self.hb, ctx.bar.close)
        return events

    def _emit(self, events: list[Event], day: date, name: str, **values: Any) -> None:
        events.append(Event(self.code, self.round_id, day, name, values))

    def _branch(self, ctx: DayContext, events: list[Event]) -> None:
        """Section 2: F+1 limit-up goes straight to the main-wave pool."""

        if ctx.limit_up and ctx.bar is not None:
            self.branch = "second"
            self.entry_date = ctx.date
            self.e_index = ctx.day_index
            self.basis = self.C_F
            self.hmax = ctx.bar.close
            self.in_main_pool = True
            self._emit(events, ctx.date, SECOND_BOARD, F=self.F.isoformat(), close=ctx.bar.close)
            self._emit(
                events,
                ctx.date,
                ENTER_MAIN_POOL,
                source="second_board",
                E=ctx.date.isoformat(),
                B=self.C_F,
            )
            return
        self.branch = "first"
        self.in_first_pool = True
        self.first_in_date = ctx.date
        self.first_in_index = ctx.day_index
        self._emit(events, ctx.date, ENTER_FIRST_POOL, F=self.F.isoformat(), k=self.k)

    # -- section 3.2 start -------------------------------------------------
    def _start(self, ctx: DayContext, events: list[Event]) -> None:
        assert ctx.bar is not None
        self.started = True
        self.T_star = ctx.date
        self.t_star_index = ctx.day_index
        self.P_star = ctx.bar.close
        self.k_start = self.k
        self.st_value = time_score(self.k)
        self.vr = ctx.vol_ratio
        self.sv = volume_score(self.vr)
        self.entry_date = ctx.date
        self.e_index = ctx.day_index
        self.basis = self.P_star
        self.hmax = ctx.bar.close
        self.in_main_pool = True
        self.confirm_pending = True
        self.above_day1 = False
        # Section 3.2: support monitoring stops once the breakout is marked.
        for support in (self.s1, self.s2):
            support.obs_left = 0
            if support.status == "observing":
                support.status = "stopped"
        self._emit(
            events,
            ctx.date,
            START,
            T_star=ctx.date.isoformat(),
            P_star=self.P_star,
            Hb=self.hb,
            k=self.k,
            vr=self.vr,
        )
        self._emit(
            events,
            ctx.date,
            ENTER_MAIN_POOL,
            source="first_board",
            E=ctx.date.isoformat(),
            B=self.P_star,
        )

    # -- section 3.3 supports ---------------------------------------------
    def _check_supports(self, ctx: DayContext, events: list[Event]) -> None:
        for support in (self.s1, self.s2):
            if self.out or not self.in_first_pool:
                return
            close = None if ctx.bar is None else ctx.bar.close
            if support.status == "observing":
                if close is not None and close > support.price:
                    support.status = "normal"
                    support.recovered = True
                    support.obs_left = 0
                    self._emit(
                        events, ctx.date, SUPPORT_RECOVER, support=support.name, price=support.price, close=close
                    )
                else:
                    support.obs_left -= 1
                    if support.obs_left <= 0:
                        support.status = "broken"
                        support.obs_left = 0
                        self._emit(
                            events,
                            ctx.date,
                            SUPPORT_BROKEN,
                            support=support.name,
                            price=support.price,
                            close=close,
                        )
                        self._remove_first_pool(ctx, "support_broken")
                continue
            if support.status != "normal" or close is None or close >= support.price:
                continue
            self._emit(events, ctx.date, SUPPORT_BREAK, support=support.name, price=support.price, close=close)
            if support.recovered and support.name == "S1":
                support.status = "broken"
                self._emit(
                    events,
                    ctx.date,
                    SUPPORT_BROKEN,
                    support="S1",
                    price=support.price,
                    close=close,
                    reason="rebreak_after_recovery",
                )
                self._remove_first_pool(ctx, "support_rebreak")
            else:
                support.status = "observing"
                support.obs_left = 3

    # -- section 3.4 confirmation -----------------------------------------
    def _check_confirm(self, ctx: DayContext, events: list[Event]) -> None:
        assert self.k_start is not None and self.P_star is not None
        relative = self.k - self.k_start
        close = None if ctx.bar is None else ctx.bar.close
        if relative in CONFIRM_WINDOW:
            if ctx.limit_up:
                self._set_priority(ctx, events, "p1")
            elif relative == 1:
                self.above_day1 = close is not None and close > self.P_star
            elif self.above_day1 and close is not None and close > self.P_star:
                self._set_priority(ctx, events, "p2")
            return
        if relative in CONFIRM_EXTRA:
            if close is not None and close > self.P_star:
                self._set_priority(ctx, events, "normal")
            elif relative == CONFIRM_EXTRA[-1]:
                self.confirm_pending = False
                self._emit(
                    events,
                    ctx.date,
                    CONFIRM_FAILED,
                    P_star=self.P_star,
                    close=close,
                    main_pool_kept=self.in_main_pool,
                )
                self._remove_first_pool(ctx, "confirm_failed")

    def _set_priority(self, ctx: DayContext, events: list[Event], priority: str) -> None:
        self.priority = priority
        self.priority_date = ctx.date
        self.confirm_pending = False
        self.above_day1 = False
        name = {"p1": PRIORITY1, "p2": PRIORITY2, "normal": NORMAL_GRADE}[priority]
        self._emit(
            events,
            ctx.date,
            name,
            P_star=self.P_star,
            close=None if ctx.bar is None else ctx.bar.close,
            k=self.k,
            vr=self.vr,
        )

    # -- section 3.1 / 3.4 expiry -----------------------------------------
    def _expire(self, ctx: DayContext, events: list[Event]) -> None:
        self._emit(events, ctx.date, EXPIRED, k=self.k, hb=self.hb)
        self._remove_first_pool(ctx, "expired")

    def _remove_first_pool(self, ctx: DayContext, reason: str) -> None:
        if not self.in_first_pool:
            return
        self.in_first_pool = False
        self.first_out_date = ctx.date
        self.first_out_index = ctx.day_index
        self.first_out_reason = reason
        if not self.in_main_pool:
            self.out = True

    # -- section 5.3 MA10 --------------------------------------------------
    def _check_ma10(self, ctx: DayContext, events: list[Event]) -> None:
        close = None if ctx.bar is None else ctx.bar.close
        ma10 = ctx.ma10
        if close is not None and ma10 is not None and close > ma10:
            self.ma10_seen_above = True
            if self.ma10_obs_left > 0:
                self.ma10_obs_left = 0
                self._emit(events, ctx.date, MA10_REPAIR, n=self.ma10_count, ma10=ma10, close=close)
            return
        if close is not None and ma10 is not None and close < ma10:
            if self.ma10_seen_above:
                self.ma10_count += 1
                self.ma10_seen_above = False
                self._emit(events, ctx.date, MA10_BREAK, n=self.ma10_count, ma10=ma10, close=close)
                if self.ma10_count >= 3:
                    self._exit_main(ctx, events, "ma10_third")
                    return
                self.ma10_obs_left = 3
                return
        if self.ma10_obs_left > 0:
            self.ma10_obs_left -= 1
            if self.ma10_obs_left <= 0:
                self._exit_main(ctx, events, "ma10_unrepaired")

    def _exit_main(self, ctx: DayContext, events: list[Event], reason: str) -> None:
        self.in_main_pool = False
        self.out = True
        self.main_out_date = ctx.date
        self.main_out_index = ctx.day_index
        self.main_out_reason = reason
        self.ma10_obs_left = 0
        self._remove_first_pool(ctx, reason)
        self._emit(events, ctx.date, MAIN_EXIT, reason=reason, ma10_count=self.ma10_count)

    # -- daily scoring -----------------------------------------------------
    def _update_ma_convergence(self, ctx: DayContext) -> None:
        """Section 3.5 ``Sm`` / floor, updated inside ``step`` once per first-pool day.

        A suspended day has no new bar, so it cannot be a new convergence day; the
        formula itself is defined from the last valid bars (suspension assumption
        documented in the report).
        """

        if not self.in_first_pool or self.k < 1 or ctx.bar is None:
            return
        converged = is_converged(ctx.ma5, ctx.ma10, ctx.ma20)
        self.conv_flags = (self.conv_flags + [converged])[-3:]
        satisfied = convergence_satisfied(self.conv_flags)
        if satisfied:
            self.sm_satisfied = True
            if MA_FLOOR_START <= self.k <= MA_FLOOR_END:
                self.floor_active = True

    def scores(self) -> dict[str, Any]:
        """Sections 3.5/3.6 daily component scores for a first-pool row."""

        broken = sum(1 for support in (self.s1, self.s2) if support.status == "broken")
        ss = support_score(broken)
        sm = 100 if self.sm_satisfied else 0
        st = self.st_value if self.started and self.st_value is not None else time_score(self.k)
        sv = self.sv if self.started else 0
        score = total_score(ss, sm, st, sv, floor_active=self.floor_active)
        return {
            "support_score": ss,
            "ma_score": sm,
            "time_score": st,
            "volume_score": sv,
            "score": score,
            "floor_active": self.floor_active,
        }

    def first_status(self) -> str:
        if self.started and self.confirm_pending:
            return "确认中"
        if self.priority == "p1":
            return "优先级一"
        if self.priority == "p2":
            return "优先级二"
        return "普通观察级"

    def main_scores(self, close: float) -> dict[str, Any]:
        """Section 5.1 score row; 0 still stays in the pool."""

        assert self.basis is not None and self.hmax is not None
        base, deduction, gain, drawdown, score = main_wave_score(self.hmax, close, self.basis)
        return {
            "base_score": base,
            "deduction": deduction,
            "gain": gain,
            "drawdown": drawdown,
            "score": score,
        }

    # -- persistence -------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        return {
            "spec_version": SPEC_VERSION,
            "code": self.code,
            "round_id": self.round_id,
            "F": self.F.isoformat(),
            "f_index": self.f_index,
            "C_F": self.C_F,
            "L_F": self.L_F,
            "G": self.G,
            "M": self.M,
            "m": self.m,
            "drawdown": self.drawdown,
            "k": self.k,
            "branch": self.branch,
            "in_first_pool": self.in_first_pool,
            "in_main_pool": self.in_main_pool,
            "out": self.out,
            "started": self.started,
            "T_star": None if self.T_star is None else self.T_star.isoformat(),
            "t_star_index": self.t_star_index,
            "P_star": self.P_star,
            "k_start": self.k_start,
            "st_value": self.st_value,
            "hb": self.hb,
            "vr": self.vr,
            "sv": self.sv,
            "priority": self.priority,
            "priority_date": None if self.priority_date is None else self.priority_date.isoformat(),
            "confirm_pending": self.confirm_pending,
            "above_day1": self.above_day1,
            "conv_flags": list(self.conv_flags),
            "sm_satisfied": self.sm_satisfied,
            "floor_active": self.floor_active,
            "s1": self.s1.__dict__,
            "s2": self.s2.__dict__,
            "first_in_date": None if self.first_in_date is None else self.first_in_date.isoformat(),
            "first_in_index": self.first_in_index,
            "first_out_date": None if self.first_out_date is None else self.first_out_date.isoformat(),
            "first_out_index": self.first_out_index,
            "first_out_reason": self.first_out_reason,
            "entry_date": None if self.entry_date is None else self.entry_date.isoformat(),
            "e_index": self.e_index,
            "basis": self.basis,
            "hmax": self.hmax,
            "ma10_count": self.ma10_count,
            "ma10_seen_above": self.ma10_seen_above,
            "ma10_obs_left": self.ma10_obs_left,
            "main_out_date": None if self.main_out_date is None else self.main_out_date.isoformat(),
            "main_out_index": self.main_out_index,
            "main_out_reason": self.main_out_reason,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> "Round":
        def _date(value: str | None) -> date | None:
            return None if value is None else date.fromisoformat(value)

        round_obj = cls(
            code=data["code"],
            round_id=int(data["round_id"]),
            F=date.fromisoformat(data["F"]),
            f_index=int(data["f_index"]),
            C_F=float(data["C_F"]),
            L_F=float(data["L_F"]),
            G=float(data["G"]),
            M=float(data.get("M", data.get("window_max"))),
            m=float(data.get("m", data.get("window_min"))),
            drawdown=float(data["drawdown"]),
        )
        for key, value in data.items():
            if key in {"spec_version", "code", "round_id", "F", "f_index", "C_F", "L_F", "G", "M", "m", "drawdown"}:
                continue
            if key in {"T_star", "priority_date", "first_in_date", "first_out_date", "entry_date", "main_out_date"}:
                setattr(round_obj, key, _date(value))
            elif key in {"s1", "s2"}:
                setattr(round_obj, key, SupportState(**value))
            elif key == "conv_flags":
                round_obj.conv_flags = list(value)
            else:
                setattr(round_obj, key, value)
        if round_obj.s1 is None or round_obj.s2 is None:
            raise ValueError("serialized round is missing support state")
        return round_obj

    def summary(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "round_id": self.round_id,
            "F": self.F.isoformat(),
            "C_F": self.C_F,
            "L_F": self.L_F,
            "G": self.G,
            "window_max": self.M,
            "window_min": self.m,
            "drawdown": self.drawdown,
            "branch": self.branch,
            "started": int(self.started),
            "T_star": None if self.T_star is None else self.T_star.isoformat(),
            "P_star": self.P_star,
            "priority": self.priority,
            "priority_date": None if self.priority_date is None else self.priority_date.isoformat(),
            "vr": self.vr,
            "E": None if self.entry_date is None else self.entry_date.isoformat(),
            "B": self.basis,
            "first_in_date": None if self.first_in_date is None else self.first_in_date.isoformat(),
            "first_in_index": self.first_in_index,
            "first_out_date": None if self.first_out_date is None else self.first_out_date.isoformat(),
            "first_out_index": self.first_out_index,
            "first_out_reason": self.first_out_reason,
            "first_pool_days": _span(self.first_in_index, self.first_out_index),
            "main_out_date": None if self.main_out_date is None else self.main_out_date.isoformat(),
            "main_out_index": self.main_out_index,
            "main_out_reason": self.main_out_reason,
            "main_pool_days": _span(self.e_index, self.main_out_index),
            "ma10_count": self.ma10_count,
            "out": int(self.out),
        }


def _span(start: int | None, end: int | None) -> int | None:
    if start is None or end is None:
        return None
    return end - start + 1


