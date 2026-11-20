"""Constants and pure rule functions from ``docs/strategy/zhushenglang-spec.md`` v1.

Every public function names the specification section it implements.  No state
and no I/O lives here so each rule can be unit-tested with hand-written bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Iterable, Sequence

SPEC_VERSION = "v1"

# Section 0: comparison / rounding口径.
CENT = Decimal("0.01")
_EPS = Decimal("0.000000001")

# Section 1: first-board window.
WINDOW_DAYS = 10
MIN_WINDOW_BARS = 6
DRAWDOWN_MIN = Decimal("0.03")
DRAWDOWN_MAX = Decimal("0.15")

# Section 3.1: first-pool lifetime.
MAX_K = 45

# Section 3.4: confirmation windows relative to T*.
CONFIRM_WINDOW = (1, 2)
CONFIRM_EXTRA = (3, 4, 5)

# Section 3.5: weights, convergence tolerance.
WEIGHT_SUPPORT = Decimal("0.30")
WEIGHT_MA = Decimal("0.15")
WEIGHT_TIME = Decimal("0.45")
WEIGHT_VOLUME = Decimal("0.10")
CONVERGENCE_TOL = Decimal("0.04")
MA_FLOOR_START, MA_FLOOR_END = 20, 30
FLOOR_SCORE = 60

# Section 5.1: main-wave bands.
GAIN_LOW = Decimal("0.15")
GAIN_HIGH = Decimal("0.25")
GAIN_STEP = Decimal("0.05")
DRAWDOWN_STEP = Decimal("0.03")


@dataclass(frozen=True)
class WindowBar:
    """One valid K-line inside the first-board lookback window (section 1)."""

    day_index: int
    close: float
    low: float
    limit_up: bool


@dataclass(frozen=True)
class FirstBoardCheck:
    """Result of the section 1 check.

    ``ok`` false carries a short ``reason``; the numeric fields are filled only
    when the bars needed for the calculation exist.
    """

    ok: bool
    reason: str
    G: float | None = None
    M: float | None = None
    m: float | None = None
    drawdown: float | None = None


def _dec(value: float | str | Decimal) -> Decimal:
    """Decimal from a float's shortest repr, quantized to 1e-9.

    Prices carry three decimals, so 1e-9 keeps boundary cases such as 30% or
    6% from flipping because of binary floating point noise.
    """

    if isinstance(value, Decimal):
        raw = value
    else:
        raw = Decimal(str(value))
    return raw.quantize(_EPS)


def round_half_up(value: float | Decimal) -> int:
    """Round half away from zero to an integer (sections 0 and 3.5)."""

    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def limit_price(prev_raw_close: float, ratio: Decimal | str) -> Decimal:
    """Section 0: ``round_half_up(prev_close * (1 + p), 2)``."""

    base = Decimal(str(prev_raw_close))
    return (base * (1 + Decimal(str(ratio)))).quantize(CENT, rounding=ROUND_HALF_UP)


def time_score(k: int) -> float:
    """Section 3.5 ``St``: 100 at k=1, 0 at k=45, linear between."""

    if k <= 0:
        raise ValueError("k must be >= 1")
    return 100.0 - (k - 1) * 100.0 / (MAX_K - 1)


def volume_score(vr: float | None) -> int:
    """Section 3.5 ``Sv``: 100 when VR>=1.5, 50 when 1.0<=VR<1.5, else 0."""

    if vr is None:
        return 0
    ratio = _dec(vr)
    if ratio >= Decimal("1.5"):
        return 100
    if ratio >= Decimal("1.0"):
        return 50
    return 0


def support_score(broken_supports: int) -> int:
    """Section 3.5 ``Ss``: 100 / 50 / 0 for zero / one / two final breaks.

    The v1 removal rule makes 50 and 0 unreachable for rows that stay in the
    pool; see spec section 8 item 1.
    """

    if broken_supports <= 0:
        return 100
    if broken_supports == 1:
        return 50
    return 0


def is_converged(ma5: float | None, ma10: float | None, ma20: float | None) -> bool:
    """Section 3.5 convergence day: ``max(|MA5-MA20|,|MA10-MA20|)/MA20 <= 4%``."""

    if ma5 is None or ma10 is None or ma20 is None or ma20 <= 0:
        return False
    spread = max(abs(_dec(ma5) - _dec(ma20)), abs(_dec(ma10) - _dec(ma20)))
    return spread / _dec(ma20) <= CONVERGENCE_TOL


def convergence_satisfied(last_three: Sequence[bool]) -> bool:
    """Section 3.5: at least 2 of the last 3 market days are convergence days."""

    return len(last_three) >= 3 and sum(1 for flag in last_three[-3:] if flag) >= 2


def total_score(
    support: int,
    ma: int,
    time: float,
    volume: int,
    *,
    floor_active: bool = False,
) -> int:
    """Section 3.5 total, rounded half up; floor of 60 when the k 20-30 rule hit."""

    weighted = (
        WEIGHT_SUPPORT * Decimal(support)
        + WEIGHT_MA * Decimal(ma)
        + WEIGHT_TIME * _dec(time)
        + WEIGHT_VOLUME * Decimal(volume)
    )
    score = round_half_up(weighted)
    if floor_active and score < FLOOR_SCORE:
        return FLOOR_SCORE
    return score


def base_score(gain: float) -> int:
    """Section 5.1 gain band: <15% 80, [15%,25%] 100, then -10 per 5pp tier."""

    g = _dec(gain)
    if g < GAIN_LOW:
        return 80
    if g <= GAIN_HIGH:
        return 100
    q = (g - GAIN_HIGH) / GAIN_STEP
    tier = int(q.quantize(Decimal("1"), rounding=ROUND_CEILING))
    return max(0, 90 - 10 * (tier - 1))


def drawdown_deduction(drawdown: float) -> int:
    """Section 5.1: ``10 * floor(d / 3%)`` (negative drawdown treated as 0)."""

    d = max(_dec(drawdown), Decimal("0"))
    q = d / DRAWDOWN_STEP
    return 10 * int(q.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def main_wave_score(hmax: float, close: float, basis: float) -> tuple[int, int, float, float, int]:
    """Section 5.1 complete row.

    Returns ``(base, deduction, gain, drawdown, score)``.  The score never goes
    below zero and a zero score still stays in the pool.
    """

    gain = _dec(hmax) / _dec(basis) - 1
    drawdown = (_dec(hmax) - _dec(close)) / _dec(hmax)
    base = base_score(gain)
    deduction = drawdown_deduction(drawdown)
    return base, deduction, float(gain), float(drawdown), max(0, base - deduction)


def check_first_board(
    *,
    f_day_index: int,
    today_limit_up: bool,
    window: Iterable[WindowBar],
    has_active_round: bool = False,
) -> FirstBoardCheck:
    """Section 1: all five first-board conditions on F.

    ``window`` holds valid bars for F-10 .. F-1 (suspension days have no bar).
    Conditions 2/3 are checked against those bars; the caller guarantees the
    window covers exactly the ten preceding market days.
    """

    if has_active_round:
        return FirstBoardCheck(False, "active_round")
    if not today_limit_up:
        return FirstBoardCheck(False, "not_limit_up")

    bars = sorted(
        (bar for bar in window if f_day_index - WINDOW_DAYS <= bar.day_index < f_day_index),
        key=lambda bar: bar.day_index,
    )
    if any(bar.limit_up for bar in bars):
        return FirstBoardCheck(False, "limit_up_in_window")
    if len(bars) < MIN_WINDOW_BARS:
        return FirstBoardCheck(False, "too_few_bars")

    max_close = max(bar.close for bar in bars)
    j_m = max(bar.day_index for bar in bars if bar.close == max_close)
    if j_m >= f_day_index - 1:
        return FirstBoardCheck(False, "max_on_last_day")

    after = [bar for bar in bars if bar.day_index > j_m]
    pit = min(bar.close for bar in bars)
    j_g = max(bar.day_index for bar in bars if bar.close == pit)
    if not after:
        return FirstBoardCheck(False, "no_bar_after_max", pit, max_close, None, None)
    min_after = min(bar.close for bar in after)
    drawdown = _dec(max_close - min_after) / _dec(max_close)
    if drawdown < DRAWDOWN_MIN or drawdown > DRAWDOWN_MAX:
        return FirstBoardCheck(False, "drawdown_out_of_range", pit, max_close, min_after, float(drawdown))

    if not any(bar.day_index > j_g and bar.close > pit for bar in bars):
        return FirstBoardCheck(False, "low_on_last_day", pit, max_close, min_after, float(drawdown))

    return FirstBoardCheck(
        True,
        "ok",
        G=pit,
        M=max_close,
        m=min_after,
        drawdown=float(drawdown),
    )


def first_pool_sort_key(row: dict) -> tuple:
    """Section 3.6 ordering for one first-pool snapshot row.

    ``priority`` is ``p1``/``p2``/``normal`` (pending confirmation is scored as
    normal).  Priority groups sort by determination date then VR; the normal
    group sorts by total score, then T* (not started last), then VR, then code.
    """

    priority = row["priority"]
    code = row["code"]
    vr = row.get("vr") or 0.0
    if priority in ("p1", "p2"):
        return (0 if priority == "p1" else 1, row.get("priority_date") or "9999-12-31", -vr, code)
    t_star = row.get("t_star") or "9999-12-31"
    return (2, -(row.get("score") or 0), t_star, -vr, code)


def main_pool_sort_key(row: dict) -> tuple:
    """Section 5.2 ordering: score desc, later E first, then code asc."""

    e_date = row.get("entry_date") or "0000-00-00"
    return (-(row.get("score") or 0), _neg_date(e_date), row["code"])


def _neg_date(value: str) -> tuple:
    y, m, d = (int(part) for part in value.split("-"))
    return (-y, -m, -d)
