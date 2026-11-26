from datetime import datetime, timedelta
from math import sin
import random
import pytest
from chives_radar.technical import crossings


def series(count):
    rng = random.Random(5015)
    start = datetime.fromisoformat("2026-11-25T09:30:00+08:00")
    out = []
    for i in range(count):
        d, n = divmod(i, 48)
        t = start + timedelta(days=d, minutes=5*n + (90 if n >= 24 else 0))
        mid = 30 + 5*sin(i/6) + 3*sin(i/16) + rng.uniform(-2, 2)
        opening = mid + rng.uniform(-1, 1)
        vol = rng.randint(100, 1400)
        out.append(dict(time=t.isoformat(), open=opening, close=mid, low=min(mid, opening)-rng.random(),
                        high=max(mid, opening)+rng.random(), volume_shares=vol, amount_yuan=vol*mid))
    return out


def test_replay_has_reproducible_crossings_for_every_indicator():
    bars = series(400)
    seen = set()
    for i in range(2, len(bars)):
        window = bars[max(0,i-160):i]
        hits = crossings(window)
        assert hits == crossings(window)
        for h in hits:
            assert (h["after"] > h["levelAfter"]) == h["up"]
            assert h["before"] <= h["levelBefore"] if h["up"] else h["before"] >= h["levelBefore"]
            seen.add(h["name"])
    for group in ("5周期均线", "MACD", "KD/KDJ", "J线", "RSI14", "DMI", "BRAR AR", "BRAR BR", "CR26", "PSY12", "DMA", "TRIX", "成交量", "VWAP"):
        assert any(group in name for name in seen), group


def test_ma_reference_and_missing_volume_not_zero():
    bars = series(8)
    for b in bars:
        b.update(open=10, high=12, low=9, close=10, amount_yuan=None, volume_shares=None)
    bars[-1]["close"] = 12
    expected = dict(name="价格与5周期均线", before=10, after=12, levelBefore=10, levelAfter=10.4, up=True)
    assert crossings(bars) == [expected]
    bars[-1]["time"] = (datetime.fromisoformat(bars[-1]["time"])+timedelta(minutes=5)).isoformat()
    assert crossings(bars) == []


def test_invalid_ohlc_rejected():
    rows=series(10)
    rows[-1]["high"]=rows[-1]["low"]-1
    with pytest.raises(ValueError):
        crossings(rows)


def test_http_evaluator_uses_the_same_formula_and_preserves_read_only_routes(tmp_path):
    from chives_radar.server import stop_server
    from test_plan_http import make, request
    _, httpd, thread = make(tmp_path)
    port = httpd.server_address[1]
    try:
        bars = series(160)
        assert request(port, "/technical/evaluate", method="POST", payload={"bars":bars}) == (200, {"signals":crossings(bars)})
        assert request(port, "/technical/evaluate")[0] == 405
        assert request(port, "/technical/evaluate", method="POST", payload={"bars":"oops"})[0] == 400
    finally:
        stop_server(httpd, thread)
