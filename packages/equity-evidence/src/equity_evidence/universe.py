import threading
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from .earnings import annualized_eps

from .storage import stamp

_lock = threading.Lock()
_cache = None
mapped = {
    "pe_ttm": "市盈率-TTM",
    "price": "最新价",
    "change_pct": "涨跌幅",
    "pb_mrq": "市净率",
    "turnover_pct": "换手率",
    "volume_ratio": "量比",
    "pe_dynamic": "市盈率-动态",
}


def tencent_universe():
    import requests
    from chives_data.sources import parse_tencent_quotes

    directory = requests.get(
        "https://www.cninfo.com.cn/new/data/szse_stock.json", timeout=8
    ).json()["stockList"]
    members = {}
    for row in directory:
        code = row["code"]
        if row.get("category") != "A股" or not code.startswith(
            ("00", "30", "60", "68", "92")
        ):
            continue
        exchange = (
            "bj" if code.startswith("92") else "sh" if code.startswith("6") else "sz"
        )
        members[exchange + code] = row["zwjc"]
    quotes = {}
    symbols = list(members)

    def fetch(batch):
        try:
            response = requests.get(
                "https://qt.gtimg.cn/q=" + ",".join(batch), timeout=5
            )
            response.raise_for_status()
            return parse_tencent_quotes(
                response.content.decode("gb18030", errors="replace")
            )
        except requests.RequestException:
            return {}

    batches = [symbols[i : i + 80] for i in range(0, len(symbols), 80)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch in pool.map(fetch, batches):
            quotes.update(batch)
    dates = [r["quote_time"].date() for r in quotes.values() if r.get("quote_time")]
    if not dates:
        raise ValueError("腾讯没有返回带时间的报价")
    latest = max(dates)
    rows = []
    for ticker, name in members.items():
        r = quotes.get(ticker, {})
        if (
            not r.get("quote_time")
            or r["quote_time"].date() != latest
            or not r.get("price")
        ):
            r = {}
        rows.append(
            {
                "代码": ticker[2:],
                "名称": name,
                "最新价": r.get("price"),
                "涨跌幅": r.get("change_pct"),
                "市净率": r.get("pb"),
                "换手率": r.get("turnover_pct"),
                "量比": r.get("volume_ratio"),
                "市盈率-动态": None,
                "市盈率-TTM": r.get("pe"),
            }
        )
    return pd.DataFrame(rows), latest.isoformat()


def universe(conditions, limit):
    global _cache
    with _lock:
        if _cache is None or time.monotonic() - _cache[0] > 300:
            df, origin = tencent_universe()
            if df.empty or not {"代码", "名称", *mapped.values()} <= set(df):
                raise ValueError("全市场行情快照缺字段")
            _cache = (time.monotonic(), stamp(), df, origin)
        _, seen, df, day = _cache
    origin = f"巨潮名录与腾讯报价，数据日 {day}"
    if any(t.field == "pe_dynamic" for t in conditions):
        df = df.copy()
        try:
            eps = annualized_eps(day)
            df["市盈率-动态"] = df["最新价"] / df["代码"].map(eps["values"])
            origin += f"；{eps['period']}，{eps['method']}"
        except (ValueError, KeyError, OSError, TypeError) as exc:
            origin += "；年化 EPS 无法计算：" + type(exc).__name__

    match = pd.Series(True, index=df.index)
    unknown = pd.Series(False, index=df.index)
    for t in conditions:
        if t.field not in mapped:
            raise ValueError("全市场接口不提供滚动 PE，支持动态 PE")
        values = pd.to_numeric(df[mapped[t.field]], errors="coerce")
        good = (values > t.value) if t.op == "gt" else (values < t.value)
        match &= good | values.isna()
        unknown |= values.isna()
    found = df[match & ~unknown]
    return {
        "source": origin,
        "retrieved": seen,
        "universe_count": len(df),
        "matched_count": len(found),
        "unknown_count": int((match & unknown).sum()),
        "results": found[["代码", "名称"]].head(limit).to_dict("records"),
    }
