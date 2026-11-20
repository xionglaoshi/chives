from datetime import date
from hashlib import sha256
from urllib.parse import urlsplit
import re
import json
import requests
from cn_market_gateway.announcement import (
    MAX_PDF_BYTES,
    extract_pdf_text,
    pdftotext_path,
)
from .storage import library, save_bytes
from .market import symbol, gateway


def research_report_lookup(code: str, limit: int = 5) -> dict:
    """Find dated sell-side reports, forecast-year fields, consensus and full text availability; try multiple PDF candidates."""
    import akshare as ak

    if not 1 <= limit <= 10:
        raise ValueError("limit 须在 1–10 内")
    code = symbol(code)
    items = []
    gaps = []
    try:
        frame = ak.stock_research_report_em(symbol=code[:6]).sort_values(
            "日期", ascending=False
        )
        rows = json.loads(
            frame.head(limit).to_json(
                orient="records", date_format="iso", force_ascii=False
            )
        )
    except Exception as exc:
        gaps.append("东财研报目录：" + type(exc).__name__)
        rows = []
    for r in rows:
        url = next(
            (
                v
                for v in r.values()
                if isinstance(v, str) and v.startswith("https://pdf.dfcfw.com/pdf/")
            ),
            None,
        )
        entry = dict(
            title=r.get("报告名称") or r.get("报告标题") or r.get("研报标题"),
            organization=r.get("机构"),
            published=str(r.get("日期", ""))[:10],
            source=url,
            status="目录",
            forecasts={
                k: v
                for k, v in r.items()
                if re.search(r"20\d\d.*(?:收益|盈利|PE)", k, re.I)
            },
        )
        if url and urlsplit(url).hostname == "pdf.dfcfw.com":
            try:
                with requests.get(
                    url,
                    headers={"Referer": "https://data.eastmoney.com/"},
                    timeout=(3, 6),
                    stream=True,
                    allow_redirects=False,
                ) as resp:
                    resp.raise_for_status()
                    blob = bytearray()
                    for chunk in resp.iter_content(65536):
                        blob.extend(chunk)
                        if len(blob) > MAX_PDF_BYTES:
                            raise ValueError("PDF 超过上限")
                if not blob.startswith(b"%PDF"):
                    raise ValueError("响应并非 PDF")
                key = sha256(blob).hexdigest()
                raw = extract_pdf_text(
                    bytes(blob),
                    executable=pdftotext_path(),
                    start_page=1,
                    end_page=1,
                    max_chars=4200,
                )
                save_bytes(library() / "documents" / (key + ".pdf"), blob)
                entry.update(
                    status="有文字层" if raw.text.strip() else "PDF 无可读文字",
                    document_id=key,
                    pages=raw.pages_total,
                    first_page=raw.text[:1200],
                )
            except Exception as exc:
                entry["gap"] = "原文读取失败：" + type(exc).__name__
        items.append(entry)
    if not items:
        directory = gateway.call("company_reports", {"code": code, "limit": limit})
        items = [
            dict(r, status="仅目录，未核验正文")
            for r in (directory.get("data") or {}).get("reports", [])
        ]
    consensus = gateway.call("company_consensus", {"code": code})
    return dict(
        code=code,
        retrieved=date.today().isoformat(),
        reports=items,
        consensus=consensus,
        gaps=gaps,
    )


def special_financials(code: str) -> dict:
    """Return reported goodwill, bills, contract assets, cash, credit impairment and operating cash flow with periods."""
    import akshare as ak
    import pandas as pd

    c = symbol(code)
    output = {}
    for label, fn, fields in [
        (
            "balance",
            ak.stock_balance_sheet_by_report_em,
            ["GOODWILL", "NOTE_RECE", "CONTRACT_ASSET", "MONETARYFUNDS"],
        ),
        ("income", ak.stock_profit_sheet_by_report_em, ["CREDIT_IMPAIRMENT_INCOME"]),
        ("cashflow", ak.stock_cash_flow_sheet_by_report_em, ["NETCASH_OPERATE"]),
    ]:
        try:
            row = (
                fn(symbol=c[-2:] + c[:6])
                .sort_values("REPORT_DATE", ascending=False)
                .iloc[0]
            )
            output[label] = {
                "period": str(row["REPORT_DATE"])[:10],
                "published": str(row.get("NOTICE_DATE"))[:10],
                "yuan": {
                    f: None if pd.isna(row.get(f)) else float(row[f]) for f in fields
                },
            }
        except Exception as exc:
            output[label] = {"status": "unavailable", "reason": type(exc).__name__}
    return {
        "code": c,
        "source": "东方财富 · AKShare",
        "statements": output,
        "restricted_cash": "查受限资产表或附注",
    }
