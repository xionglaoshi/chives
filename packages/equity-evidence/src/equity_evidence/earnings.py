"""Dynamic P/E calculated from the latest completed quarter's disclosed basic EPS."""

from datetime import date, timedelta
import json
import math
import requests
from .storage import library, save


def annualized_eps(day):
    asof = date.fromisoformat(day)
    start = date(asof.year, 3 * ((asof.month - 1) // 3) + 1, 1)
    period = start - timedelta(days=1)
    cache = library() / "market" / ("eps-" + day + ".json")
    if cache.exists():
        return json.loads(cache.read_bytes())
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = dict(
        reportName="RPT_LICO_FN_CPD",
        columns="SECURITY_CODE,BASIC_EPS,UPDATE_DATE,REPORTDATE",
        pageSize=500,
        sortColumns="SECURITY_CODE",
        sortTypes="1",
        filter=f"(REPORTDATE='{period}')",
    )
    values = {}
    page = 1
    while True:
        response = requests.get(
            url, params={**params, "pageNumber": page}, timeout=(3, 8)
        )
        response.raise_for_status()
        result = response.json().get("result") or {}
        rows = result.get("data") or []
        for r in rows:
            eps = r.get("BASIC_EPS")
            disclosed = str(r.get("UPDATE_DATE", ""))[:10]
            if (
                disclosed
                and disclosed <= day
                and isinstance(eps, (int, float))
                and math.isfinite(eps)
                and eps > 0
            ):
                values[r["SECURITY_CODE"]] = eps * 12 / period.month
        if not rows or page >= int(result["pages"]):
            break
        page += 1
    payload = {
        "period": period.isoformat(),
        "source": url,
        "method": "现价 ÷（当年最新完整季度累计基本 EPS × 12 / 报告期月份）；仅纳入行情日已披露的正 EPS",
        "values": values,
    }
    if values:
        save(cache, payload)
    return payload
