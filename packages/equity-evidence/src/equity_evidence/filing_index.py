from datetime import date, timedelta
from urllib.parse import urljoin
import re
import requests
from bs4 import BeautifulSoup
from .market import gateway


def announcements(code, days=60):
    attempts = []
    primary = gateway.call(
        "company_announcements",
        {
            "code": code,
            "limit": 20,
            "start": (date.today() - timedelta(days=days)).isoformat(),
            "end": date.today().isoformat(),
        },
    )
    if (primary.get("data") or {}).get("announcements") and not primary.get("stale"):
        return primary
    attempts.append({"source": "巨潮", "status": primary.get("status")})
    digits = code[:6]
    url = f"https://money.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/stockid/{digits}.phtml"
    start = (date.today() - timedelta(days=days)).isoformat()
    end = date.today().isoformat()
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        rows = []
        for a in BeautifulSoup(resp.content, "html.parser").select(
            'a[href*="vCB_AllBulletinDetail.php"]'
        ):
            match = re.search(
                r"\d{4}-\d\d-\d\d",
                " ".join(str(x) for x in a.previous_siblings if isinstance(x, str)),
            )
            if match and start <= match[0] <= end:
                rows.append(
                    {
                        "date": match[0],
                        "title": a.get_text(strip=True),
                        "url": urljoin(url, a["href"]),
                    }
                )
        if rows:
            return {
                "status": "partial",
                "as_of": end,
                "data": {"announcements": rows},
                "basis": url,
                "attempts": attempts,
                "scope": "近一期列表页",
            }
    except requests.RequestException as exc:
        attempts.append({"source": "新浪", "error": type(exc).__name__})
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    try:
        resp = requests.get(
            url,
            params={
                "stock_list": digits,
                "begin_time": start,
                "end_time": end,
                "page_size": 30,
                "page_index": 1,
                "ann_type": "A",
                "client_source": "web",
                "sr": -1,
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        rows = [
            {
                "date": r["notice_date"][:10],
                "title": r["title"],
                "url": f"https://data.eastmoney.com/notices/detail/{digits}/{r['art_code']}.html",
            }
            for r in data["list"]
            if any(t["stock_code"] == digits for t in r["codes"])
        ]
        return {
            "status": "partial",
            "as_of": end,
            "basis": resp.url,
            "data": {"announcements": rows},
            "attempts": attempts,
            "total": data.get("total_hits"),
        }
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        attempts.append({"source": "东财", "error": type(exc).__name__})
    return {**primary, "attempts": attempts}
