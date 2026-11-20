from __future__ import annotations

import json
from datetime import date
from urllib.parse import unquote

import pytest

from cn_daily_store.http import FetchError, HttpClient, check_url
from cn_daily_store.sources import (
    ExchangeListSource,
    TencentKlineSource,
    board_for_digits,
    parse_sse_rows,
    parse_szse_rows,
)

from conftest import FIXTURES, load_fixture


def fake_client(payload_map: dict[str, object]) -> HttpClient:
    def transport(url: str, headers, timeout):
        text = unquote(url)
        for marker, payload in payload_map.items():
            if marker in text:
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raise AssertionError(f"unexpected URL: {url}")

    return HttpClient(min_interval=0, max_attempts=1, transport=transport)


def test_tencent_raw_units():
    payload = load_fixture("tencent_600519_none.json")
    source = TencentKlineSource(fake_client({"sh600519": payload}))
    bars = source.fetch_stock("600519.SH", adjust="none")
    assert len(bars) == 6
    first = bars[0]
    assert first.date == date(2026, 11, 10)
    assert first.close == 1439.0
    assert first.volume == 2303800  # Tencent publishes lots, store uses shares
    assert first.amount == pytest.approx(3316078800.0)


def test_tencent_qfq_rows():
    payload = load_fixture("tencent_600519_qfq.json")
    source = TencentKlineSource(fake_client({"sh600519": payload}))
    bars = source.fetch_stock("600519.SH", adjust="qfq")
    assert bars[-1].close == 1457.70
    assert bars[0].close == 1439.0


def test_sse_rows_include_delisted():
    payload = load_fixture("sse_list.json")
    rows = parse_sse_rows(payload["pageHelp"]["data"])
    assert [row.code for row in rows] == ["600000.SH", "600001.SH", "600002.SH"]
    assert rows[0].list_date == "1999-11-10"
    assert rows[1].delist_date == "2009-12-29"
    assert rows[2].board == "sh_main"


def test_szse_rows_strip_html():
    payload = load_fixture("szse_list.json")
    rows = parse_szse_rows(payload[0]["data"])
    assert [row.code for row in rows] == ["000001.SZ", "000002.SZ", "000006.SZ"]
    assert rows[1].name == "万 科Ａ"
    assert rows[0].list_date == "1991-04-03"


def test_board_classification():
    assert board_for_digits("600519") == "sh_main"
    assert board_for_digits("000528") == "sz_main"
    assert board_for_digits("002594") == "sz_main"
    assert board_for_digits("300750") == "chinext"
    assert board_for_digits("301001") == "chinext"
    assert board_for_digits("688981") == "star"
    assert board_for_digits("920000") is None
    assert board_for_digits("900901") is None


def test_exchange_refresh_writes_securities_and_names(tmp_path):
    from cn_daily_store.db import connect, init_schema

    payload_sse = load_fixture("sse_list.json")
    payload_szse = load_fixture("szse_list.json")

    def transport(url: str, headers, timeout):
        if "query.sse.com.cn" in url:
            return json.dumps(payload_sse, ensure_ascii=False).encode("utf-8")
        return json.dumps(payload_szse, ensure_ascii=False).encode("utf-8")

    client = HttpClient(min_interval=0, max_attempts=1, transport=transport)
    db = tmp_path / "x.sqlite"
    conn = connect(db, readonly=False)
    init_schema(conn)
    source = ExchangeListSource(client)
    source.fetch_sse = lambda: parse_sse_rows(payload_sse["pageHelp"]["data"])  # type: ignore[method-assign]
    source.fetch_szse = lambda: parse_szse_rows(payload_szse[0]["data"])  # type: ignore[method-assign]
    counts = source.refresh(conn)
    assert counts == {"sh_main": 3, "sz_main": 3}
    assert conn.execute("SELECT COUNT(*) FROM securities").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM names").fetchone()[0] == 6
    conn.close()


def test_host_whitelist_and_forbidden_marker():
    check_url("https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get?param=x")
    with pytest.raises(FetchError):
        check_url("https://push2.eastmoney.com/api")
    with pytest.raises(FetchError):
        check_url("https://example.com/")


def test_sina_factor_parser():
    from cn_daily_store.sources import SinaFactorSource

    text = (FIXTURES / "sina_qfq_600519.js").read_text(encoding="utf-8")
    client = HttpClient(min_interval=0, max_attempts=1, transport=lambda url, headers, timeout: text.encode("utf-8"))
    points = SinaFactorSource(client).fetch("600519.SH")
    assert points
    assert points == sorted(points)
    assert abs(points[-1][1] - 1.0) < 1e-9  # latest qfq factor is 1
    assert all(factor > 0 for _, factor in points)


def test_star_volume_is_shares_not_lots():
    payload = {
        "code": 0,
        "data": {
            "sh688981": {
                "day": [
                    ["2026-11-11", "106.90", "109.31", "109.39", "106.51",
                     "28496458.00", {}, "1.42", "307957.32", ""]
                ]
            }
        },
    }
    source = TencentKlineSource(fake_client({"sh688981": payload}))
    bars = source.fetch_stock("688981.SH", adjust="none")
    assert bars[0].volume == 28496458
    assert bars[0].amount == pytest.approx(3079573200.0)
