"""Daily-bar measurements used by the Chives factor service."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ratio(numerator, denominator):
    """Use the historical precision convention and leave undefined ratios missing."""
    base = denominator.astype("float64")
    adjusted = base + np.sign(base) * 1e-12
    return numerator.astype("float64").div(adjusted.where(base.ne(0))).replace([np.inf, -np.inf], np.nan)


def candle(panel, name):
    opening = panel["open"]
    shape = name.removesuffix("2")
    if shape == "klen":
        length = panel["high"] - panel["low"]
    else:
        closing = panel["close"]
        if shape == "kmid":
            length = closing - opening
        elif shape == "ksft":
            length = 2.0 * closing - panel["high"] - panel["low"]
        elif shape == "kup":
            length = panel["high"] - opening.where(opening.ge(closing), closing)
        elif shape == "klow":
            length = opening.where(opening.le(closing), closing) - panel["low"]
        else:
            raise KeyError(name)
    basis = panel["high"] - panel["low"] if name.endswith("2") else opening
    return ratio(length, basis)


def movement_share(values, window, kind, *, count):
    previous = values.shift()
    if count:
        observed = values.notna() & previous.notna()
        up = values.gt(previous).where(observed).astype(float).rolling(window).mean()
        down = values.lt(previous).where(observed).astype(float).rolling(window).mean()
        if kind == "d":
            return up - down
        return up if kind == "p" else down

    # Subtract after shifting: unsigned volume can shrink from one day to the next.
    change = values - previous
    distance = change.abs().rolling(window).sum()
    gains = change.clip(lower=0).rolling(window).sum()
    losses = (-change).clip(lower=0).rolling(window).sum()
    if kind == "d":
        return ratio(gains - losses, distance)
    return ratio(gains if kind == "p" else losses, distance)


def extremum_position(values, window, maximum):
    # Index the most recent tied extreme from the start of the full window.
    locate = np.argmax if maximum else np.argmin
    return values.rolling(window).apply(lambda sample: window - 1 - locate(sample[::-1]), raw=True)


def price_trend(close, window, kind):
    if kind == "rsqr":
        dates = pd.Series(np.arange(len(close), dtype=float), index=close.index)
        correlation = close.rolling(window).corr(dates).replace([np.inf, -np.inf], np.nan)
        return correlation.pow(2)
    offsets = np.arange(window, dtype=float) - (window - 1) / 2
    weights = offsets / offsets.dot(offsets)
    slope = close.rolling(window).apply(lambda prices: prices @ weights, raw=True)
    if kind == "beta":
        return ratio(slope, close)
    fitted_close = close.rolling(window).mean() + slope * offsets[-1]
    return ratio(close - fitted_close, close)


def rolling_measure(panel, kind, window):
    if kind.startswith(("cnt", "sum", "vsum")):
        values = panel["volume" if kind.startswith("v") else "close"]
        return movement_share(values, window, kind[-1], count=kind.startswith("cnt"))
    if kind in ("imax", "imin", "imxd"):
        if kind != "imin":
            high_at = extremum_position(panel["high"], window, maximum=True)
            if kind == "imax":
                return high_at / window
        low_at = extremum_position(panel["low"], window, maximum=False)
        return low_at / window if kind == "imin" else (high_at - low_at) / window
    if kind in ("vma", "vstd"):
        volume = panel["volume"]
        history = volume.rolling(window)
        statistic = history.mean() if kind == "vma" else history.std()
        return ratio(statistic, volume + 1e-12)

    close = panel["close"]
    prices = close.rolling(window)
    if kind == "roc":
        return ratio(close.shift(window), close)
    if kind == "ma":
        return ratio(prices.mean(), close)
    if kind == "std":
        return ratio(prices.std(), close)
    if kind in ("qtld", "qtlu"):
        return ratio(prices.quantile(0.2 if kind == "qtld" else 0.8), close)
    if kind == "rank":
        return prices.rank(method="average", pct=True)
    if kind in ("max", "min", "rsv"):
        if kind == "max":
            return ratio(panel["high"].rolling(window).max(), close)
        low = panel["low"].rolling(window).min()
        if kind == "min":
            return ratio(low, close)
        return ratio(close - low, panel["high"].rolling(window).max() - low)
    if kind in ("beta", "resi", "rsqr"):
        return price_trend(close, window, kind)

    volume = panel["volume"]
    if kind == "corr":
        return prices.corr(np.log1p(volume)).replace([np.inf, -np.inf], np.nan)
    relative_close = ratio(close, close.shift())
    if kind == "cord":
        log_volume_change = np.log(ratio(volume, volume.shift()) + 1.0)
        return relative_close.rolling(window).corr(log_volume_change).replace([np.inf, -np.inf], np.nan)
    if kind == "wvma":
        weighted = ((relative_close - 1.0).abs() * volume).rolling(window)
        return ratio(weighted.std(), weighted.mean())
    raise KeyError(kind)
