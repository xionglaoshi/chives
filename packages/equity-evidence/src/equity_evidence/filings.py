"""Discover dated filings and preserve the exact PDF behind every page citation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
import re

import requests

from .storage import library
from .market import gateway
from chives_data.announcement import (
    MAX_PDF_BYTES,
    PdfExtractionError,
    extract_pdf_text,
    pdftotext_path,
    resolve_pdf_url,
)


def discover(code, today, target_period=None):
    start = today - timedelta(days=450)
    rows, errors = [], []
    offset = 0
    while True:
        result = gateway.call(
            "company_announcements",
            dict(
                code=code,
                start=start.isoformat(),
                end=today.isoformat(),
                limit=100,
                offset=offset,
            ),
        )
        data = result.get("data") or {}
        if "announcements" not in data or result.get("stale"):
            errors.append("公告目录不可用或过期，检索范围不完整")
            break
        rows.extend(data["announcements"])
        following = data.get("next_offset")
        if following is None:
            break
        if following <= offset or following > 10000:
            errors.append("公告目录未取完")
            break
        offset = following

    def formal(t):
        return re.search(
            r"(20\d\d)\s*年(年度|半年度|第一季度|第三季度|三季度|一季度)报告(?:[（(](?:修订|更正|更新).*?[）)])?$",
            t,
        )

    main = []
    related = []
    for row in rows:
        title = row["title"].strip()
        match = formal(title)
        if match:
            year, kind = match.groups()
            period = (
                year
                + {
                    "年度": "-12-31",
                    "半年度": "-06-30",
                    "第一季度": "-03-31",
                    "一季度": "-03-31",
                    "第三季度": "-09-30",
                    "三季度": "-09-30",
                }[kind]
            )
            main.append(dict(row, period=period, kind=kind))
        elif (
            re.search(r"回款|应收账款|监管措施|问询.*回复|回复.*问询|年报.*回复", title)
            and "延期" not in title
        ):
            related.append(dict(row, period=None, kind="专项公告"))
    if target_period:
        main = [r for r in main if r["period"] <= target_period]
        if not any(r["period"] == target_period for r in main):
            errors.append("检索范围内未找到指定报告期 " + target_period)
    main.sort(
        key=lambda r: (
            r["period"],
            r["date"],
            bool(re.search("修订|更正|更新", r["title"])),
        ),
        reverse=True,
    )
    selected = []
    for group in (
        main[:1],
        [r for r in main if r["kind"] == "半年度"][:1],
        [r for r in main if r["kind"] == "年度"][:1],
        related[:12],
    ):
        for row in group:
            if row not in selected:
                selected.append(row)
    if len(related) > 12:
        errors.append("专项公告仅核查最近12份")
    return (
        selected,
        errors,
        dict(
            start=start.isoformat(),
            end=today.isoformat(),
            count=len(rows),
            name=data.get("name"),
            related=len(related),
        ),
    )


def read_filing(row):
    url = resolve_pdf_url(row["url"])
    with requests.get(
        url, timeout=(6, 25), stream=True, allow_redirects=False
    ) as response:
        response.raise_for_status()
        blob = bytearray()
        for part in response.iter_content(65536):
            blob.extend(part)
            if len(blob) > MAX_PDF_BYTES:
                raise ValueError("PDF 超过读取上限")
    if not blob.startswith(b"%PDF"):
        raise ValueError("未取得 PDF")
    digest = sha256(blob).hexdigest()
    path = library() / "documents" / f"{digest}.pdf"
    path.parent.mkdir(exist_ok=True, parents=True)
    if not path.exists():
        with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            tmp.write(blob)
        Path(tmp.name).replace(path)
    executable = pdftotext_path()
    if not executable:
        raise ValueError("需要 pdftotext")
    extracted = extract_pdf_text(
        bytes(blob), executable=executable, max_chars=4_000_000
    )
    if extracted.truncated:
        raise ValueError("PDF 超出文字提取上限")
    pages = extracted.text.split("\f")
    if len(pages) < extracted.pages_total:
        raise ValueError("PDF 物理页计数不一致")
    return dict(row, url=url, sha256=digest, pages_total=extracted.pages_total), pages[
        : extracted.pages_total
    ]


def collect(code, as_of, period=None):
    selected, errors, scope = discover(code, as_of, period)
    documents = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(r, pool.submit(read_filing, r)) for r in selected]
        for row, f in futures:
            try:
                documents.append(f.result())
            except (
                ValueError,
                requests.RequestException,
                PdfExtractionError,
                OSError,
            ) as exc:
                errors.append(f"{row['title']} 无法读取：{exc}")
    return documents, errors, scope
