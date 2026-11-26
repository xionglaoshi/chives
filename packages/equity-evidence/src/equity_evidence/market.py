import re
from datetime import date, timedelta
from cn_daily_store import DailyStore
from chives_data.service import GatewayService
from .storage import library

gateway = GatewayService(include_bar_reference=True)


def symbol(code):
    text = code.strip().upper()
    if not re.fullmatch(r"\d{6}(\.(SH|SZ|BJ))?", text):
        raise ValueError("请输入六位股票代码，可带交易所后缀")
    digits = "920427" if text[:6] == "833427" else text[:6]
    exchange = (
        "BJ"
        if digits.startswith(("4", "8", "92"))
        else "SH"
        if digits.startswith("6")
        else "SZ"
    )
    if "." in text and text.split(".")[1] != exchange:
        raise ValueError("证券与交易所不匹配")
    return digits + "." + exchange


def daily(code, days, adjust, as_of=None):
    code = symbol(code)
    end = date.fromisoformat(as_of) if as_of else date.today()
    if (
        end > date.today()
        or not 1 <= days <= 1000
        or adjust not in ("none", "qfq", "hfq")
    ):
        raise ValueError("日期、日数或复权类型无效")
    start = end - timedelta(days=days * 2 + 35)
    db = library().parent / "marketdata/daily.sqlite"
    local = []
    if db.is_file() and adjust in ("none", "qfq"):
        store = DailyStore(db)
        try:
            rows = store.bars(code, start, end, adjust=adjust)[-days:]
            local = [
                dict(
                    time=r.date.isoformat(),
                    open=r.open,
                    high=r.high,
                    low=r.low,
                    close=r.close,
                    volume_shares=r.volume,
                )
                for r in rows
            ]
        finally:
            store.close()
    origin = "Chives cn-daily-store"
    source_url = "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get"
    bars = local
    if len(local) < days or local[-1]["time"] != end.isoformat():
        response = gateway.call(
            "market_bars",
            dict(
                code=code,
                interval="1d",
                adjust=adjust,
                limit=days,
                start=start.isoformat(),
                end=end.isoformat(),
            ),
        )
        remote = (response.get("data") or {}).get("bars") or []
        if (
            not response.get("stale")
            and remote
            and (not local or remote[-1]["time"] >= local[-1]["time"])
        ):
            bars = remote
            origin = "Chives cn_market · " + response["data"].get(
                "bar_source", "market_bars"
            )
            source_url = response["data"].get("source_url")
    return dict(
        code=code,
        bars=bars,
        source=origin,
        source_url=source_url,
        as_of=bars[-1]["time"] if bars else None,
        requested_as_of=end.isoformat(),
        adjust=adjust,
        volume_unit="股",
        status="ok"
        if len(bars) == days and str(bars[-1]["time"])[:10] == end.isoformat()
        else "partial"
        if bars
        else "unavailable",
    )
