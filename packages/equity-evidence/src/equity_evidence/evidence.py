from datetime import date
from hashlib import sha256
from time import time
import json
from chives_data.announcement import PdfExtractionError, extract_pdf_text, pdftotext_path
from .storage import library, save, snapshot, digest_id
from .market import symbol
from . import filings
from .cash_parser import parse_cash
from .cash_report import cash_markdown


def document_path(key):
    return library() / "documents" / (digest_id(key) + ".pdf")


def pdf_text(meta):
    content = document_path(meta["sha256"]).read_bytes()
    if sha256(content).hexdigest() != meta["sha256"]:
        raise ValueError("公告原件哈希不符")
    executable = pdftotext_path()
    if not executable:
        raise ValueError("需要安装 Poppler 的 pdftotext")
    raw = extract_pdf_text(content, executable=executable, max_chars=4_000_000)
    if raw.truncated or raw.pages_total != meta["pages_total"]:
        raise ValueError("PDF 页数或提取长度不符")
    return raw.text.split("\f")[: raw.pages_total]


def material(code, as_of, period):
    code = symbol(code)
    day = date.fromisoformat(as_of) if as_of else date.today()
    if day > date.today() or (period and date.fromisoformat(period) > day):
        raise ValueError("报告期或截至日无效")
    file = (
        library()
        / "filings"
        / code
        / (day.isoformat() + ("-" + period if period else "") + ".json")
    )
    if file.exists() and (as_of or time()-file.stat().st_mtime < 3600):
        manifest = json.loads(file.read_bytes())
        docs = []
        errors = list(manifest["errors"])
        for meta in manifest["documents"]:
            try:
                docs.append((meta, pdf_text(meta)))
            except (OSError, ValueError, RuntimeError, PdfExtractionError) as exc:
                errors.append(f"{meta['title']}：{exc}")
        return docs, errors, manifest["scope"], manifest.get("financial", {})
    docs, errors, scope = filings.collect(code, day, period or None)
    if docs and not errors:
        save(
            file, dict(documents=[meta for meta, _ in docs], errors=errors, scope=scope)
        )
    return docs, errors, scope, {}


def filing_evidence(code: str, as_of: str = "", period: str = "") -> dict:
    """Discover public annual/interim/quarterly filings and related inquiries by date. Return PDF SHA and source URL."""
    docs, errors, scope, _ = material(code, as_of, period)
    return dict(
        code=symbol(code), scope=scope, documents=[m for m, _ in docs], gaps=errors
    )


def evidence_page(document_id: str, page: int) -> dict:
    """Read a physical page (1-based) from an archived filing or research report."""
    content = document_path(document_id).read_bytes()
    if sha256(content).hexdigest() != document_id or page < 1:
        raise ValueError("文件或页码无效")
    raw = extract_pdf_text(
        content,
        executable=pdftotext_path(),
        start_page=page,
        end_page=page,
        max_chars=20000,
    )
    return dict(
        document_id=document_id,
        page=page,
        total_pages=raw.pages_total,
        text=raw.text,
        truncated=raw.truncated,
        link=f"api/research-documents/{document_id}#page={page}",
    )


def cash_quality(code: str, as_of: str = "", period: str = "") -> dict:
    """Recompute cash conversion, ageing and post-period receipts from original PDFs; returns a cited report and evidence snapshot."""
    docs, errors, scope, financial = material(code, as_of, period)
    d = parse_cash(docs, errors, scope, financial)
    for f in d["filings"]:
        if f["meta"]["period"] and not f.get("statements", {}).get("合并"):
            d["errors"].append(f["meta"]["title"] + "：合并报表解析不完整，请核对原页")
    if d["errors"] and d["status"] == "ok":
        d["status"] = "partial"
    key = snapshot({"code": symbol(code), "method": "cash-quality/1", "result": d})
    return dict(
        snapshot_id=key,
        status=d["status"],
        coverage=d["coverage"],
        gaps=d["errors"],
        report=cash_markdown(symbol(code), d),
    )


def research_snapshot(snapshot_id: str, section: str = "", index: int = 0) -> dict:
    """Read a previous public research result by evidence hash. For cash reports select filings and an index."""
    value = json.loads(
        (library() / "snapshots" / (digest_id(snapshot_id) + ".json")).read_bytes()
    )
    result = value.get("result", value)
    if not section:
        return dict(
            snapshot_id=snapshot_id, code=value.get("code"), sections=list(result)
        )
    if section not in result:
        raise ValueError("未知字段")
    part = result[section]
    if isinstance(part, list):
        if not 0 <= index < len(part):
            raise ValueError("索引越界")
        part = part[index]
    return {"section": section, "value": part}
