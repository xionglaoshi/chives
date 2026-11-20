"""Shared offline test helpers (no network, no real time)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from dataclasses import dataclass

from market_watch.models import CN_TZ

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class FetchResult:
    text: str
    url: str
    fetched_at: datetime
NOW = datetime(2026, 11, 3, 10, 30, 0, tzinfo=CN_TZ)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(hour: int, minute: int = 0, second: int = 0, day: int = 3) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=CN_TZ)


class FakeClient:
    """Route table keyed by source and a path prefix; records every request."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Callable[[str, dict[str, Any]], str]]] = []
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.health_payload: dict[str, dict[str, Any]] = {}

    def add(self, source: str, prefix: str, payload: str | Callable[[str, dict[str, Any]], str]) -> "FakeClient":
        if isinstance(payload, str):
            text = payload

            def reader(path: str, params: dict[str, Any], _text: str = text) -> str:
                return _text

            self.routes.append((source, prefix, reader))
        else:
            self.routes.append((source, prefix, payload))
        return self

    def _match(self, source: str, path: str, params: dict[str, Any]) -> str:
        for route_source, prefix, reader in self.routes:
            if route_source == source and path.startswith(prefix):
                return reader(path, params)
        raise AssertionError(f"unexpected request {source} {path} {params}")

    def get(
        self,
        source: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        *,
        encoding: str = "utf-8",
        cache_ttl: float = 0.0,
        now: Optional[datetime] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> FetchResult:
        values = dict(params or {})
        self.calls.append((source, path, values))
        text = self._match(source, path, values)
        return FetchResult(text=text, url=f"fake://{source}{path}", fetched_at=now or NOW)

    def get_json(
        self,
        source: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        *,
        cache_ttl: float = 0.0,
        now: Optional[datetime] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[Any, FetchResult]:
        from market_watch.gateway import SourceError

        result = self.get(
            source,
            path,
            params,
            cache_ttl=cache_ttl,
            now=now,
            headers=headers,
        )
        try:
            return json.loads(result.text), result
        except json.JSONDecodeError as exc:
            raise SourceError("invalid_json", f"fake upstream not json: {exc}") from exc

    def health(self, now: datetime) -> dict[str, dict[str, Any]]:
        return dict(self.health_payload)


    # -- fake gateway -----------------------------------------------------
    def call(self, tool: str, args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"status": "ok", "as_of": "2026-11-03T10:30:00+08:00", "data": self.data(tool, args or {})}

    def data(self, tool: str, args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        args = dict(args or {})
        if tool == "market_quote":
            return {"quotes": self._quotes([str(code) for code in args.get("codes") or []])}
        if tool == "market_overview":
            return self._overview()
        if tool == "market_limit_pool":
            return self._limit_pool(args)
        if tool == "market_sectors":
            return self._sectors(args)
        if tool == "market_movers":
            return self._movers(args)
        if tool == "market_fund_flow":
            return self._flows(args)
        if tool == "market_bars":
            return self._bars(args)
        raise AssertionError(f"unexpected gateway tool {tool} {args}")

    def _quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        if not codes:
            return []
        symbols = ",".join(
            ("sh" if code.endswith(".SH") else "bj" if code.endswith(".BJ") else "sz")
            + code.split(".")[0]
            for code in codes
        )
        text = self.get("tencent", "/q=" + symbols, None, encoding="gbk").text
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("v_") or "=" not in line:
                continue
            head, body = line.split("=", 1)
            exchange = head[2:4]
            digits = head[4:]
            fields = body.strip().strip('";').split("~")
            if len(fields) < 38 or not fields[3]:
                continue
            try:
                price = float(fields[3])
                prev = float(fields[4])
            except ValueError:
                continue
            if price <= 0 or prev <= 0:
                continue
            code = f"{digits}.{exchange.upper()}"
            rows.append(
                {
                    "code": code,
                    "name": fields[1],
                    "price": price,
                    "prev_close": prev,
                    "open": float(fields[5] or price),
                    "high": float(fields[33] or price),
                    "low": float(fields[34] or price),
                    "change_pct": float(fields[32] or 0.0),
                    "amount_yuan": float(fields[37] or 0.0) * 10000.0,
                    "volume_shares": int(float(fields[6] or 0)) * 100,
                    "quote_time": "2026-11-03T10:30:00+08:00",
                    "limit_up": float(fields[47]) if len(fields) > 47 and float(fields[47]) > 0 else None,
                    "limit_down": float(fields[48]) if len(fields) > 48 and float(fields[48]) > 0 else None,
                }
            )
        return rows

    def _overview(self) -> dict[str, Any]:
        quotes = self._quotes(["000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000852.SH", "000688.SH"])
        breadth_text = self.get("eastmoney", "/api/qt/ulist.np/get", None).text
        up = down = flat = 0
        try:
            payload = json.loads(breadth_text)
            for item in payload.get("data", {}).get("diff", []):
                up += int(item.get("f104") or 0)
                down += int(item.get("f105") or 0)
                flat += int(item.get("f106") or 0)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            pass
        counts = {}
        for kind, path in (("zt", "/getTopicZTPool"), ("zb", "/getTopicZBPool"), ("dt", "/getTopicDTPool")):
            try:
                text = self.get("eastmoney_ex", path, None).text
                payload = json.loads(text)
                counts[kind] = int(payload.get("data", {}).get("tc") or 0)
            except Exception:
                counts[kind] = None
        amount = sum(
            float(row.get("amount_yuan") or 0.0)
            for row in quotes
            if row["code"] in {"000001.SH", "399001.SZ"}
        )
        return {
            "indexes": [
                {key: row.get(key) for key in ("code", "name", "price", "prev_close", "change_pct", "amount_yuan")}
                for row in quotes
            ],
            "breadth": {
                "up_count": up or None,
                "down_count": down or None,
                "flat_count": flat or None,
                "suspended_count": None,
                "up_ratio_pct": None,
            },
            "limit": {
                "limit_up_count": counts.get("zt"),
                "limit_down_count": counts.get("dt"),
                "broken_count": counts.get("zb"),
                "max_streak": None,
                "seal_ratio_pct": None,
            },
            "amount_yuan": amount or None,
            "headlines": [],
            "as_of": "2026-11-03T10:30:00+08:00",
        }

    def _limit_pool(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("kind") or "zt")
        if kind == "stats":
            return {"days": []}
        path = {"zt": "/getTopicZTPool", "zb": "/getTopicZBPool", "dt": "/getTopicDTPool"}[kind]
        params = {"date": str(args.get("date") or "20261103").replace("-", "")}
        try:
            text = self.get("eastmoney_ex", path, params).text
            payload = json.loads(text)
        except Exception:
            raise
        data = payload.get("data") or {}
        rows = []
        for item in data.get("pool") or []:
            rows.append(
                {
                    "code": (
                        f"{item.get('c')}.SH"
                        if item.get("m") == 1
                        else f"{item.get('c')}.SZ"
                        if item.get("m") == 0
                        else f"{item.get('c')}.SH"
                        if str(item.get("c", "")).startswith("6")
                        else f"{item.get('c')}.SZ"
                    ),
                    "name": item.get("n"),
                    "price": None if item.get("p") is None else float(item["p"]) / 1000.0,
                    "change_pct": item.get("zdp"),
                    "amount_yuan": item.get("amount"),
                    "turnover_pct": item.get("hs"),
                    "streak": item.get("lbc"),
                    "first_seal_time": (
                        None
                        if item.get("fbt") is None
                        else f"{int(item['fbt']):06d}"[:2] + ":" + f"{int(item['fbt']):06d}"[2:4] + ":" + f"{int(item['fbt']):06d}"[4:6]
                    ),
                    "broken_times": item.get("zbc"),
                    "industry": item.get("hybk"),
                    "seal_amount_yuan": item.get("fund"),
                }
            )
        return {"date": str(args.get("date") or "2026-11-03"), "kind": kind, "count": int(data.get("tc") or 0), "rows": rows}

    def _sectors(self, args: dict[str, Any]) -> dict[str, Any]:
        code = args.get("code")
        kind = str(args.get("kind") or "industry")
        if code:
            fs = f"b:{code}"
            text = self.get("eastmoney", "/api/qt/clist/get", {"fs": fs, "pn": 1, "pz": 100}).text
            payload = json.loads(text)
            members = [
                {
                    "code": item.get("f12"),
                    "name": item.get("f14"),
                    "price": item.get("f2"),
                    "change_pct": item.get("f3"),
                    "amount_yuan": item.get("f6"),
                    "turnover_pct": item.get("f8"),
                }
                for item in payload.get("data", {}).get("diff", [])
            ]
            return {"code": code, "name": code, "members": members, "member_count": len(members)}
        fs = "m:90+t:3" if kind == "concept" else "m:90+t:2"
        text = self.get("eastmoney", "/api/qt/clist/get", {"fs": fs, "pn": 1, "pz": 100}).text
        payload = json.loads(text)
        rows = []
        for item in payload.get("data", {}).get("diff", []):
            rows.append(
                {
                    "code": item.get("f12"),
                    "name": item.get("f14"),
                    "change_pct": item.get("f3"),
                    "amount_yuan": item.get("f6"),
                    "up_count": item.get("f104"),
                    "down_count": item.get("f105"),
                    "member_count": None
                    if item.get("f104") is None
                    else int(item.get("f104") or 0) + int(item.get("f105") or 0) + int(item.get("f106") or 0),
                    "leader": {
                        "code": item.get("f140"),
                        "name": item.get("f128"),
                        "change_pct": item.get("f136"),
                    },
                }
            )
        return {"kind": kind, "rows": rows}

    def _movers(self, args: dict[str, Any]) -> dict[str, Any]:
        fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        if args.get("include_bj"):
            fs += ",m:0+t:81"
        text = self.get("eastmoney", "/api/qt/clist/get", {"fs": fs, "pn": 1, "pz": 100}).text
        payload = json.loads(text)
        rows = [
            {
                "code": item.get("f12"),
                "name": item.get("f14"),
                "price": item.get("f2"),
                "change_pct": item.get("f3"),
                "amount_yuan": item.get("f6"),
                "turnover_pct": item.get("f8"),
                "industry": item.get("f100"),
            }
            for item in payload.get("data", {}).get("diff", [])
        ]
        return {"kind": args.get("kind"), "rows": rows}

    def _flows(self, args: dict[str, Any]) -> dict[str, Any]:
        scope = args.get("scope")
        if scope == "sector":
            fs = "m:90+t:2"
        else:
            fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            if args.get("include_bj"):
                fs += ",m:0+t:81"
        text = self.get("eastmoney", "/api/qt/clist/get", {"fs": fs, "fid": "f62", "pn": 1, "pz": 100}).text
        payload = json.loads(text)
        rows = [
            {
                "code": item.get("f12"),
                "name": item.get("f14"),
                "main_net_yuan": item.get("f62"),
                "main_net_pct": item.get("f184"),
                "change_pct": item.get("f3"),
                "amount_yuan": item.get("f6"),
            }
            for item in payload.get("data", {}).get("diff", [])
        ]
        return {"scope": scope, "rows": rows}

    def _bars(self, args: dict[str, Any]) -> dict[str, Any]:
        text = self.get("eastmoney_hist", "/api/qt/stock/kline/get", {}).text
        payload = json.loads(text)
        bars = []
        for line in payload.get("data", {}).get("klines", []):
            parts = str(line).split(",")
            if len(parts) < 3:
                continue
            bars.append({"time": parts[0], "close": float(parts[2])})
        return {"bars": bars}

def standard_client() -> FakeClient:
    client = FakeClient()
    client.add("tencent", "/q=", fixture("tencent_indexes.txt"))
    client.add("eastmoney", "/api/qt/ulist.np/get", fixture("eastmoney_breadth.json"))
    client.add("eastmoney", "/api/qt/clist/get", fixture("eastmoney_boards.json"))
    client.add("eastmoney_ex", "/getTopicZTPool", fixture("eastmoney_zt_pool.json"))
    client.add("eastmoney_ex", "/getTopicZBPool", fixture("eastmoney_zb_pool.json"))
    client.add("eastmoney_ex", "/getTopicDTPool", fixture("eastmoney_dt_pool.json"))
    client.add("sw", "/institute-sw/api/index_publish/current/", fixture("sw_realtime.json"))
    client.add("sw", "/institute-sw/api/index_publish/details/component_stocks/", fixture("sw_components.json"))
    client.add("sw", "/institute-sw/api/index_publish/trend/", fixture("sw_history.json"))
    return client


def tencent_line(
    code: str,
    name: str,
    price: float,
    prev_close: float,
    amount_yuan: float,
    time_text: str = "20261103103000",
    limit_up: float | None = None,
    limit_down: float | None = None,
    change_pct: float | None = None,
) -> str:
    prefix = "sh" if code.endswith(".SH") else "bj" if code.endswith(".BJ") else "sz"
    digits = code.split(".")[0]
    change = (price / prev_close - 1) * 100 if change_pct is None else change_pct
    fields = [""] * 88
    fields[1] = name
    fields[3] = f"{price:.2f}"
    fields[4] = f"{prev_close:.2f}"
    fields[5] = f"{prev_close:.2f}"
    fields[6] = "100000"
    fields[30] = time_text
    fields[32] = f"{change:.2f}"
    fields[33] = f"{price:.2f}"
    fields[34] = f"{price:.2f}"
    fields[35] = f"{price:.2f}/100000/{amount_yuan:.0f}"
    fields[37] = f"{amount_yuan / 10000:.0f}"
    fields[47] = "-1" if limit_up is None else f"{limit_up:.2f}"
    fields[48] = "-1" if limit_down is None else f"{limit_down:.2f}"
    return f'v_{prefix}{digits}="' + "~".join(fields) + '";'


def tencent_payload(rows: list[dict[str, Any]]) -> str:
    return "\n".join(tencent_line(**row) for row in rows)


def breadth_payload(sh: tuple[int, int, int], sz: tuple[int, int, int]) -> str:
    return json.dumps(
        {
            "rc": 0,
            "data": {
                "total": 2,
                "diff": [
                    {"f12": "000001", "f14": "上证指数", "f2": 3600.0, "f3": -0.5,
                     "f104": sh[0], "f105": sh[1], "f106": sh[2]},
                    {"f12": "399001", "f14": "深证成指", "f2": 10800.0, "f3": -0.8,
                     "f104": sz[0], "f105": sz[1], "f106": sz[2]},
                ],
            },
        },
        ensure_ascii=False,
    )


def sw_payload(rows: list[tuple[str, str, float, float, float]]) -> str:
    results = [
        {
            "swindexcode": code,
            "swindexname": name,
            "l3": f"{prev:.2f}",
            "l4": f"{prev:.2f}",
            "l5": f"{amount_yuan / 1_000_000:.2f}",
            "l6": f"{price:.2f}",
            "l7": f"{prev:.2f}",
            "l8": f"{price:.2f}",
            "l11": "1000.00",
        }
        for code, name, prev, price, amount_yuan in rows
    ]
    return json.dumps(
        {"code": "200", "message": "ok", "data": {"count": len(results), "results": results}},
        ensure_ascii=False,
    )


def components_payload(members: list[tuple[str, str, float]]) -> str:
    results = [
        {"stockcode": code, "stockname": name, "newweight": str(weight),
         "beginningdate": "2021-12-13T08:00:00+08:00"}
        for code, name, weight in members
    ]
    return json.dumps(
        {"code": "200", "message": "ok", "data": {"count": len(results), "results": results}},
        ensure_ascii=False,
    )


def history_payload(closes: list[float]) -> str:
    from datetime import date, timedelta

    start = date(2026, 9, 1)
    data = [
        {
            "swindexcode": "801010",
            "bargaindate": (start + timedelta(days=index)).isoformat(),
            "openindex": value,
            "maxindex": value,
            "minindex": value,
            "closeindex": value,
            "hike": 0.0,
            "markup": 0.0,
            "bargainamount": 1.0,
            "bargainsum": 1.0,
        }
        for index, value in enumerate(closes)
    ]
    return json.dumps({"code": "200", "message": "ok", "data": data}, ensure_ascii=False)


def board_row(
    code: str,
    name: str,
    change_pct: float,
    amount_yuan: float,
    up: int,
    down: int,
    flat: int = 0,
    leader_code: str = "600000",
    leader_name: str = "领涨股",
    leader_change_pct: float = 5.0,
    price: float = 1000.0,
    prev_close: float | None = None,
    stamp: int = 1793691570,
) -> dict[str, Any]:
    return {
        "f12": code,
        "f14": name,
        "f2": price,
        "f3": change_pct,
        "f6": amount_yuan,
        "f18": prev_close if prev_close is not None else price / (1 + change_pct / 100),
        "f104": up,
        "f105": down,
        "f106": flat,
        "f124": stamp,
        "f128": leader_name,
        "f136": leader_change_pct,
        "f140": leader_code,
        "f141": 0,
    }


def board_list_payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"rc": 0, "data": {"total": len(rows), "diff": rows}}, ensure_ascii=False)


def mover_row(
    code: str,
    name: str,
    price: float,
    change_pct: float,
    amount_yuan: float,
    turnover_pct: float = 1.0,
    industry: str = "测试行业",
) -> dict[str, Any]:
    return {
        "f12": code,
        "f14": name,
        "f2": price,
        "f3": change_pct,
        "f6": amount_yuan,
        "f8": turnover_pct,
        "f100": industry,
    }


def movers_payload(rows: list[dict[str, Any]], total: int | None = None) -> str:
    return json.dumps(
        {"rc": 0, "data": {"total": total if total is not None else len(rows), "diff": rows}},
        ensure_ascii=False,
    )


def members_payload(rows: list[dict[str, Any]], total: int | None = None) -> str:
    return json.dumps(
        {"rc": 0, "data": {"total": total if total is not None else len(rows), "diff": rows}},
        ensure_ascii=False,
    )


def flow_row(
    code: str,
    name: str,
    main_net_yuan: float | None,
    main_net_pct: float | None = None,
    change_pct: float = 1.0,
    amount_yuan: float = 1e9,
) -> dict[str, Any]:
    pct = (
        main_net_yuan / amount_yuan * 100
        if main_net_pct is None and main_net_yuan is not None and amount_yuan
        else main_net_pct
    )
    return {
        "f12": code,
        "f14": name,
        "f3": change_pct,
        "f6": amount_yuan,
        "f62": main_net_yuan,
        "f184": pct,
    }


def flows_payload(rows: list[dict[str, Any]], total: int | None = None) -> str:
    return json.dumps(
        {"rc": 0, "data": {"total": total if total is not None else len(rows), "diff": rows}},
        ensure_ascii=False,
    )


def northbound_payload(
    date_text: str = "2026-11-03",
    *,
    net: tuple[float, float] = (0.0, 0.0),
    remain: tuple[float, float] = (0.0, 0.0),
) -> str:
    return json.dumps(
        {
            "rc": 0,
            "data": {
                "hk2sh": {
                    "status": 1,
                    "dayNetAmtIn": net[0],
                    "dayAmtRemain": remain[0],
                    "dayAmtThreshold": 5200000.0,
                    "date": date_text[5:],
                    "date2": date_text,
                },
                "hk2sz": {
                    "status": 1,
                    "dayNetAmtIn": net[1],
                    "dayAmtRemain": remain[1],
                    "dayAmtThreshold": 5200000.0,
                    "date": date_text[5:],
                    "date2": date_text,
                },
            },
        },
        ensure_ascii=False,
    )


def member_row(code: str, name: str, price: float, change_pct: float, amount_yuan: float) -> dict[str, Any]:
    return {
        "f12": code,
        "f14": name,
        "f2": price,
        "f3": change_pct,
        "f6": amount_yuan,
        "f8": 1.0,
        "f124": 1793691291,
    }


def board_history_payload(closes: list[float], start_day: str = "2026-09-01") -> str:
    from datetime import date, timedelta

    start = date.fromisoformat(start_day)
    lines = []
    for index, value in enumerate(closes):
        day = start + timedelta(days=index)
        lines.append(
            f"{day.isoformat()},{value:.2f},{value:.2f},{value:.2f},{value:.2f},1000,1000000.00"
        )
    return json.dumps({"rc": 0, "data": {"code": "BK0000", "name": "行业", "klines": lines}}, ensure_ascii=False)


def board_trend_payload(points: list[tuple[str, float]], pre_close: float = 1000.0) -> str:
    trends = [
        f"{stamp},{price:.2f},{price:.2f},{price:.2f},{price:.2f},1000,1000000.00,{price:.3f}"
        for stamp, price in points
    ]
    return json.dumps(
        {"rc": 0, "data": {"code": "BK0000", "name": "行业", "preClose": pre_close, "trends": trends}},
        ensure_ascii=False,
    )


def pool_stock(
    code: str,
    name: str,
    *,
    market: int = 0,
    price_milli: int = 10000,
    change_pct: float = 10.0,
    amount_yuan: float = 1e8,
    turnover_pct: float = 2.5,
    streak: int | None = 1,
    first_seal: int | None = 93000,
    broken_times: int | None = 0,
    industry: str = "测试行业",
    seal_amount_yuan: float | None = 1e7,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "c": code,
        "m": market,
        "n": name,
        "p": price_milli,
        "zdp": change_pct,
        "amount": amount_yuan,
        "hs": turnover_pct,
        "hybk": industry,
    }
    if streak is not None:
        row["lbc"] = streak
    if first_seal is not None:
        row["fbt"] = first_seal
    if broken_times is not None:
        row["zbc"] = broken_times
    if seal_amount_yuan is not None:
        row["fund"] = seal_amount_yuan
    return row


def pool_payload(
    rows: list[dict[str, Any]] | None = None,
    *,
    tc: int | None = None,
    qdate: str = "20261103",
    with_data: bool = True,
) -> str:
    if not with_data:
        return json.dumps({"rc": 0, "svr": 1, "lt": 1, "data": None})
    rows = rows or []
    return json.dumps(
        {
            "rc": 0,
            "svr": 1,
            "lt": 1,
            "data": {"tc": len(rows) if tc is None else tc, "qdate": qdate, "pool": rows},
        },
        ensure_ascii=False,
    )
