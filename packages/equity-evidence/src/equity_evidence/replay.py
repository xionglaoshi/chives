from statistics import mean

from .market import daily


def replay(code, fast, slow, capital, fee):
    if fast >= slow:
        raise ValueError("短窗口需小于长窗口")
    series = daily(code, 250, "none")
    bars = series["bars"]
    if len(bars) <= slow:
        raise ValueError("可用历史不足")
    cash = capital
    shares = 0
    curve = []
    trades = []
    closes = []
    peak = capital
    drawdown = 0
    for row in bars:
        # Yesterday's completed bars determine today's desired position.
        if len(closes) >= slow and row["high"] > row["low"] and row["open"] > 0:
            long = mean(closes[-fast:]) > mean(closes[-slow:])
            price = row["open"]
            size = (
                int(cash / (price * (1 + fee)) / 100) * 100
                if long and shares == 0
                else (-shares if not long else 0)
            )
            if size:
                cost = abs(size) * price * fee
                cash -= size * price + cost
                shares += size
                trades.append(
                    {"date": row["time"], "shares": size, "price": price, "fees": cost}
                )
        closes.append(row["close"])
        nav = cash + shares * row["close"]
        curve.append({"date": row["time"], "equity": nav})
        peak = max(peak, nav)
        drawdown = max(drawdown, 1 - nav / peak)
    return {
        "code": code,
        "source": series.get("source"),
        "model": "未复权日线，上一日均线判定、下一开盘成交，整百股，单一费率，忽略分红与滑点，跳过一字线",
        "trades": trades,
        "curve": curve,
        "return_pct": (nav / capital - 1) * 100,
        "max_drawdown_pct": drawdown * 100,
        "open_shares": shares,
    }
