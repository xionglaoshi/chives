"""Price a single position in yuan using the snapshot's exchange timestamp."""
import json
import math
import sqlite3
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from portfolio_mcp.quotes import GatewayQuoteClient, QuoteError, parse_quote_text


def select_quote(q, now):
    if not q or not q.time:
        return None
    stamp = datetime.fromisoformat(q.time)
    today = now.date()
    clock = now.time().replace(tzinfo=None)
    if stamp.date() > today:
        return None
    live = (stamp.date() == today and now.weekday() < 5 and
            (time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15)) and
            stamp.time() >= time(9, 25))
    if live or stamp.time() >= time(15):
        if q.price and q.price > 0:
            return dict(price=q.price, basis="最新行情" if live else "收盘价", as_of=q.time)
    if q.prev_close and q.prev_close > 0:
        return dict(price=q.prev_close, basis="前收盘价", as_of=q.time)
    return None


def read_price(code, directory):
    if code not in directory:
        return None
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if code.endswith(".OF"):
        url = "https://api.fund.eastmoney.com/f10/lsjz?fundCode="+code[:6]+"&pageIndex=1&pageSize=1"
        request = Request(url, headers={"Referer": "https://fundf10.eastmoney.com/"})
        try:
            with urlopen(request, timeout=5) as response:
                data = json.load(response)["Data"]
            row = data["LSJZList"][0]
            # Money-market funds publish income per 10,000 units instead of a NAV.
            if data.get("SYType") not in ("", None, False):
                return None
            value = float(row["DWJZ"])
            if math.isfinite(value) and value > 0:
                return dict(price=value, basis="单位净值", as_of=row["FSRQ"])
        except (URLError, TimeoutError, ValueError, TypeError, IndexError, KeyError):
            pass
        return None
    try:
        result = select_quote(GatewayQuoteClient(timeout=5).fetch([code]).get(code), now)
        if result:
            return result
    except (ValueError, QuoteError):
        pass
    if re.match(r"^(11|12|81)", code):
        ticker = code[-2:].lower()+code[:6]
        try:
            with urlopen("https://qt.gtimg.cn/q="+ticker, timeout=4) as response:
                bond = parse_quote_text(response.read().decode("gb18030")).get(code)
            result = select_quote(bond, now)
            if result:
                return result
        except (URLError, TimeoutError, ValueError):
            pass
    end = now.date() if now.hour >= 15 else now.date()-timedelta(days=1)
    db = Path(__file__).resolve().parents[4] / "data/marketdata/daily.sqlite"
    try:
        with sqlite3.connect(db.as_uri()+"?mode=ro", uri=True) as conn:
            row = conn.execute("select close,date from bars where code=? and date<=? and close>0 order by date desc limit 1", (code,end.isoformat())).fetchone()
        if row:
            return dict(price=row[0], basis="最近收盘价", as_of=row[1])
    except sqlite3.Error:
        pass
    return None
