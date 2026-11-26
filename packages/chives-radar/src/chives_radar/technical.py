"""Deterministic signals from consecutive, closed, unadjusted five-minute bars."""
from datetime import datetime, timedelta
from math import isfinite, nan
from statistics import fmean


def rolling(values, length, fn=fmean):
    return [fn(values[i-length+1:i+1]) if i+1 >= length else nan for i in range(len(values))]


def ema(values, period, alpha=None, seed=nan):
    alpha = 2 / (period + 1) if alpha is None else alpha
    result = []
    last = seed
    for value in values:
        if isfinite(value):
            last = last + alpha * (value-last) if isfinite(last) else value
            result.append(last)
        else:
            result.append(nan)
    return result


def pct(a, b):
    return 100*a/b if b > 0 else nan


def crossings(bars):
    if not isinstance(bars, list) or len(bars) > 320:
        raise ValueError("最多接受320根已收盘K线")
    if len(bars) < 2:
        return []
    stamps = []
    for bar in bars:
        if not isinstance(bar, dict) or not isinstance(bar.get("time"), str):
            raise ValueError("K线时间无效")
        ts = datetime.fromisoformat(bar["time"])
        if stamps and ts <= stamps[-1]:
            raise ValueError("K线时间必须递增")
        stamps.append(ts)
        for key in ("open", "low", "high", "close"):
            price = bar.get(key)
            if type(price) not in (float, int) or not isfinite(price) or price <= 0:
                raise ValueError("K线价格无效")
        if min(bar["open"], bar["close"]) < bar["low"] or max(bar["open"], bar["close"]) > bar["high"]:
            raise ValueError("K线区间无效")
        for key in ("volume_shares", "amount_yuan"):
            value = bar.get(key)
            if value is not None and (type(value) not in (float, int) or not isfinite(value) or value < 0):
                raise ValueError("成交字段无效")
    if stamps[-1]-stamps[-2] != timedelta(minutes=5):
        return []
    c = [b["close"] for b in bars]
    prev = [bars[0], *bars[:-1]]
    result = []

    def add(name, series, levels, warm):
        if len(series) <= warm:
            return
        lo, hi = series[-2:]
        a, b = levels[-2:] if isinstance(levels, list) else (levels, levels)
        if all(map(isfinite, (lo, hi, a, b))) and ((lo <= a and hi > b) or (lo >= a and hi < b)):
            result.append(dict(name=name, before=lo, after=hi, levelBefore=a, levelAfter=b, up=hi>b))

    def diff(a, b):
        return [i-j for i,j in zip(a,b)]

    add("价格与5周期均线", c, rolling(c, 5), 5)
    dif = diff(ema(c,12), ema(c,26))
    add("MACD DIF/DEA", dif, ema(dif,9), 60)
    lows = rolling([b["low"] for b in bars],9,min)
    highs = rolling([b["high"] for b in bars],9,max)
    rsv = [nan if not isfinite(l) else pct(v-l,h-l) if h>l else 50 for v,l,h in zip(c,lows,highs)]
    k = ema(rsv,3,1/3,50)
    d = ema(k,3,1/3,50)
    add("KD/KDJ K线与D线", k, d, 27)
    add("KDJ J线与100", [3*x-2*y for x,y in zip(k,d)], 100, 27)
    delta = [b["close"]-p["close"] for b,p in zip(bars,prev)]
    gains = ema([max(0,v) for v in delta],14,1/14)
    losses = ema([max(0,-v) for v in delta],14,1/14)
    rsi = [pct(g,g+l) for g,l in zip(gains,losses)]
    for level in (70,30):
        add(f"RSI14 与{level}", rsi, level, 42)
    atr = ema([max(b["high"]-b["low"],abs(b["high"]-p["close"]),abs(b["low"]-p["close"])) for b,p in zip(bars,prev)],14,1/14)
    hd = [b["high"]-p["high"] for b,p in zip(bars,prev)]
    ld = [p["low"]-b["low"] for b,p in zip(bars,prev)]
    def di(a,b):
        dm = ema([x if x>y and x>0 else 0 for x,y in zip(a,b)],14,1/14)
        return [pct(x,y) for x,y in zip(dm,atr)]
    add("DMI +DI/−DI", di(hd,ld), di(ld,hd),42)

    def energy(name,plus,minus):
        add(name,[pct(a,b) for a,b in zip(rolling(plus,26,sum),rolling(minus,26,sum))],100,27)
    energy("BRAR AR",[b["high"]-b["open"] for b in bars],[b["open"]-b["low"] for b in bars])
    def relative(name, pivot):
        energy(name,[max(0,b["high"]-p) for b,p in zip(bars,pivot)],
               [max(0,p-b["low"]) for b,p in zip(bars,pivot)])
    relative("BRAR BR",[p["close"] for p in prev])
    relative("CR26",[(p["high"]+p["low"])/2 for p in prev])
    psy = rolling([100 if v>0 else 0 for v in delta],12)
    for level in (75,25):
        add(f"PSY12 与{level}",psy,level,13)
    dma = diff(rolling(c,10),rolling(c,50))
    add("DMA(10,50)/AMA10",dma,rolling(dma,10),59)
    e3 = ema(ema(ema(c,12),12),12)
    trix = [nan]+[pct(v-p,p) for v,p in zip(e3[1:],e3)]
    add("TRIX12/TRMA9",trix,rolling(trix,9),60)
    vol = [b["volume_shares"] if b.get("volume_shares") is not None else nan for b in bars]
    add("成交量与前5周期均量的2倍",vol,[nan]+[2*v for v in rolling(vol[:-1],5)],6)
    vwap = []
    cash = shares = 0
    complete = False
    for i,(t,b) in enumerate(zip(stamps,bars)):
        if not i or t.date()!=stamps[i-1].date():
            cash = shares = 0
            complete = t.strftime("%H:%M") in ("09:30","09:35")
        elif t-stamps[i-1]!=timedelta(minutes=5):
            lunch=(stamps[i-1].strftime("%H:%M"),t.strftime("%H:%M")) in (("11:30","13:05"),("11:25","13:00"),("11:30","13:00"))
            complete = complete and lunch
        if b.get("amount_yuan") is None or b.get("volume_shares") is None or b["volume_shares"] and not b["amount_yuan"]:
            complete = False
        cash += b.get("amount_yuan") or 0
        shares += b.get("volume_shares") or 0
        vwap.append(cash/shares if shares and complete else nan)
    add("价格与当日VWAP",c,vwap,2)
    return result
