"""Parse a broker-exported holdings table (CSV / TSV / aligned text) into canonical rows.

Only code/name/quantity/available/cost/industry are taken from the table. Market value,
profit, fees and prices are ignored: valuation is always recomputed from the quote source.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from typing import Any

from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.fields import validate_position
from portfolio_mcp.sanitize import check_text_payload, clean_text
from portfolio_mcp.symbols import normalize_symbol

DELIMITERS = ("tab", "comma", "space")
MAX_HEADER_SCAN = 10

HEADER_ALIASES: dict[str, frozenset[str]] = {
    "code": frozenset(
        {
            "代码",
            "证券代码",
            "股票代码",
            "证券编码",
            "股票编码",
            "证券编号",
            "股票编号",
            "代码编号",
            "证券号",
            "股票号",
            "code",
            "symbol",
            "stockcode",
        }
    ),
    "name": frozenset(
        {
            "名称",
            "证券名称",
            "股票名称",
            "证券简称",
            "股票简称",
            "简称",
            "name",
            "stockname",
            "securityname",
        }
    ),
    "qty": frozenset(
        {
            "数量",
            "股票余额",
            "持仓数量",
            "当前持仓",
            "持股数量",
            "证券数量",
            "持仓量",
            "持仓股数",
            "股票数量",
            "股份余额",
            "持股数",
            "持股余额",
            "当前持仓量",
            "总持仓",
            "持仓",
            "证券余额",
            "当前余额",
            "qty",
            "quantity",
            "shares",
            "holding",
            "holdings",
        }
    ),
    "available": frozenset(
        {
            "可用",
            "可用余额",
            "可卖数量",
            "可用数量",
            "可用股数",
            "可卖股数",
            "可卖余额",
            "可用持仓",
            "可卖",
            "可用股份",
            "可卖股份",
            "股份可用",
            "available",
            "availableqty",
            "sellable",
        }
    ),
    "cost": frozenset(
        {
            "成本",
            "成本价",
            "参考成本价",
            "买入均价",
            "摊薄成本价",
            "持仓成本",
            "持仓成本价",
            "成本单价",
            "摊薄成本",
            "买入成本价",
            "买入成本",
            "持仓均价",
            "当前成本",
            "成本均价",
            "cost",
            "costprice",
            "avgcost",
        }
    ),
    "opened_date": frozenset(
        {"建仓日期", "买入日期", "开仓日期", "建仓时间", "买入时间", "openeddate"}
    ),
    "industry": frozenset({"行业", "所属行业", "板块", "所属板块", "行业名称", "industry", "sector"}),
    "note": frozenset({"备注", "说明", "备注信息", "note", "remark", "memo"}),
}

REQUIRED_COLUMNS = ("code", "name", "qty", "cost")
_EMPTY_VALUES = frozenset(
    {"", "-", "--", "---", "—", "－", "n/a", "na", "nan", "none", "null", "*", "***"}
)
_QUOTE_CHARS = "\"'“”‘’"
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_HEADER_SPACE_RE = re.compile(r"[\s:：·]+")
_COMMA_NUMBER_RE = re.compile(r"[,\uFF0C\s]")
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d")


def _unquote(value: str) -> str:
    text = value.strip()
    if text.startswith("="):
        text = text[1:].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    if text.startswith("'"):
        text = text[1:].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text


def _norm_header(cell: str) -> str:
    text = _unquote(cell).replace("\ufeff", "").strip().lower()
    text = _PAREN_RE.sub("", text)
    return _HEADER_SPACE_RE.sub("", text)


def _map_header(cells: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(cells):
        name = _norm_header(cell)
        if not name:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if name in aliases and field not in mapping:
                mapping[field] = index
                break
    return mapping


def _split_line(line: str, delimiter: str) -> list[str]:
    if delimiter == "tab":
        return next(csv.reader([line], delimiter="\t"))
    if delimiter == "comma":
        return next(csv.reader([line]))
    stripped = line.strip()
    if not stripped:
        return []
    return re.split(r"\s{2,}", stripped)


def _merge_thousands(cells: list[str], target_width: int) -> list[str]:
    """Rejoin an unquoted thousands-separated number (`1,000`) split by the comma delimiter."""
    if len(cells) <= target_width:
        return cells
    budget = len(cells) - target_width
    out: list[str] = []
    index = 0
    while index < len(cells):
        text = cells[index].strip()
        if budget > 0 and re.fullmatch(r"-?\d{1,3}", text):
            parts = [text]
            cursor = index + 1
            while (
                budget > 0
                and cursor < len(cells)
                and re.fullmatch(r"\d{3}(?:\.\d+)?", cells[cursor].strip())
            ):
                parts.append(cells[cursor].strip())
                budget -= 1
                cursor += 1
            if len(parts) >= 2:
                out.append("".join(parts))
                index = cursor
                continue
        out.append(cells[index])
        index += 1
    return out if len(out) == target_width else cells


def _find_header(
    lines: list[tuple[int, str]],
) -> tuple[int, str, dict[str, int], int]:
    """Return (index in `lines`, delimiter, mapping, header width)."""
    best: tuple[int, int, str, dict[str, int], int] | None = None
    for index, (_, line) in enumerate(lines[:MAX_HEADER_SCAN]):
        for delimiter in DELIMITERS:
            try:
                cells = _split_line(line, delimiter)
            except csv.Error:
                continue
            if len(cells) < 2:
                continue
            mapping = _map_header(cells)
            if not all(field in mapping for field in REQUIRED_COLUMNS):
                continue
            score = len(mapping) * 10 + len(cells)
            if best is None or score > best[0]:
                best = (score, index, delimiter, mapping, len(cells))
    if best is None:
        raise PortfolioError(
            "missing_header",
            "could not find a header row with code/name/quantity/cost columns; "
            "keep the first line of the exported table",
        )
    return best[1], best[2], best[3], best[4]


def _cell(cells: list[str], index: int) -> str:
    if index >= len(cells):
        return ""
    return cells[index]


def _number_text(value: str) -> str:
    text = _unquote(value)
    text = text.replace("元", "").replace("股", "").replace("人民币", "")
    return _COMMA_NUMBER_RE.sub("", text)


def _parse_number(value: str) -> float | None:
    text = _number_text(value)
    if text.casefold() in _EMPTY_VALUES:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise PortfolioError("invalid_number", "value is not a number") from exc


def _parse_int(value: str) -> int | None:
    number = _parse_number(value)
    if number is None:
        return None
    if not number.is_integer():
        raise PortfolioError("invalid_number", "quantity must be a whole number of shares")
    return int(number)


def _parse_date(value: str) -> str | None:
    text = _unquote(value)
    if text.casefold() in _EMPTY_VALUES:
        return None
    text = text.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise PortfolioError("invalid_date", "date must be YYYY-MM-DD")


def _optional_text(value: str) -> str | None:
    text = _unquote(value)
    if text.casefold() in _EMPTY_VALUES:
        return None
    return clean_text(text)


def _code_value(value: str) -> str:
    text = _unquote(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text


def parse_csv_text(text: object, *, today: date | None = None) -> dict[str, Any]:
    """Parse and normalize rows; never writes to disk."""
    payload = check_text_payload(text)
    assert isinstance(payload, str)
    cleaned = payload.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    numbered = [
        (number, line)
        for number, line in enumerate(cleaned.split("\n"), start=1)
        if line.strip()
    ]
    if not numbered:
        raise PortfolioError("empty_text", "text contains no holdings rows", field="text")

    header_index, delimiter, mapping, header_width = _find_header(numbered)
    header_cells = _split_line(numbered[header_index][1], delimiter)

    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row_index in range(header_index + 1, len(numbered)):
        line_number, line = numbered[row_index]
        try:
            cells = _split_line(line, delimiter)
        except csv.Error:
            rejected.append({"line": line_number, "reason": "unparsable_row"})
            continue
        if not cells or all(not cell.strip() for cell in cells):
            continue
        if all(field in _map_header(cells) for field in REQUIRED_COLUMNS):
            continue  # repeated header from a multi-page export
        if len(cells) > header_width:
            cells = _merge_thousands(cells, header_width)
        if len(cells) < header_width or any(
            cell.strip() for cell in cells[header_width:]
        ):
            rejected.append({"line": line_number, "reason": "column_count_mismatch"})
            continue

        try:
            code = normalize_symbol(_code_value(_cell(cells, mapping["code"]))).canonical
            qty = _parse_int(_cell(cells, mapping["qty"]))
            cost = _parse_number(_cell(cells, mapping["cost"]))
            name_value = _unquote(_cell(cells, mapping["name"]))
            raw: dict[str, Any] = {
                "code": code,
                "name": "" if name_value.casefold() in _EMPTY_VALUES else name_value,
                "qty": qty if qty is not None else _cell(cells, mapping["qty"]),
                "cost_price": cost if cost is not None else _cell(cells, mapping["cost"]),
            }
            if "available" in mapping:
                available = _parse_int(_cell(cells, mapping["available"]))
                raw["available_qty"] = available
            if "opened_date" in mapping:
                raw["opened_date"] = _parse_date(_cell(cells, mapping["opened_date"]))
            if "industry" in mapping:
                raw["industry"] = _optional_text(_cell(cells, mapping["industry"]))
            if "note" in mapping:
                raw["note"] = _optional_text(_cell(cells, mapping["note"]))

            position = validate_position(raw, today=today)
        except PortfolioError as exc:
            rejected.append(
                {
                    "line": line_number,
                    "reason": exc.code,
                    **({"field": exc.field} if exc.field else {}),
                }
            )
            continue

        if position["code"] in seen:
            rejected.append(
                {"line": line_number, "reason": "duplicate_code", "field": "code"}
            )
            continue
        seen.add(position["code"])
        rows.append(position)

    columns = {
        field: clean_text(_cell(header_cells, index))[:20]
        for field, index in mapping.items()
    }
    return {
        "rows": rows,
        "rejected": rejected,
        "count": len(rows),
        "rejected_count": len(rejected),
        "columns": columns,
    }
