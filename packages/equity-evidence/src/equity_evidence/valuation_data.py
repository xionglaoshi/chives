"""Dated A-share valuation panels. Fetch only public fields, preserve source inputs."""

import hashlib
import json
import math
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import requests
from .storage import library, save

SOURCE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SECURITIES = "RPT_VALUEANALYSIS_DET"
REPORTS = "RPT_F10_FINANCE_MAINFINADATA"
MARKET = "RPT_VALUEMARKET"
FINANCING = "RPTA_WEB_RZRQ_GGMX"
PEER_FIELDS = "SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,PE_TTM,PB_MRQ"
REPORT_FIELDS = (
    "SECUCODE,REPORT_DATE,NOTICE_DATE,UPDATE_DATE,CURRENCY,ORG_TYPE,EPSJB,BPS,"
    "PARENTNETPROFIT,KCFJCXSYJLR,TOTALOPERATEREVE,ROEJQ,MGJYXJJE,ZCFZL,NONPERLOAN,HXYJBCZL"
)


class SourceUnavailable(Exception):
    pass


def number(value):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return value
    return None


def financial_versions(code, current, through):
    """Keep public statement revisions so later vendor replacements do not erase a replay."""
    observed = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    path = library() / "market" / "valuation-financial-vintages.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    try:
        with db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS versions (code TEXT, digest TEXT, first_seen TEXT, "
                "payload TEXT NOT NULL, PRIMARY KEY (code, digest))"
            )
            payloads = [json.dumps(r, sort_keys=True, allow_nan=False) for r in current]
            db.executemany(
                "INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?)",
                [
                    (code, hashlib.sha256(p.encode()).hexdigest(), observed, p)
                    for p in payloads
                ],
            )
            known = set(payloads)
            older = [
                {**json.loads(payload), "_first_seen": seen}
                for payload, seen in db.execute(
                    "SELECT payload, first_seen FROM versions WHERE code=? AND first_seen<=? "
                    "ORDER BY first_seen, digest",
                    (code, through),
                )
                if payload not in known
            ]
    finally:
        db.close()
    return older + current


def rows(table, fields, condition, order, *, first=False):
    params = dict(
        reportName=table,
        columns=fields,
        filter=condition,
        sortColumns=order,
        sortTypes=",".join("-1" for _ in order.split(",")),
        pageSize=1 if first else 500,
    )
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    path = library() / "market" / "valuation-inputs" / (key + ".json")
    if path.is_file() and time.time() - path.stat().st_mtime < 21600:
        return json.loads(path.read_bytes())
    result = []
    page = 1
    while True:
        try:
            response = requests.get(
                SOURCE, params={**params, "pageNumber": page}, timeout=(4, 10)
            )
            response.raise_for_status()
            body = response.json()
            data = body.get("result")
            if data is None and (
                body.get("code") == 9201 or body.get("success") is True
            ):
                return []
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise SourceUnavailable(table + " 未返回可核验记录")
            result.extend(data["data"])
            if first or page >= int(data["pages"]):
                break
            page += 1
            if page > 60:
                raise SourceUnavailable(table + " 分页超限，放弃不完整样本")
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailable(table + " 暂时无法读取") from exc
    if result:
        save(path, result)
    return result


def index_history(start, day):
    """Pick completed, relatively flat months using only contemporary 60-session trends."""
    raw = rows(
        MARKET,
        "TRADE_MARKET_CODE,TRADE_DATE,CLOSE_PRICE",
        f"(TRADE_DATE>='{start}')(TRADE_DATE<='{day}')(TRADE_MARKET_CODE in (\"000001\",\"399001\"))",
        "TRADE_DATE,TRADE_MARKET_CODE",
    )
    series = {}
    for row in raw:
        day_key = row["TRADE_DATE"][:10]
        close = number(row["CLOSE_PRICE"])
        if close and close > 0:
            series.setdefault(day_key, {})[row["TRADE_MARKET_CODE"]] = close
    return series


def market_months(day, series):
    dates = sorted(k for k, prices in series.items() if k <= day and len(prices) == 2)
    months = {}
    latest = None
    for i in range(60, len(dates)):
        d = dates[i]
        changes = [
            series[d][k] / series[dates[i - 60]][k] - 1 for k in ("000001", "399001")
        ]
        latest = dict(date=d, sh_60d=changes[0], sz_60d=changes[1])
        if (
            d[:7] < day[:7]
            and (date.fromisoformat(day) - date.fromisoformat(d)).days <= 365 * 5
        ):
            months[d[:7]] = latest
    candidates = sorted(
        months.values(), key=lambda x: max(abs(x["sh_60d"]), abs(x["sz_60d"]))
    )
    neutral = [
        x for x in candidates if max(abs(x["sh_60d"]), abs(x["sz_60d"])) <= 0.10
    ][:18]
    return sorted(neutral, key=lambda x: x["date"]), latest


