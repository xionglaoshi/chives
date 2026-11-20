"""Day-by-day replay across the whole market (spec sections 1-5).

The engine processes exactly one market day at a time.  New first boards are
identified before the existing rounds are advanced, as the task requires.  Only
data up to the current day is read, so the same code path serves full replay and
the incremental ``step`` command.  Roll-up histories keep the last 25 valid bars
per code: enough for the 10-day first-board window, MA20 and the 5-bar volume
ratio.
"""

from __future__ import annotations

import bisect
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from .market import MarketSource
from .outputs import OutputStore, default_paths
from .spec import (
    SPEC_VERSION,
    WindowBar,
    check_first_board,
    first_pool_sort_key,
    main_pool_sort_key,
)
from .state import (
    FIRST_BOARD,
    BarView,
    DayContext,
    Event,
    Round,
)

HISTORY_LEN = 25
WARMUP_DAYS = 70
SEED_DAYS = 45


@dataclass(frozen=True)
class HistBar:
    day_index: int
    close: float
    low: float
    volume: int
    limit_up: bool


class SurgeReplay:
    def __init__(
        self,
        source: MarketSource,
        output: OutputStore | None = None,
        *,
        state_path: Path | str | None = None,
    ) -> None:
        self.source = source
        self.output = output or OutputStore()
        self.state_path = Path(state_path) if state_path else default_paths()[1]
        self.calendar = list(source.calendar())
        self.index = {day: offset for offset, day in enumerate(self.calendar)}
        self.active: dict[str, Round] = {}
        self.counters: dict[str, int] = {}
        self.history: dict[str, deque[HistBar]] = defaultdict(lambda: deque(maxlen=HISTORY_LEN))
        self.last_raw: dict[str, float] = {}
        self.last_close: dict[str, float] = {}
        self.last_day: date | None = None

    # -- public entry points ----------------------------------------------
    def run(self, start: date | str, end: date | str, *, reset: bool = True, verbose: bool = False) -> date:
        start_day = _as_date(start)
        end_day = _as_date(end)
        start_idx = bisect.bisect_left(self.calendar, start_day)
        if start_idx >= len(self.calendar):
            raise ValueError(f"no trading day on or after {start_day}")
        end_idx = bisect.bisect_right(self.calendar, end_day) - 1
        if end_idx < start_idx:
            raise ValueError("end is before start")
        start_day = self.calendar[start_idx]
        if reset:
            self.output.reset()
        self.active.clear()
        self.counters.clear()
        self.history.clear()
        self.last_raw.clear()
        self.last_close.clear()
        self.output.set_meta("spec_version", SPEC_VERSION)
        self.output.set_meta("engine", "surge-engine")
        process_from = max(0, start_idx - WARMUP_DAYS)
        self._seed_history(process_from)
        for offset in range(process_from, end_idx + 1):
            day = self.calendar[offset]
            self._process_day(offset, emit=day >= start_day)
            if verbose and (offset - process_from) % 100 == 0:
                print(f"replay {day} active={len(self.active)}")
        self.output.set_meta("last_date", self.calendar[end_idx].isoformat())
        self.output.set_meta("replay_start", start_day.isoformat())
        self.output.set_meta("replay_end", self.calendar[end_idx].isoformat())
        self.output.conn.commit()
        self._save_state()
        return self.calendar[end_idx]

    def step(self, target: date | str, *, verbose: bool = False) -> list[Event]:
        target_day = _as_date(target)
        target_idx = self._require_index(target_day)
        self._load_state()
        if self.last_day is None:
            self.last_day = self.calendar[target_idx - 1] if target_idx else None
        last_idx = self.index[self.last_day] if self.last_day is not None else target_idx - 1
        if target_idx <= last_idx:
            raise ValueError(f"state is already at {self.last_day}; {target_day} is not later")
        self._seed_history(last_idx + 1)
        emitted: list[Event] = []
        for offset in range(last_idx + 1, target_idx + 1):
            day = self.calendar[offset]
            emitted.extend(self._process_day(offset, emit=True))
            if verbose:
                print(f"step {day} active={len(self.active)}")
        self.output.set_meta("last_date", self.calendar[target_idx].isoformat())
        self.output.conn.commit()
        self._save_state()
        return emitted

    # -- one market day ----------------------------------------------------
    def _process_day(self, offset: int, *, emit: bool) -> list[Event]:
        day = self.calendar[offset]
        qfq = self.source.qfq_bars(day)
        raw = self.source.raw_closes(day)
        universe = self.source.universe(day)

        limits: dict[str, bool] = {}
        for code, bar in qfq.items():
            raw_close = raw.get(code)
            previous = self.last_raw.get(code)
            limits[code] = bool(
                raw_close is not None
                and self.source.is_limit_up(code, day, raw_close, previous)
            )

        events: list[Event] = []
        new_today: set[str] = set()
        for code in sorted(universe):
            bar = qfq.get(code)
            if bar is None or not limits.get(code) or code in self.active:
                continue
            window = [
                WindowBar(item.day_index, item.close, item.low, item.limit_up)
                for item in self.history.get(code, ())
                if offset - 10 <= item.day_index < offset
            ]
            result = check_first_board(f_day_index=offset, today_limit_up=True, window=window)
            if not result.ok:
                continue
            assert result.G is not None and result.M is not None and result.m is not None
            round_id = self.counters.get(code, 0) + 1
            self.counters[code] = round_id
            round_obj = Round.create(
                code=code,
                round_id=round_id,
                F=day,
                f_index=offset,
                C_F=bar.close,
                L_F=bar.low,
                G=result.G,
                M=result.M,
                m=result.m,
                drawdown=result.drawdown or 0.0,
            )
            self.active[code] = round_obj
            new_today.add(code)
            if emit:
                events.append(
                    Event(
                        code,
                        round_id,
                        day,
                        FIRST_BOARD,
                        {
                            "F": day.isoformat(),
                            "C_F": bar.close,
                            "L_F": bar.low,
                            "G": result.G,
                            "M": result.M,
                            "m": result.m,
                            "drawdown": result.drawdown,
                        },
                    )
                )

        first_rows: list[dict] = []
        main_rows: list[dict] = []
        round_rows: list[dict] = []
        for code, round_obj in list(self.active.items()):
            if code in new_today:
                if emit:
                    round_rows.append(round_obj.summary())
                continue
            bar = qfq.get(code)
            context = self._context(offset, day, code, bar, limits.get(code, False))
            produced = round_obj.step(context)
            if emit:
                events.extend(produced)
            if round_obj.in_first_pool and emit:
                first_rows.append(self._first_row(day, round_obj, bar))
            # A suspended stock has no C_t, so it has no main-pool score row that
            # day; it stays in the pool and reappears when it trades again.
            if round_obj.in_main_pool and bar is not None and emit:
                main_rows.append(self._main_row(day, round_obj, bar))
            if emit:
                round_rows.append(round_obj.summary())
            if round_obj.out:
                del self.active[code]

        if emit:
            self._rank(first_rows, first_pool_sort_key)
            self._rank(main_rows, main_pool_sort_key)
            self.output.write_day(
                events=events, first_rows=first_rows, main_rows=main_rows, rounds=round_rows
            )

        for code, bar in qfq.items():
            self.history[code].append(
                HistBar(offset, bar.close, bar.low, bar.volume, limits.get(code, False))
            )
        self.last_raw.update(raw)
        self.last_close.update({code: bar.close for code, bar in qfq.items()})
        self.last_day = day
        return events

    def _context(self, offset: int, day: date, code: str, bar: BarView | None, limit_up: bool) -> DayContext:
        closes = [item.close for item in self.history.get(code, ())]
        if bar is not None:
            closes = closes + [bar.close]
        return DayContext(
            date=day,
            day_index=offset,
            bar=bar,
            limit_up=limit_up,
            ma5=_last_mean(closes, 5),
            ma10=_last_mean(closes, 10),
            ma20=_last_mean(closes, 20),
            vol_ratio=self._volume_ratio(code, bar),
        )

    def _volume_ratio(self, code: str, bar: BarView | None) -> float | None:
        """Section 3.5 VR; when fewer than five positive-volume bars exist before
        T*, the available bars are averaged (the spec leaves this case open)."""

        if bar is None:
            return None
        prior = [item.volume for item in self.history.get(code, ()) if item.volume > 0][-5:]
        if not prior:
            return None
        mean = sum(prior) / len(prior)
        return None if mean <= 0 else bar.volume / mean

    @staticmethod
    def _first_row(day: date, round_obj: Round, bar: BarView | None) -> dict:
        scores = round_obj.scores()
        return {
            "date": day.isoformat(),
            "pool": "first",
            "code": round_obj.code,
            "round_id": round_obj.round_id,
            "rank": None,
            "status": round_obj.first_status(),
            "priority": round_obj.priority,
            "priority_date": None if round_obj.priority_date is None else round_obj.priority_date.isoformat(),
            "k": round_obj.k,
            "score": scores["score"],
            "support_score": scores["support_score"],
            "ma_score": scores["ma_score"],
            "time_score": scores["time_score"],
            "volume_score": scores["volume_score"],
            "hb": round_obj.hb,
            "s1_status": round_obj.s1.status,
            "s2_status": round_obj.s2.status,
            "t_star": None if round_obj.T_star is None else round_obj.T_star.isoformat(),
            "p_star": round_obj.P_star,
            "vr": round_obj.vr,
            "close": None if bar is None else bar.close,
        }

    @staticmethod
    def _main_row(day: date, round_obj: Round, bar: BarView) -> dict:
        scores = round_obj.main_scores(bar.close)
        return {
            "date": day.isoformat(),
            "pool": "main",
            "code": round_obj.code,
            "round_id": round_obj.round_id,
            "rank": None,
            "status": "主升浪",
            "priority": round_obj.priority,
            "k": round_obj.k,
            "score": scores["score"],
            "close": bar.close,
            "entry_date": None if round_obj.entry_date is None else round_obj.entry_date.isoformat(),
            "basis": round_obj.basis,
            "hmax": round_obj.hmax,
            "gain": scores["gain"],
            "drawdown": scores["drawdown"],
            "base_score": scores["base_score"],
            "deduction": scores["deduction"],
            "ma10_count": round_obj.ma10_count,
            "ma10_obs_left": round_obj.ma10_obs_left,
        }

    @staticmethod
    def _rank(rows: list[dict], key) -> None:
        rows.sort(key=key)
        for position, row in enumerate(rows, start=1):
            row["rank"] = position

    # -- history / state ---------------------------------------------------
    def _seed_history(self, first_offset: int) -> None:
        self.history.clear()
        self.last_raw.clear()
        self.last_close.clear()
        seed_from = max(0, first_offset - SEED_DAYS)
        if seed_from > 0:
            self.last_raw.update(self.source.raw_closes(self.calendar[seed_from - 1]))
        for offset in range(seed_from, first_offset):
            day = self.calendar[offset]
            qfq = self.source.qfq_bars(day)
            raw = self.source.raw_closes(day)
            limits: dict[str, bool] = {}
            for code, bar in qfq.items():
                raw_close = raw.get(code)
                previous = self.last_raw.get(code)
                limits[code] = bool(
                    raw_close is not None
                    and self.source.is_limit_up(code, day, raw_close, previous)
                )
            for code, bar in qfq.items():
                self.history[code].append(
                    HistBar(offset, bar.close, bar.low, bar.volume, limits.get(code, False))
                )
            self.last_raw.update(raw)
            self.last_close.update({code: bar.close for code, bar in qfq.items()})

    def _save_state(self) -> None:
        payload = {
            "spec_version": SPEC_VERSION,
            "last_date": None if self.last_day is None else self.last_day.isoformat(),
            "counters": self.counters,
            "active": [round_obj.to_state() for round_obj in self.active.values()],
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temp.replace(self.state_path)

    def _load_state(self) -> None:
        if not self.state_path.is_file():
            raise RuntimeError(f"state file not found: {self.state_path}; run replay first")
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.last_day = None if payload.get("last_date") is None else date.fromisoformat(payload["last_date"])
        self.counters = {str(code): int(value) for code, value in payload.get("counters", {}).items()}
        self.active = {
            item["code"]: Round.from_state(item) for item in payload.get("active", [])
        }

    def _require_index(self, day: date) -> int:
        if day not in self.index:
            raise ValueError(f"{day} is not a trading day in the store calendar")
        return self.index[day]

    def close(self) -> None:
        self.output.close()
        close = getattr(self.source, "close", None)
        if callable(close):
            close()


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _last_mean(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window
