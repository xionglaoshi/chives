"""Market-level upstream adapters for T141.

Every parser works on a recorded fixture in ``tests/fixtures/market``.  The
public hosts are read-only; nothing here writes state or opens a connection to
a forbidden host.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from . import config
from .codes import InvalidCode, normalize_code
from .transport import HostGovernor, UpstreamError

LEGU_HOST = "legulegu.com"
SINA_NODE_HOST = "vip.stock.finance.sina.com.cn"
SINA_MONEY_HOST = "money.finance.sina.com.cn"
DATACENTER_HOST = "datacenter-web.eastmoney.com"
THS_HOST = "data.10jqka.com.cn"
THS_SUMMARY_HOST = "q.10jqka.com.cn"
HKEX_HOST = "www.hkex.com.hk"
HKEXNEWS_HOST = "www3.hkexnews.hk"

SINA_REFERER = {"Referer": "https://finance.sina.com.cn"}
THS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.10jqka.com.cn/market/longhu/",
}
HKEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.hkex.com.hk/",
}

SINA_MOVER_SORTS = {"gainers": ("changepercent", "0"), "losers": ("changepercent", "1"), "active": ("amount", "0")}
SINA_BOARD_PATHS = {"industry": "/q/view/newSinaHy.php", "concept": "/q/view/newFLJK.php"}
THS_PATHS = {
    "zt": "/dataapi/limit_up/limit_up_pool",
    "zb": "/dataapi/limit_up/limit_up",
    "ladder": "/dataapi/limit_up/continuous_limit_up",
}
THS_FIELDS = "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004"

_LEGU_TIME_RE = re.compile(r'class="market-activity-time"[^>]*>\s*([^<]+?)\s*<')
_LEGU_ACTIVITY_RE = re.compile(r'class="metric-label">\s*活跃度\s*</span>\s*<span class="metric-value">\s*([0-9.]+)%')
_HOLDING_DATE_RE = re.compile(r"Shareholding Date:\s*(\d{4}/\d{2}/\d{2})")
_HOLDING_ROW_RE = re.compile(
    r'<td class="col-stock-code">.*?mobile-list-body">\s*([^<]+?)\s*</div>'
    r'.*?<td class="col-stock-name">.*?mobile-list-body">\s*([^<]+?)\s*</div>'
    r'.*?<td class="col-shareholding">.*?mobile-list-body">\s*([\d,]+)\s*</div>'
    r'.*?<td class="col-shareholding-percent">.*?mobile-list-body">\s*([\d.]+)%',
    re.DOTALL,
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


def _legu_count(html: str, label: str) -> int | None:
    match = re.search(rf"<td>\s*{label}\s*</td>\s*<td[^>]*>\s*(-?[0-9]+)\s*</td>", html)
    return None if match is None else int(match.group(1))


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    to_dict = getattr(frame, "to_dict", None)
    if to_dict is None:
        return list(frame) if isinstance(frame, list) else []
    if getattr(frame, "empty", False):
        return []
    return list(to_dict(orient="records"))


def _load_json(text: str, label: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise UpstreamError("invalid_json", circuit=False) from exc


# --------------------------------------------------------------------------- breadth


@dataclass(frozen=True)
class LeguActivity:
    up: int
    down: int
    flat: int
    suspended: int | None
    limit_up: int | None
    limit_down: int | None
    active_pct: float | None
    as_of: datetime | None


def parse_legu_activity(html: str) -> LeguActivity:
    if not isinstance(html, str) or not html.strip():
        raise UpstreamError("parse_empty", circuit=False)
    up = _legu_count(html, "上涨")
    down = _legu_count(html, "下跌")
    flat = _legu_count(html, "平盘")
    if up is None or down is None or flat is None:
        raise UpstreamError("parse_empty", circuit=False)
    activity = None
    match = _LEGU_ACTIVITY_RE.search(html)
    if match is not None:
        activity = _number(match.group(1))
    stamp = None
    time_match = _LEGU_TIME_RE.search(html)
    if time_match is not None:
        try:
            stamp = datetime.strptime(time_match.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=config.CN_TZ)
        except ValueError:
            stamp = None
    return LeguActivity(
        up=up,
        down=down,
        flat=flat,
        suspended=_legu_count(html, "停牌"),
        limit_up=_legu_count(html, "涨停"),
        limit_down=_legu_count(html, "跌停"),
        active_pct=activity,
        as_of=stamp,
    )


# --------------------------------------------------------------------------- sina


def parse_sina_movers(payload: Any, *, include_bj: bool = False) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().lower()
        if len(symbol) != 8 or symbol[:2] not in {"sh", "sz", "bj"}:
            continue
        if not include_bj and symbol.startswith("bj"):
            continue
        try:
            code = normalize_code(symbol[2:])
        except InvalidCode:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        change_pct = _number(item.get("changepercent"))
        if change_pct is None:
            price = _number(item.get("trade"))
            settlement = _number(item.get("settlement"))
            if price is not None and settlement:
                change_pct = (price / settlement - 1.0) * 100.0
        rows.append(
            {
                "code": code.canonical,
                "name": name,
                "price": _number(item.get("trade")),
                "change_pct": change_pct,
                "amount_yuan": _number(item.get("amount")),
                "turnover_pct": _number(item.get("turnoverratio")),
                "ticktime": str(item.get("ticktime") or "").strip() or None,
            }
        )
    return rows


def parse_sina_board_js(text: str) -> list[dict[str, Any]]:
    if not isinstance(text, str) or "{" not in text or "}" not in text:
        raise UpstreamError("invalid_format", circuit=False)
    body = text[text.index("{") : text.rindex("}") + 1]
    payload = _load_json(body, "boards")
    if not isinstance(payload, dict):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for value in payload.values():
        if not isinstance(value, str):
            continue
        parts = value.split(",", 12)
        if len(parts) < 13:
            continue
        code, name = parts[0].strip(), parts[1].strip()
        if not code or not name:
            continue
        change_pct = _number(parts[5])
        if change_pct is None:
            price, change = _number(parts[3]), _number(parts[4])
            if price is not None and change is not None and price != change:
                change_pct = change / (price - change) * 100.0
        leader_code = None
        try:
            leader_code = normalize_code(parts[8].strip()[2:] if len(parts[8].strip()) == 8 else parts[8].strip()).canonical
        except InvalidCode:
            leader_code = None
        rows.append(
            {
                "code": code,
                "name": name,
                "change_pct": change_pct,
                "amount_yuan": _number(parts[7]),
                "member_count": _int(parts[2]),
                "leader": {
                    "code": leader_code,
                    "name": parts[12].strip() or None,
                    "change_pct": _number(parts[9]),
                },
            }
        )
    if not rows:
        raise UpstreamError("parse_empty", circuit=False)
    return rows


def parse_sina_node(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().lower()
        if len(symbol) != 8 or symbol[:2] not in {"sh", "sz", "bj"}:
            continue
        try:
            code = normalize_code(symbol[2:])
        except InvalidCode:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "code": code.canonical,
                "name": name,
                "price": _number(item.get("trade")),
                "change_pct": _number(item.get("changepercent")),
                "amount_yuan": _number(item.get("amount")),
                "turnover_pct": _number(item.get("turnoverratio")),
            }
        )
    return rows


# --------------------------------------------------------------------------- flows


def _flow_row(item: dict[str, Any], code: str, name: str) -> dict[str, Any]:
    net = _number(item.get("r0_net"))
    ratio = _number(item.get("r0_ratio"))
    return {
        "code": code,
        "name": name,
        "main_net_yuan": net,
        "main_net_pct": None if ratio is None else ratio * 100.0,
        "change_pct": None if _number(item.get("changeratio")) is None else _number(item.get("changeratio")) * 100.0,
        "amount_yuan": _number(item.get("amount")),
    }


def parse_sina_flow_boards(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = str(item.get("category") or "").strip()
        name = str(item.get("name") or "").strip()
        if not code or not name:
            continue
        row = _flow_row(item, code, name)
        if row["main_net_yuan"] is None:
            inflow, outflow = _number(item.get("inamount")), _number(item.get("outamount"))
            if inflow is not None and outflow is not None:
                row["main_net_yuan"] = inflow - outflow
        ratio = _number(item.get("ratioamount"))
        change = _number(item.get("avg_changeratio"))
        row["main_net_pct"] = None if ratio is None else ratio * 100.0
        row["change_pct"] = None if change is None else change * 100.0
        row["amount_yuan"] = _number(item.get("amount"))
        rows.append(row)
    if not rows:
        raise UpstreamError("parse_empty", circuit=False)
    return rows


def parse_sina_stock_flows(payload: Any, *, include_bj: bool = False) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().lower()
        if len(symbol) != 8 or symbol[:2] not in {"sh", "sz", "bj"}:
            continue
        if not include_bj and symbol.startswith("bj"):
            continue
        try:
            code = normalize_code(symbol[2:]).canonical
        except InvalidCode:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(_flow_row(item, code, name))
    return rows


def parse_sina_stock_history(payload: Any, *, days: int) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_day = str(item.get("opendate") or "")[:10]
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            continue
        net = _number(item.get("r0_net"))
        ratio = _number(item.get("r0_ratio"))
        amount = None
        if net is not None and ratio:
            amount = round(net / ratio, 2)
        rows.append(
            {
                "date": day.isoformat(),
                "close": _number(item.get("trade")),
                "main_net_yuan": net,
                "main_net_pct": None if ratio is None else ratio * 100.0,
                "change_pct": None if _number(item.get("changeratio")) is None else _number(item.get("changeratio")) * 100.0,
                "amount_yuan": amount,
            }
        )
        if len(rows) >= days:
            break
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows


# --------------------------------------------------------------------------- limit pool


def _ths_streak(text: Any) -> int | None:
    value = str(text or "").strip()
    if not value:
        return None
    if value == "首板":
        return 1
    match = re.match(r"(\d+)\s*天\s*(\d+)\s*板", value)
    if match:
        return int(match.group(2))
    match = re.match(r"(\d+)\s*板", value)
    return int(match.group(1)) if match else None


def _ths_time(value: Any) -> str | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, config.CN_TZ).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def parse_ths_pool(payload: Any, *, kind: str) -> tuple[int, list[dict[str, Any]]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, list):
        raise UpstreamError("parse_empty", circuit=False)
    page = data.get("page") if isinstance(data, dict) else None
    total = _int(page.get("total")) if isinstance(page, dict) else None
    rows: list[dict[str, Any]] = []
    for item in info:
        if not isinstance(item, dict):
            continue
        raw_code = str(item.get("code") or "").strip()
        try:
            code = normalize_code(raw_code).canonical
        except InvalidCode:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "code": code,
                "name": name,
                "price": _number(item.get("latest")),
                "change_pct": _number(item.get("change_rate")),
                "amount_yuan": None,
                "turnover_pct": _number(item.get("turnover_rate")),
                "streak": _ths_streak(item.get("high_days")) if kind == "zt" else None,
                "first_seal_time": _ths_time(item.get("first_limit_up_time")) if kind == "zt" else None,
                "broken_times": _int(item.get("open_num")),
                "industry": None,
                "theme": (str(item.get("reason_type")).strip() or None) if item.get("reason_type") else None,
                "seal_amount_yuan": _number(item.get("order_amount")),
                "seal_volume_shares": _int(item.get("order_volume")),
                "board_type": item.get("limit_up_type"),
            }
        )
    if total is None:
        total = len(rows)
    return total, rows


def parse_ths_ladder(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise UpstreamError("parse_empty", circuit=False)
    tiers: list[dict[str, Any]] = []
    max_streak = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        streak = _int(item.get("height"))
        if streak is None:
            continue
        codes = item.get("code_list")
        rows: list[dict[str, Any]] = []
        for entry in codes if isinstance(codes, list) else []:
            if not isinstance(entry, dict):
                continue
            try:
                code = normalize_code(str(entry.get("code") or "")).canonical
            except InvalidCode:
                continue
            rows.append({"code": code, "name": str(entry.get("name") or "").strip(), "streak": streak})
        tiers.append({"streak": streak, "count": _int(item.get("number")) or len(rows), "rows": rows})
        max_streak = max(max_streak, streak)
    tiers.sort(key=lambda tier: tier["streak"], reverse=True)
    if not tiers:
        raise UpstreamError("parse_empty", circuit=False)
    return {"max_streak": max_streak, "tiers": tiers}


# --------------------------------------------------------------------------- datacenter


def datacenter_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise UpstreamError("invalid_format", circuit=False)
    if payload.get("success") is False:
        raise UpstreamError("upstream_rejected", circuit=False)
    result = payload.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    if data is None:
        return []
    if not isinstance(data, list):
        raise UpstreamError("invalid_format", circuit=False)
    return [row for row in data if isinstance(row, dict)]


def normalize_dragon_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(raw.get("SECURITY_CODE") or ""),
        "name": raw.get("SECURITY_NAME_ABBR"),
        "close": _number(raw.get("CLOSE_PRICE")),
        "change_pct": _number(raw.get("CHANGE_RATE")),
        "net_buy_yuan": _number(raw.get("BILLBOARD_NET_AMT")),
        "buy_amount_yuan": _number(raw.get("BILLBOARD_BUY_AMT")),
        "sell_amount_yuan": _number(raw.get("BILLBOARD_SELL_AMT")),
        "turnover_yuan": _number(raw.get("ACCUM_AMOUNT")),
        "reason": raw.get("EXPLANATION"),
    }


def normalize_seat(raw: dict[str, Any], *, side: str, rank: int) -> dict[str, Any]:
    return {
        "seat": raw.get("OPERATEDEPT_NAME"),
        "side": side,
        "buy_yuan": _number(raw.get("BUY")),
        "sell_yuan": _number(raw.get("SELL")),
        "net_yuan": _number(raw.get("NET")),
        "rank": rank,
        "reason": raw.get("EXPLANATION"),
        "trade_id": raw.get("TRADE_ID"),
    }


def normalize_block_row(raw: dict[str, Any]) -> dict[str, Any]:
    premium = _number(raw.get("PREMIUM_RATIO"))
    return {
        "trade_date": str(raw.get("TRADE_DATE") or "")[:10] or None,
        "name": raw.get("SECURITY_NAME_ABBR"),
        "close_price": _number(raw.get("CLOSE_PRICE")),
        "deal_price": _number(raw.get("DEAL_PRICE")),
        "premium_pct": None if premium is None else round(premium * 100.0, 6),
        "deal_volume_shares": _int(raw.get("DEAL_VOLUME")),
        "deal_amount_yuan": _number(raw.get("DEAL_AMT")),
        "buyer_seat": raw.get("BUYER_NAME"),
        "seller_seat": raw.get("SELLER_NAME"),
    }


def normalize_margin_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": str(raw.get("DATE") or "")[:10] or None,
        "financing_balance_yuan": _number(raw.get("RZYE")),
        "financing_buy_yuan": _number(raw.get("RZMRE")),
        "financing_repay_yuan": _number(raw.get("RZCHE")),
        "short_balance_yuan": _number(raw.get("RQYE")),
        "short_volume_shares": _int(raw.get("RQYL")),
        "margin_total_balance_yuan": _number(raw.get("RZRQY"))
        if _number(raw.get("RZRQY")) is not None
        else _number(raw.get("RZRQYE")),
    }


# --------------------------------------------------------------------------- hkex


def parse_hkex_daily(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or "[" not in text:
        raise UpstreamError("invalid_format", circuit=False)
    payload = _load_json(text[text.index("[") : text.rindex("]") + 1], "hkex")
    if not isinstance(payload, list):
        raise UpstreamError("invalid_format", circuit=False)
    channels: dict[str, dict[str, Any]] = {}
    top_active: dict[str, list[dict[str, Any]]] = {}
    report_date = None
    for block in payload:
        if not isinstance(block, dict):
            continue
        market = str(block.get("market") or "")
        if market not in {"SSE Northbound", "SZSE Northbound"}:
            continue
        channel = "sh" if market.startswith("SSE") else "sz"
        report_date = report_date or block.get("date")
        for item in block.get("content") or []:
            table = item.get("table") if isinstance(item, dict) else None
            if not isinstance(table, dict):
                continue
            schema = table.get("schema")
            columns = schema[0] if isinstance(schema, list) and schema and isinstance(schema[0], list) else []
            values = []
            for row in table.get("tr") or []:
                cells = row.get("td") if isinstance(row, dict) else None
                cells = cells or []
                if len(cells) == 1 and isinstance(cells[0], list) and len(cells[0]) > 1:
                    values.append([str(value).strip() for value in cells[0]])
                else:
                    values.append([str(cell[0]).strip() if isinstance(cell, list) and cell else "" for cell in cells])
            if table.get("classname") == "tradingTable" and columns:
                flat = [cells[0] for cells in values if cells]
                record = dict(zip(columns, flat))
                channels[channel] = {
                    "total_turnover_yuan": _scaled(record.get("Total Turnover"), 1_000_000),
                    "etf_turnover_yuan": _scaled(record.get("ETF Turnover"), 1_000_000),
                    "trade_count": _int(record.get("Total Trade Count")),
                }
            elif table.get("classname") == "top10Table" and columns:
                rows = []
                for cells in values:
                    record = dict(zip(columns, cells))
                    raw_code = str(record.get("Stock Code") or "").strip()
                    # HKEX prints Shenzhen codes without leading zeros ("2463" = 002463, "333" = 000333).
                    if raw_code.isdigit() and len(raw_code) < 6:
                        raw_code = raw_code.zfill(6)
                    try:
                        code = normalize_code(raw_code).canonical
                    except InvalidCode:
                        code = raw_code
                    rows.append(
                        {
                            "rank": _int(record.get("Rank")),
                            "code": code,
                            "name": record.get("Stock Name"),
                            "turnover_yuan": _scaled(record.get("Total Turnover"), 1),
                        }
                    )
                top_active[channel] = rows
    if not channels:
        raise UpstreamError("parse_empty", circuit=False)
    return {"date": report_date, "channels": channels, "top_active": top_active}


def _scaled(value: Any, factor: float) -> float | None:
    number = _number(value)
    return None if number is None else round(number * factor, 2)


def parse_hkex_holdings(html: str) -> dict[str, Any]:
    if not isinstance(html, str) or "col-stock-code" not in html:
        raise UpstreamError("parse_empty", circuit=False)
    match = _HOLDING_DATE_RE.search(html)
    if match is None:
        raise UpstreamError("parse_empty", circuit=False)
    report_date = datetime.strptime(match.group(1), "%Y/%m/%d").date()
    rows: list[dict[str, Any]] = []
    for code_text, name, shares, pct in _HOLDING_ROW_RE.findall(html):
        a_code = re.search(r"#\s*(\d{6})", name)
        raw_code = a_code.group(1) if a_code else code_text
        try:
            code = normalize_code(raw_code).canonical
        except InvalidCode:
            continue
        rows.append(
            {
                "code": code,
                "name": re.sub(r"\s*\(\s*A?\s*#\s*\d{6}\s*\)?\s*$", "", name).strip(),
                "shareholding_shares": _int(shares),
                "shareholding_pct": _number(pct),
            }
        )
    return {"date": report_date, "rows": rows}


def quarter_end(day: date) -> date:
    month = ((day.month - 1) // 3 + 1) * 3
    if month == 12:
        return date(day.year, 12, 31)
    return date(day.year, month + 1, 1) - timedelta(days=1)


def previous_quarter_end(day: date) -> date:
    current = quarter_end(day)
    first_month = current.month - 2
    return date(current.year, first_month, 1) - timedelta(days=1)


def next_quarter_end(day: date) -> date:
    current = quarter_end(day)
    month = current.month + 3
    year = current.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return quarter_end(date(year, month, 1))


def holdings_change(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prior = {row["code"]: row for row in previous}
    output = []
    for row in current:
        old = prior.get(row["code"])
        shares = row.get("shareholding_shares")
        pct = row.get("shareholding_pct")
        old_shares = old.get("shareholding_shares") if old else None
        old_pct = old.get("shareholding_pct") if old else None
        output.append(
            {
                **row,
                "change_shares": None if shares is None or old_shares is None else shares - old_shares,
                "change_pct_points": None if pct is None or old_pct is None else round(pct - old_pct, 4),
            }
        )
    return output


# --------------------------------------------------------------------------- facade


class MarketSources:
    """All market-level reads used by the seven T141 capabilities."""

    def __init__(self, governor: HostGovernor) -> None:
        self.governor = governor

    # -- breadth --------------------------------------------------------
    def legu_activity(self) -> LeguActivity:
        text = self.governor.request(
            LEGU_HOST,
            "/stockdata/market-activity",
            headers={"User-Agent": THS_HEADERS["User-Agent"], "Referer": "https://legulegu.com/"},
            encoding="utf-8",
        )
        return parse_legu_activity(text)

    # -- sina -----------------------------------------------------------
    def _sina_json(self, path: str, params: Mapping[str, Any]) -> Any:
        text = self.governor.request(
            SINA_NODE_HOST, path, params=params, headers=SINA_REFERER, encoding="utf-8"
        )
        return _load_json(text, "sina")

    def sina_movers(self, kind: str, *, include_bj: bool, limit: int) -> list[dict[str, Any]]:
        sort, asc = SINA_MOVER_SORTS[kind]
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in range(1, 6):
            payload = self._sina_json(
                "/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
                {"node": "hs_a", "sort": sort, "asc": asc, "num": 100, "page": page},
            )
            for row in parse_sina_movers(payload, include_bj=include_bj):
                if row["code"] in seen:
                    continue
                seen.add(row["code"])
                rows.append(row)
            if len(rows) >= limit:
                break
        if not rows:
            raise UpstreamError("parse_empty", circuit=False)
        return rows[:limit]

    def ths_industry_summary(self) -> list[dict[str, Any]]:
        """Industry-wide table with up/down counts, amount, net inflow and leader."""
        import akshare as ak

        frame = self.governor.run_external(
            THS_SUMMARY_HOST,
            ak.stock_board_industry_summary_ths,
            timeout=config.AKSHARE_TIMEOUT,
        )
        return _frame_records(frame)

    def sina_boards(self, kind: str) -> list[dict[str, Any]]:
        params = {"param": "class"} if kind == "concept" else None
        text = self.governor.request(
            SINA_NODE_HOST,
            SINA_BOARD_PATHS[kind],
            params=params,
            headers=SINA_REFERER,
            encoding="gbk",
        )
        return parse_sina_board_js(text)

    def sina_node(self, node: str, *, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pages = max(1, (limit + 99) // 100)
        for page in range(1, pages + 1):
            payload = self._sina_json(
                "/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
                {"node": node, "sort": "amount", "asc": 0, "num": min(100, limit), "page": page},
            )
            rows.extend(parse_sina_node(payload))
        if not rows:
            raise UpstreamError("parse_empty", circuit=False)
        return rows[:limit]

    def sina_sector_flows(self, kind: str) -> list[dict[str, Any]]:
        payload = self._sina_json(
            "/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk",
            {"page": 1, "num": 100, "sort": "netamount", "asc": 0 if kind == "in" else 1, "fenlei": 0},
        )
        return parse_sina_flow_boards(payload)

    def sina_stock_flows(self, kind: str, *, include_bj: bool, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        pages = max(1, (limit + 49) // 50)
        if not include_bj:
            pages = max(2, pages)
        for page in range(1, pages + 1):
            payload = self._sina_json(
                "/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj",
                {
                    "page": page,
                    "num": 50,
                    "sort": "r0_net",
                    "asc": 0 if kind == "in" else 1,
                    "bankuai": "",
                    "shichang": "",
                },
            )
            for row in parse_sina_stock_flows(payload, include_bj=include_bj):
                if row["code"] in seen:
                    continue
                seen.add(row["code"])
                rows.append(row)
            if len(rows) >= limit:
                break
        if not rows:
            raise UpstreamError("parse_empty", circuit=False)
        return rows[:limit]

    def sina_stock_history(self, code: Any, *, days: int) -> list[dict[str, Any]]:
        payload = self._sina_json(
            "/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs",
            {"daima": code.symbol, "page": 1, "num": days, "sort": "opendate", "asc": 0},
        )
        return parse_sina_stock_history(payload, days=days)

    # -- limit pool -----------------------------------------------------
    def ths_pool(self, kind: str, *, day: date, limit: int) -> tuple[int, list[dict[str, Any]]]:
        page_size = min(200, limit)
        rows: list[dict[str, Any]] = []
        for page in range(1, (limit + page_size - 1) // page_size + 1):
            payload = self._sina_json_ths(
                THS_PATHS[kind],
                {
                    "page": page,
                    "limit": page_size,
                    "field": THS_FIELDS,
                    "filter": "HS,GEM2STAR",
                    "order_field": 330324,
                    "order_type": 0,
                    "date": day.strftime("%Y%m%d"),
                },
            )
            total, batch = parse_ths_pool(payload, kind=kind)
            rows.extend(batch)
            if len(rows) >= total or not batch:
                break
        return total, rows[:limit]

    def ths_ladder(self, *, day: date) -> dict[str, Any]:
        payload = self._sina_json_ths(
            THS_PATHS["ladder"],
            {"page": 1, "limit": 200, "filter": "HS,GEM2STAR", "date": day.strftime("%Y%m%d")},
        )
        return parse_ths_ladder(payload)

    def _sina_json_ths(self, path: str, params: Mapping[str, Any]) -> Any:
        text = self.governor.request(
            THS_HOST, path, params=params, headers=THS_HEADERS, encoding="utf-8"
        )
        payload = _load_json(text, "ths")
        if isinstance(payload, dict) and payload.get("status_code") not in (0, None):
            raise UpstreamError("upstream_rejected", circuit=False)
        return payload

    # -- datacenter -----------------------------------------------------
    def datacenter(self, report: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        text = self.governor.request(
            DATACENTER_HOST,
            "/api/data/v1/get",
            params={"reportName": report, "columns": "ALL", "source": "WEB", "client": "WEB", **params},
            headers={"Referer": "https://data.eastmoney.com/"},
            encoding="utf-8",
        )
        return datacenter_rows(_load_json(text, "datacenter"))

    # -- hkex -----------------------------------------------------------
    def hkex_daily(self, day: date) -> dict[str, Any]:
        text = self.governor.request(
            HKEX_HOST,
            f"/eng/csm/DailyStat/data_tab_daily_{day.strftime('%Y%m%d')}e.js",
            headers=HKEX_HEADERS,
            encoding="utf-8",
        )
        return parse_hkex_daily(text)

    def hkex_holdings(self, channel: str, *, day: date | None = None) -> dict[str, Any]:
        path = "/sdw/search/mutualmarket.aspx"
        params = {"t": channel}
        html = self.governor.request(
            HKEXNEWS_HOST, path, params=params, headers=HKEX_HEADERS, encoding="utf-8"
        )
        parsed = parse_hkex_holdings(html)
        if day is None or day >= parsed["date"]:
            return parsed
        guard = 0
        while parsed["date"] > day and guard < 8:
            form = _hkex_form(html)
            form["txtShareholdingDate"] = parsed["date"].isoformat().replace("-", "/")
            form["originalShareholdingDate"] = form["txtShareholdingDate"]
            # The channel lives in the query string; without it the site answers with
            # the Shanghai list, so a Shenzhen "previous quarter" would be Shanghai data.
            html = self.governor.request_form(
                HKEXNEWS_HOST, path, form=form, params=params, headers=HKEX_HEADERS, encoding="utf-8"
            )
            nxt = parse_hkex_holdings(html)
            if nxt["date"] >= parsed["date"]:
                break
            parsed = nxt
            guard += 1
        return parsed


_HIDDEN_RE = re.compile(r'name="(__VIEWSTATE|__VIEWSTATEGENERATOR|today)"[^>]*value="([^"]*)"')


def _hkex_form(html: str) -> dict[str, str]:
    values = {name: value for name, value in _HIDDEN_RE.findall(html)}
    return {
        "__VIEWSTATE": values.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": values.get("__VIEWSTATEGENERATOR", ""),
        "today": values.get("today", ""),
        "sortBy": "stockcode",
        "sortDirection": "asc",
        "alertMsg": "",
        "btnSearch": "",
    }
