"""Refresh the offline holdings form's Shanghai, Shenzhen and Beijing security names."""
import html
import re
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

BASE = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center."
DEST = Path(__file__).resolve().parents[1] / "apps/web/public/holdings-securities.json"


def fetch(query):
    with urlopen(BASE + query + "&ts=" + str(time.time_ns()), timeout=30) as response:
        return json.loads(response.read().decode("gb18030"))


def snapshot(node):
    count = int(fetch("getHQNodeStockCount?node=" + node))

    def page(number):
        return fetch(f"getHQNodeData?node={node}&page={number}&num=100&sort=symbol&asc=1")

    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = [r for batch in pool.map(page, range(1, (count+99)//100+1)) for r in batch]
    entries = {r["code"]+"."+r["symbol"][:2].upper(): r["name"].strip() for r in rows}
    if not count or (node == "hs_a" and len(entries) != count) or not entries or not all(entries.values()):
        raise ValueError(f"Incomplete {node} snapshot: {len(entries)}/{count}")
    return entries


if __name__ == "__main__":
    equities = snapshot("hs_a")
    if {k[-2:] for k in equities} != {"SH", "SZ", "BJ"}:
        raise ValueError("Missing stock exchange")
    with urlopen("https://fund.eastmoney.com/cnjy_dwjz.html", timeout=30) as response:
        page = response.read().decode("gb18030")
    pairs = re.findall(r'id="tr(\d{6})"[^<]*(?:(?!</tr>).)*?<nobr><a [^>]+>([^<]+)</a>', page, re.S)
    funds = {code + (".SH" if code.startswith("5") else ".SZ"): html.unescape(name).strip()
             for code, name in pairs if code.startswith(("5", "158", "159", "16", "18"))}
    if len(funds) < 1000:
        raise ValueError("Incomplete listed-fund directory")
    with urlopen("https://fund.eastmoney.com/js/fundcode_search.js", timeout=30) as response:
        script = response.read().decode("utf-8-sig")
    catalog = json.loads(script.split("=", 1)[1].strip().rstrip(";"))
    otc = {code + ".OF": name for code, _, name, _, _ in catalog
           if re.fullmatch(r"\d{6}", code) and not re.search("美元|港币|外币|英镑|欧元|澳元", name)
           and not any(code + suffix in funds for suffix in (".SH", ".SZ"))}
    entries = equities | funds | otc | snapshot("hskzz_z")
    tmp = DEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1)+"\n")
    os.replace(tmp, DEST)
    print(f"{len(equities)} stocks, {len(entries)} securities")
