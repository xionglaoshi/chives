"""Pure standard-library risk math and A-share exposure classification."""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

ANNUALIZATION_DAYS = 252
MIN_BARS = 60
UNKNOWN_INDUSTRY = "未标注"

BROAD_INDEX_ETF_CODES = frozenset(
    {
        "510050.SH",  # 上证50ETF
        "510100.SH",  # 上证50ETF
        "510180.SH",  # 上证180ETF
        "510300.SH",  # 沪深300ETF
        "510310.SH",  # 沪深300ETF
        "510330.SH",  # 沪深300ETF
        "510350.SH",  # 沪深300ETF
        "510360.SH",  # 沪深300ETF
        "510500.SH",  # 中证500ETF
        "510710.SH",  # 上证180ETF
        "510800.SH",  # 上证380ETF
        "512100.SH",  # 中证1000ETF
        "512500.SH",  # 中证500ETF
        "512510.SH",  # 中证500ETF
        "515300.SH",  # 沪深300ETF
        "515330.SH",  # 沪深300ETF
        "515350.SH",  # 沪深300ETF
        "515380.SH",  # 沪深300ETF
        "515660.SH",  # 沪深300ETF
        "588000.SH",  # 科创50ETF
        "588080.SH",  # 科创板50ETF
        "159901.SZ",  # 深证100ETF
        "159915.SZ",  # 创业板ETF
        "159919.SZ",  # 沪深300ETF
        "159922.SZ",  # 中证500ETF
        "159949.SZ",  # 创业板50ETF
        "159845.SZ",  # 中证1000ETF
        "159531.SZ",  # 中证2000ETF
        "159338.SZ",  # 中证A500ETF
    }
)

_BROAD_INDEX_NAME_KEYWORDS = (
    "沪深300",
    "中证500",
    "中证1000",
    "中证2000",
    "中证A500",
    "中证A50",
    "中证100",
    "上证50",
    "上证180",
    "上证380",
    "科创50",
    "科创板50",
    "创业板",
    "深证100",
    "国证2000",
    "宽基",
)


def _digits(code: str) -> str:
    return code.split(".", 1)[0]


def is_etf(code: str) -> bool:
    """Shanghai 5-prefixed funds and Shenzhen 159/16-prefixed funds."""
    digits = _digits(code)
    return digits.startswith("5") or digits.startswith(("158", "159", "16", "18"))


def board_of(code: str) -> str:
    if is_etf(code):
        return "ETF 基金"
    digits = _digits(code)
    if digits.startswith(("300", "301")):
        return "创业板"
    if digits.startswith(("688", "689")):
        return "科创板"
    if digits.startswith(("92", "4", "8")):
        return "北交所"
    return "主板"


def asset_class_of(code: str) -> str:
    return "etf" if is_etf(code) else "stock"


def is_broad_index_etf(code: str, name: str | None) -> bool:
    if not is_etf(code):
        return False
    if code in BROAD_INDEX_ETF_CODES:
        return True
    text = name or ""
    return any(keyword in text for keyword in _BROAD_INDEX_NAME_KEYWORDS)


def sample_stdev(values: Sequence[float]) -> float | None:
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return math.sqrt(max(variance, 0.0))


def annualized_volatility(returns: Sequence[float]) -> float | None:
    stdev = sample_stdev(returns)
    if stdev is None:
        return None
    return stdev * math.sqrt(ANNUALIZATION_DAYS)


def variance(values: Sequence[float]) -> float | None:
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    return sum((value - mean) ** 2 for value in values) / (count - 1)


def covariance(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    return sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
    ) / (len(left) - 1)


def beta(returns: Sequence[float], benchmark_returns: Sequence[float]) -> float | None:
    cov = covariance(returns, benchmark_returns)
    var = variance(benchmark_returns)
    if cov is None or var is None or var <= 0:
        return None
    return cov / var


def correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    left_sq = sum((a - mean_left) ** 2 for a in left)
    right_sq = sum((b - mean_right) ** 2 for b in right)
    if left_sq <= 0 or right_sq <= 0:
        return None
    return numerator / math.sqrt(left_sq * right_sq)


def nav_curve(returns: Sequence[float]) -> list[float]:
    nav = 1.0
    curve = [nav]
    for value in returns:
        nav *= 1.0 + value
        curve.append(nav)
    return curve


def max_drawdown(returns: Sequence[float]) -> float:
    """Largest peak-to-trough drawdown of the replayed NAV, as a positive ratio."""
    peak = 1.0
    worst = 0.0
    nav = 1.0
    for value in returns:
        nav *= 1.0 + value
        if nav > peak:
            peak = nav
        drawdown = (peak - nav) / peak if peak > 0 else 0.0
        if drawdown > worst:
            worst = drawdown
    return worst


def replay_returns(
    calendar: Sequence[str], closes_by_date: Mapping[str, float]
) -> list[float | None]:
    """Forward-fill a position on the benchmark calendar; a missing bar returns 0.

    The first calendar day has no prior close and is None. Days before the
    position's first bar stay None rather than inventing a price.
    """
    returns: list[float | None] = []
    last_close: float | None = None
    previous: float | None = None
    for day in calendar:
        if day in closes_by_date:
            close = closes_by_date[day]
            had_bar = True
        elif last_close is not None:
            close = last_close
            had_bar = False
        else:
            returns.append(None)
            continue
        if previous is None:
            returns.append(None)
        else:
            returns.append((close / previous - 1.0) if had_bar else 0.0)
        previous = close
        last_close = close
    return returns


def sum_by(positions: Iterable[Mapping[str, object]], key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for position in positions:
        label = str(position.get(key) or UNKNOWN_INDUSTRY)
        weight = float(position.get("weight_ratio") or 0.0)
        totals[label] = totals.get(label, 0.0) + weight
    return totals