def rating_events(code, start, end):
    """Dated analyst changes only; no report text is sent to a model."""
    url = "https://reportapi.eastmoney.com/report/list"
    params = dict(
        code=code[:6],
        beginTime=start,
        endTime=end,
        qType=0,
        pageSize=100,
        industryCode="*",
        industry="*",
        rating="*",
        ratingChange="*",
    )
    output = []
    try:
        for page in range(1, 61):
            rsp = requests.get(
                url,
                params={
                    **params,
                    "pageNo": page,
                    "p": page,
                    "pageNumber": page,
                    "pageNum": page,
                },
                timeout=(3, 8),
            )
            rsp.raise_for_status()
            body = rsp.json()
            if not isinstance(body.get("data"), list):
                return []
            for r in body["data"]:
                if r.get("stockCode") == code[:6]:
                    output.append(
                        {
                            k: r.get(k)
                            for k in (
                                "orgCode",
                                "publishDate",
                                "infoCode",
                                "emRatingName",
                                "lastEmRatingName",
                            )
                        }
                    )
            if page >= int(body.get("TotalPage", 0)):
                return output
    except (requests.RequestException, TypeError, ValueError):
        pass
    return []


def peer_rows(industry, months):
    def peers(group):
        dates = ",".join("'" + m["date"] + "'" for m in group)
        return rows(
            SECURITIES,
            PEER_FIELDS,
            f'(BOARD_CODE="{industry}")(TRADE_DATE in ({dates}))',
            "TRADE_DATE,SECUCODE",
        )

    groups = [months[i : i + 3] for i in range(0, len(months), 3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for batch in pool.map(peers, groups) for row in batch]


def collect(code, day):
    quote_rows = rows(
        SECURITIES,
        PEER_FIELDS
        + ",BOARD_CODE,BOARD_NAME,CLOSE_PRICE,TOTAL_SHARES,NOTLIMITED_MARKETCAP_A",
        f"(SECUCODE=\"{code}\")(TRADE_DATE<='{day}')",
        "TRADE_DATE",
        first=True,
    )
    if not quote_rows:
        return {"quote": None}
    quote = quote_rows[0]
    industry = str(quote["BOARD_CODE"])
    if not re.fullmatch(r"[0-9A-Za-z]{1,20}", industry):
        raise SourceUnavailable("行业代码缺失")
    quote_day = quote["TRADE_DATE"][:10]
    # For a suspended stock do not mix an old share count and freshly published accounts.
    if (date.fromisoformat(day) - date.fromisoformat(quote_day)).days > 14:
        return {"quote": quote, "stale": True}
    start = (date.fromisoformat(quote_day) - timedelta(days=365 * 8)).isoformat()
    with ThreadPoolExecutor(max_workers=4) as pool:
        past = date.fromisoformat(quote_day)
        market = pool.submit(
            index_history, (past - timedelta(days=365 * 5 + 120)).isoformat(), quote_day
        )
        events = pool.submit(
            rating_events, code, (past - timedelta(days=45)).isoformat(), quote_day
        )
        finance = pool.submit(
            rows,
            REPORTS,
            REPORT_FIELDS,
            f"(SECUCODE=\"{code}\")(REPORT_DATE>='{start}')(NOTICE_DATE<='{quote_day}')",
            "REPORT_DATE",
        )
        flow = pool.submit(
            rows,
            FINANCING,
            "SECUCODE,DATE,RZJME5D",
            f"(SECUCODE=\"{code}\")(DATE<'{quote_day}')",
            "DATE",
            first=True,
        )
        months, latest = market_months(quote_day, market.result())
        reports = financial_versions(code, finance.result(), quote_day)
        try:
            financing = flow.result()
        except SourceUnavailable:
            financing = []
    panel = peer_rows(industry, months)
    return dict(
        quote=quote,
        reports=reports,
        neutral_months=months,
        peers=panel,
        market_signal=latest,
        financing=financing,
        rating_events=events.result(),
        data_source=SOURCE,
        sentiment_source="https://reportapi.eastmoney.com/report/list",
        reports_used=[SECURITIES, REPORTS, MARKET, FINANCING],
    )
