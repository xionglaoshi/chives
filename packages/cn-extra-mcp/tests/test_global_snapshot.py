from __future__ import annotations

import socket
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from cn_extra_mcp import global_market as gm
from cn_extra_mcp import sources

FIX = Path(__file__).parent / "fixtures/global"
TENCENT = (FIX / "tencent_global.txt").read_text(encoding="utf-8")
REAL_TENCENT = (FIX / "real_run_tencent.txt").read_text(encoding="utf-8")
SINA = (FIX / "sina_global.txt").read_text(encoding="utf-8")
SINA_LIVE = (FIX / "sina_live_20261117.txt").read_text(encoding="utf-8")
BOND = pd.read_csv(FIX / "bond_zh_us_rate.csv")

NOW = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)  # Mon 11:00 Beijing, the recording day


class Upstream:
    def __init__(self) -> None:
        self.tencent_calls: list[list[str]] = []
        self.sina_calls: list[list[str]] = []
        self.bond_calls: list[str] = []
        self.tencent_text = REAL_TENCENT + "\n" + TENCENT
        self.sina_text = SINA
        self.bond = BOND
        self.tencent_error: Exception | None = None
        self.sina_error: Exception | None = None
        self.bond_error: Exception | None = None


@pytest.fixture
def up(monkeypatch, tmp_path) -> Upstream:
    state = Upstream()
    gm.clear_cache()
    monkeypatch.setattr(gm, "_now", lambda: NOW)
    monkeypatch.setattr(gm, "_sleep", lambda seconds: None)
    mapfile = tmp_path / "map.yaml"
    mapfile.write_text(
        "leaders:\n"
        "  - symbol: usNVDA\n    name: 英伟达\n    a_share_sectors: [算力, 光模块]\n    note: 关联算力链\n"
        "  - symbol: usFSLR\n    name: 第一太阳能\n    a_share_sectors: [光伏]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CN_EXTRA_OVERSEAS_MAP", str(mapfile))

    def tencent(symbols, timeout=8.0):
        state.tencent_calls.append(list(symbols))
        if state.tencent_error:
            raise state.tencent_error
        return state.tencent_text

    def sina(symbols, timeout=8.0, referer=sources.SINA_REFERER):
        state.sina_calls.append(list(symbols))
        if state.sina_error:
            raise state.sina_error
        return state.sina_text

    def bond(start_date):
        state.bond_calls.append(start_date)
        if state.bond_error:
            raise state.bond_error
        return state.bond

    monkeypatch.setattr(sources, "fetch_tencent_text", tencent)
    monkeypatch.setattr(sources, "fetch_sina_text", sina)
    monkeypatch.setattr(sources, "fetch_bond_frame", bond)
    return state


def items(payload: dict, group: str) -> dict[str, dict]:
    return {i["key"]: i for i in payload["data"]["groups"][group]["items"]}


# ---- field-index verification on recorded samples -------------------------------------------

def _tencent_pairs() -> list[str]:
    return sorted(gm._tencent_rows(TENCENT))


@pytest.mark.parametrize("symbol", _tencent_pairs())
def test_tencent_prev_close_times_pct_matches_price(symbol: str) -> None:
    fields = gm._tencent_rows(TENCENT)[symbol]
    price, prev, pct = float(fields[3]), float(fields[4]), float(fields[32])
    assert abs(prev * (1 + pct / 100) - price) <= max(0.02 * 1, price * 0.0006)
    assert abs((price - prev) - float(fields[31])) < 0.011


def test_sina_fx_fixture_cross_fields() -> None:
    fields = gm._sina_rows(SINA)["fx_susdcnh"]
    price, prev, pct, change = (float(fields[i]) for i in (8, 3, 10, 11))
    assert abs(price - change - prev) < 1e-6
    assert abs(change / prev * 100 - pct) < 0.01


def test_sina_hxc_fixture_cross_fields() -> None:
    fields = gm._sina_rows(SINA)["gb_hxc"]
    price, pct, change, prev = (float(fields[i]) for i in (1, 2, 4, 26))
    assert abs(price - change - prev) < 1e-3
    assert abs(change / prev * 100 - pct) < 0.02


def test_sina_hf_price_inside_day_range() -> None:
    for symbol, fields in gm._sina_rows(SINA).items():
        if symbol.startswith("hf_"):
            assert float(fields[5]) <= float(fields[0]) <= float(fields[4])


def test_sina_hf_field_7_is_not_the_open() -> None:
    # The open must lie inside the day's range; field 7 does not (hf_CL, hf_HG), so 7 = prev settle, 8 = open.
    outside = []
    for text in (SINA, SINA_LIVE):
        for symbol, fields in gm._sina_rows(text).items():
            if symbol.startswith("hf_"):
                high, low, f7, f8 = (float(fields[i]) for i in (4, 5, 7, 8))
                assert low <= f8 <= high
                if not low <= f7 <= high:
                    outside.append(symbol)
    assert {"hf_CL", "hf_HG"} <= set(outside)


def test_sina_diniw_shares_fx_layout() -> None:
    for text in (SINA, SINA_LIVE):
        rows = gm._sina_rows(text)
        for symbol in ("DINIW", "fx_susdcnh"):
            span, high, low = (float(rows[symbol][i]) for i in (4, 6, 7))
            assert abs((high - low) * 10000 - span) <= 1.5


# ---- group parsing ---------------------------------------------------------------------------

def test_us_index_group(up) -> None:
    payload = gm.cn_get_global_snapshot(["us_index"])
    assert payload["ok"] and payload["status"] == "ready"
    got = items(payload, "us_index")
    assert list(got) == ["dji", "ixic", "spx", "hxc"]
    assert got["dji"]["price"] == 52347.55
    assert got["dji"]["prev_close"] == 52297.09
    assert got["dji"]["change_pct"] == 0.1
    assert got["dji"]["quote_time"] == "2026-11-13T16:43:26-05:00"
    assert got["dji"]["quote_tz"] == "America/New_York"
    assert got["dji"]["source"] == "qt.gtimg.cn"
    assert got["dji"]["stale"] is False
    assert "computed" not in got["dji"]


def test_hxc_from_sina_with_caveat(up) -> None:
    hxc = items(gm.cn_get_global_snapshot(["us_index"]), "us_index")["hxc"]
    assert hxc["source"] == "hq.sinajs.cn"
    assert hxc["price"] == 24.4248 and hxc["prev_close"] == 24.4352 and hxc["change_pct"] == -0.04
    assert hxc["quote_time"] == "2026-11-13T16:10:00-05:00"
    assert hxc["caveat"] == "instrument_identity_unverified"


def test_hk_index_group_uses_hong_kong_time(up) -> None:
    got = items(gm.cn_get_global_snapshot(["hk_index"]), "hk_index")
    assert set(got) == {"hsi", "hstech"}
    assert got["hsi"]["price"] == 23876.53
    assert got["hsi"]["prev_close"] == 23637.6
    assert got["hsi"]["change_pct"] == 1.01
    assert got["hsi"]["quote_tz"] == "Asia/Hong_Kong"
    assert got["hsi"]["quote_time"] == "2026-11-16T10:38:42+08:00"


def test_a50_group_change_against_prev_settle(up) -> None:
    a50 = items(gm.cn_get_global_snapshot(["a50"]), "a50")["a50"]
    assert a50["price"] == 12773.8
    assert a50["quote_time"] == "2026-11-16T10:53:52+08:00"
    assert a50["quote_tz"] == "Asia/Shanghai"
    assert a50["prev_close"] == 12830.0 and a50["prev_close_kind"] == "settle"
    assert a50["change_pct"] == round((12773.8 / 12830.0 - 1) * 100, 4)
    assert a50["computed"] is True and "reason" not in a50
    assert a50["stale"] is False


def test_hf_open_outside_range_fails_field_check(up) -> None:
    up.sina_text = SINA.replace("12830.000,12829.000", "12830.000,12999.000")
    a50 = items(gm.cn_get_global_snapshot(["a50"]), "a50")["a50"]
    assert a50["price"] == 12773.8
    assert a50["prev_close"] is None and a50["change_pct"] is None
    assert a50["reason"] == "field_check_failed"


def test_fx_group(up) -> None:
    got = items(gm.cn_get_global_snapshot(["fx"]), "fx")
    assert got["usdcnh"]["price"] == 6.6697
    assert got["usdcnh"]["prev_close"] == 6.6746
    assert got["usdcnh"]["change_pct"] == -0.07
    assert got["dxy"]["price"] == 103.4202
    assert got["dxy"]["prev_close"] == 103.4105
    assert got["dxy"]["change_pct"] == round((103.4202 / 103.4105 - 1) * 100, 4)
    assert got["dxy"]["caveat"] == "prev_close_by_layout" and "reason" not in got["dxy"]


def test_dxy_broken_layout_fails_field_check(up) -> None:
    up.sina_text = SINA.replace("103.4105,1093,", "103.4105,9999,")
    dxy = items(gm.cn_get_global_snapshot(["fx"]), "fx")["dxy"]
    assert dxy["price"] == 103.4202
    assert dxy["prev_close"] is None and dxy["reason"] == "field_check_failed"


def test_commodity_group(up) -> None:
    got = items(gm.cn_get_global_snapshot(["commodity"]), "commodity")
    assert list(got) == ["crude_oil", "gold", "copper"]
    assert got["crude_oil"]["price"] == 87.794
    assert got["gold"]["price"] == 3873.39
    assert got["copper"]["price"] == 610.03
    assert got["crude_oil"]["prev_close"] == 88.56
    assert got["gold"]["prev_close"] == 3886.3
    assert got["copper"]["prev_close"] == 618.45
    assert got["crude_oil"]["change_pct"] == round((87.794 / 88.56 - 1) * 100, 4)
    assert all(i["prev_close_kind"] == "settle" for i in got.values())


def test_rates_group_values_and_spread(up) -> None:
    payload = gm.cn_get_global_snapshot(["rates"])
    got = items(payload, "rates")
    assert got["us10y"]["price"] == 5.15 and got["us10y"]["prev_close"] == 5.10
    assert got["us2y"]["price"] == 4.88
    assert got["cn10y"]["price"] == 1.6123 and got["cn10y"]["prev_close"] == 1.6032
    spread = got["cn_us_10y_spread"]
    assert spread["price"] == pytest.approx(5.15 - 1.6123, abs=1e-4)
    assert spread["prev_close"] == pytest.approx(5.10 - 1.6032, abs=1e-4)
    assert spread["computed"] is True
    assert spread["change_bp"] == pytest.approx(4.1, abs=0.11)
    assert spread["unit"] == "pct_points"
    assert got["us10y"]["quote_time"] == "2026-11-13"
    assert got["us10y"]["change_pct"] is None


def test_rates_skip_nan_holiday_row(up) -> None:
    frame = BOND.copy()
    frame.loc[frame["日期"] == "2026-11-13", ["美国国债收益率10年"]] = float("nan")
    up.bond = frame
    got = items(gm.cn_get_global_snapshot(["rates"]), "rates")
    assert got["us10y"]["price"] == 5.10
    assert got["us10y"]["prev_close"] == 4.98  # 11-11 is NaN in the recording, so 11-10 is skipped over
    assert got["us10y"]["quote_time"] == "2026-11-12"
    assert got["cn_us_10y_spread"]["quote_time"] == "2026-11-12"


def test_rates_column_missing(up) -> None:
    up.bond = BOND.drop(columns=["美国国债收益率2年"])
    got = items(gm.cn_get_global_snapshot(["rates"]), "rates")
    assert got["us2y"]["price"] is None and got["us2y"]["reason"] == "series_unavailable"
    assert got["us10y"]["price"] == 5.15


def test_rates_empty_frame_is_group_error(up) -> None:
    up.bond = BOND.iloc[0:0]
    group = gm.cn_get_global_snapshot(["rates"])["data"]["groups"]["rates"]
    assert group["ok"] is False and group["error"]["code"] == "upstream_error"


def test_leaders_group_carries_map_fields(up) -> None:
    got = items(gm.cn_get_global_snapshot(["leaders"]), "leaders")
    assert list(got) == ["usNVDA", "usFSLR"]
    nvda = got["usNVDA"]
    assert nvda["name"] == "英伟达"
    assert nvda["a_share_sectors"] == ["算力", "光模块"]
    assert nvda["note"] == "关联算力链"
    assert nvda["price"] == 162.85 and nvda["change_pct"] == -2.01
    assert got["usFSLR"]["price"] == 171.39 and got["usFSLR"]["note"] == ""


def test_leader_missing_in_upstream_response(up) -> None:
    up.tencent_text = TENCENT
    got = items(gm.cn_get_global_snapshot(["leaders"]), "leaders")
    assert got["usFSLR"]["price"] is None and got["usFSLR"]["reason"] == "not_found_upstream"
    assert got["usFSLR"]["a_share_sectors"] == ["光伏"]


def test_default_is_all_groups(up) -> None:
    payload = gm.cn_get_global_snapshot()
    assert list(payload["data"]["groups"]) == list(gm.GROUPS)
    assert payload["ok"] is True and "warnings" not in payload


def test_subset_only_requests_needed_upstreams(up) -> None:
    gm.cn_get_global_snapshot(["a50", "commodity"])
    assert up.tencent_calls == [] and up.bond_calls == []
    assert up.sina_calls == [["hf_CHA50CFD", "hf_CL", "hf_GC", "hf_HG"]]


def test_all_groups_use_one_request_per_upstream(up) -> None:
    gm.cn_get_global_snapshot()
    assert len(up.tencent_calls) == 1 and len(up.sina_calls) == 1 and len(up.bond_calls) == 1


@pytest.mark.parametrize("bad", ["us_index", ["nope"], [], [1], 5, ["us_index", "nope"]])
def test_invalid_groups_rejected_without_upstream(up, bad) -> None:
    payload = gm.cn_get_global_snapshot(bad)
    assert payload["ok"] is False and payload["error"]["code"] == "invalid_argument"
    assert up.tencent_calls == [] and up.sina_calls == [] and up.bond_calls == []


# ---- computed change_pct, stale ---------------------------------------------------------------

def test_change_pct_computed_when_source_blank(up) -> None:
    lines = []
    for line in up.tencent_text.splitlines():
        if line.startswith("v_usNVDA="):
            fields = line.split("~")
            fields[32] = ""
            line = "~".join(fields)
        lines.append(line)
    up.tencent_text = "\n".join(lines)
    nvda = items(gm.cn_get_global_snapshot(["leaders"]), "leaders")["usNVDA"]
    assert nvda["computed"] is True
    assert nvda["change_pct"] == pytest.approx((162.85 / 166.19 - 1) * 100, abs=1e-3)


def test_source_pct_mismatch_is_recomputed_and_flagged(up) -> None:
    lines = []
    for line in up.tencent_text.splitlines():
        if line.startswith("v_usNVDA="):
            fields = line.split("~")
            fields[32] = "7.77"
            line = "~".join(fields)
        lines.append(line)
    up.tencent_text = "\n".join(lines)
    nvda = items(gm.cn_get_global_snapshot(["leaders"]), "leaders")["usNVDA"]
    assert nvda["computed"] is True and nvda["reason"] == "source_change_pct_mismatch"
    assert nvda["change_pct"] == pytest.approx(-2.0098, abs=1e-3)


def test_no_prev_close_gives_null_pct_with_reason(up) -> None:
    lines = []
    for line in up.tencent_text.splitlines():
        if line.startswith("v_usNVDA="):
            fields = line.split("~")
            fields[4] = ""
            fields[32] = ""
            line = "~".join(fields)
        lines.append(line)
    up.tencent_text = "\n".join(lines)
    nvda = items(gm.cn_get_global_snapshot(["leaders"]), "leaders")["usNVDA"]
    assert nvda["price"] == 162.85 and nvda["change_pct"] is None
    assert nvda["reason"] == "change_pct_unavailable"


def test_stale_when_older_than_four_days(up, monkeypatch) -> None:
    monkeypatch.setattr(gm, "_now", lambda: NOW + timedelta(days=3))  # Friday 16:43 ET -> ~5.3 days old
    payload = gm.cn_get_global_snapshot(["us_index", "rates"])
    assert items(payload, "us_index")["dji"]["stale"] is True
    assert items(payload, "rates")["us10y"]["stale"] is True


def test_not_stale_just_inside_four_days(up, monkeypatch) -> None:
    dji_time = datetime(2026, 11, 13, 16, 43, 26, tzinfo=timezone(timedelta(hours=-5)))
    monkeypatch.setattr(gm, "_now", lambda: dji_time + timedelta(days=4) - timedelta(seconds=1))
    assert items(gm.cn_get_global_snapshot(["us_index"]), "us_index")["dji"]["stale"] is False
    monkeypatch.setattr(gm, "_now", lambda: dji_time + timedelta(days=4, seconds=1))
    gm.clear_cache()
    assert items(gm.cn_get_global_snapshot(["us_index"]), "us_index")["dji"]["stale"] is True


def test_sina_stale_sample_marked(up, monkeypatch) -> None:
    monkeypatch.setattr(gm, "_now", lambda: NOW + timedelta(days=6))
    assert items(gm.cn_get_global_snapshot(["a50"]), "a50")["a50"]["stale"] is True


def test_est_year_inference(monkeypatch) -> None:
    monkeypatch.setattr(gm, "_now", lambda: datetime(2027, 1, 4, 3, 0, tzinfo=timezone.utc))
    parsed = gm._parse_est("Dec 31 04:10PM EST")
    assert parsed is not None and parsed.year == 2026
    assert gm._parse_est("garbage") is None


# ---- isolation and failures -------------------------------------------------------------------

def test_tencent_failure_only_hits_tencent_groups(up) -> None:
    up.tencent_error = urllib.error.URLError("boom")
    payload = gm.cn_get_global_snapshot()
    groups = payload["data"]["groups"]
    assert payload["ok"] is True and payload["status"] == "ready"
    assert groups["hk_index"]["ok"] is False and groups["hk_index"]["error"]["code"] == "upstream_error"
    assert groups["leaders"]["ok"] is False
    assert groups["us_index"]["ok"] is False  # contains tencent indexes
    assert any(i["key"] == "hxc" and i["price"] == 24.4248 for i in groups["us_index"]["items"])
    for good in ("a50", "fx", "commodity", "rates"):
        assert groups[good]["ok"] is True
    assert set(payload["warnings"]) == {"group_failed:us_index", "group_failed:hk_index", "group_failed:leaders"}


def test_sina_failure_isolated(up) -> None:
    up.sina_error = urllib.error.URLError("boom")
    groups = gm.cn_get_global_snapshot()["data"]["groups"]
    for bad in ("a50", "fx", "commodity"):
        assert groups[bad]["ok"] is False
    assert groups["hk_index"]["ok"] is True and groups["rates"]["ok"] is True and groups["leaders"]["ok"] is True


def test_sina_missing_referer_sample_fails_group(up) -> None:
    body = (FIX / "sina_no_referer.txt").read_text(encoding="utf-8")
    assert body.startswith("HTTP 403")
    up.sina_error = urllib.error.HTTPError("https://hq.sinajs.cn/list=x", 403, "Forbidden", {}, None)
    group = gm.cn_get_global_snapshot(["a50"])["data"]["groups"]["a50"]
    assert group["ok"] is False and group["error"]["code"] == "upstream_error"
    assert group["items"][0]["price"] is None and group["items"][0]["reason"] == "upstream_failed"


def test_sina_garbage_body_gives_per_item_reason(up) -> None:
    up.sina_text = "HTTP 403\nForbidden"
    payload = gm.cn_get_global_snapshot(["a50"])
    a50 = items(payload, "a50")["a50"]
    assert a50["price"] is None and a50["reason"] == "not_found_upstream"


def test_bond_failure_isolated_and_timeout_code(up) -> None:
    up.bond_error = ConnectionError("down")
    groups = gm.cn_get_global_snapshot(["rates", "a50"])["data"]["groups"]
    assert groups["rates"]["error"]["code"] == "upstream_error"
    assert groups["a50"]["ok"] is True


def test_akshare_hard_timeout(up, monkeypatch) -> None:
    release = __import__("threading").Event()

    def slow(start_date):
        release.wait(5)
        return BOND

    monkeypatch.setattr(sources, "fetch_bond_frame", slow)
    monkeypatch.setattr(gm, "AKSHARE_TIMEOUT", 0.05)
    started = time.monotonic()
    payload = gm.cn_get_global_snapshot(["rates", "a50"])
    release.set()
    assert time.monotonic() - started < 2
    assert payload["data"]["groups"]["rates"]["error"]["code"] == "upstream_timeout"
    assert payload["data"]["groups"]["a50"]["ok"] is True


def test_socket_timeout_classified(up) -> None:
    up.sina_error = socket.timeout("timed out")
    group = gm.cn_get_global_snapshot(["a50"])["data"]["groups"]["a50"]
    assert group["error"]["code"] == "upstream_timeout"


def test_all_groups_failing_is_error_envelope(up) -> None:
    up.sina_error = OSError("x")
    payload = gm.cn_get_global_snapshot(["a50", "fx"])
    assert payload["ok"] is False and payload["status"] == "error"
    assert payload["error"]["code"] == "upstream_error"


# ---- leaders map states ------------------------------------------------------------------------

def test_map_not_configured_is_empty(up, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CN_EXTRA_OVERSEAS_MAP", str(tmp_path / "missing.yaml"))
    payload = gm.cn_get_global_snapshot(["leaders"])
    group = payload["data"]["groups"]["leaders"]
    assert group["status"] == "empty" and group["reason"] == "map_not_configured" and group["items"] == []
    assert up.tencent_calls == []


def test_invalid_map_fails_leaders_only(up, monkeypatch, tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("leaders:\n  - symbol: nope\n    name: x\n    a_share_sectors: [a]\n", encoding="utf-8")
    monkeypatch.setenv("CN_EXTRA_OVERSEAS_MAP", str(bad))
    groups = gm.cn_get_global_snapshot(["leaders", "a50"])["data"]["groups"]
    assert groups["leaders"]["ok"] is False
    assert groups["leaders"]["error"]["code"] == "invalid_overseas_map"
    assert "line 2" in groups["leaders"]["error"]["message"]
    assert groups["a50"]["ok"] is True


# ---- cache, throttle ---------------------------------------------------------------------------

def test_cache_hit_within_ttl_and_refetch_after(up, monkeypatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(gm, "_monotonic", lambda: clock["t"])
    gm.cn_get_global_snapshot(["a50"])
    gm.cn_get_global_snapshot(["a50"])
    assert len(up.sina_calls) == 1
    clock["t"] += 31
    gm.cn_get_global_snapshot(["a50"])
    assert len(up.sina_calls) == 2


def test_rates_cache_is_thirty_minutes(up, monkeypatch) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr(gm, "_monotonic", lambda: clock["t"])
    gm.cn_get_global_snapshot(["rates"])
    clock["t"] += 1700
    gm.cn_get_global_snapshot(["rates"])
    assert len(up.bond_calls) == 1
    clock["t"] += 200
    gm.cn_get_global_snapshot(["rates"])
    assert len(up.bond_calls) == 2


def test_failures_are_not_cached(up) -> None:
    up.sina_error = OSError("x")
    gm.cn_get_global_snapshot(["a50"])
    up.sina_error = None
    assert items(gm.cn_get_global_snapshot(["a50"]), "a50")["a50"]["price"] == 12773.8
    assert len(up.sina_calls) == 2


def test_same_upstream_requests_are_spaced(up, monkeypatch) -> None:
    waits: list[float] = []
    clock = {"t": 50.0}
    monkeypatch.setattr(gm, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(gm, "_sleep", waits.append)
    gm.cn_get_global_snapshot(["a50"])
    gm.cn_get_global_snapshot(["fx"])  # different symbols -> not a cache hit, same upstream, same instant
    assert len(waits) == 1 and 0 < waits[0] <= 1.0


# ---- Sina fetch function (request shape) ------------------------------------------------------

class _Resp:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def read(self) -> bytes:
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_fetch_sina_text_sends_referer_get_and_decodes_gbk(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"], captured["timeout"] = request, timeout
        return _Resp("var hq_str_hf_CL=\"87.7,,\";".encode("gbk") + "纽约原油".encode("gbk"))

    monkeypatch.setattr(sources, "urlopen", fake_urlopen)
    text = sources.fetch_sina_text(["hf_CL", "DINIW"])
    request = captured["request"]
    assert request.full_url == "https://hq.sinajs.cn/list=hf_CL,DINIW"
    assert request.get_method() == "GET"
    assert request.get_header("Referer") == "https://finance.sina.com.cn"
    assert captured["timeout"] == 8.0
    assert "纽约原油" in text


def test_fetch_sina_text_only_allows_sina_host(monkeypatch) -> None:
    monkeypatch.setattr(sources, "SINA_URL", "https://evil.example.com/list={symbols}")
    monkeypatch.setattr(sources, "urlopen", lambda *a, **k: pytest.fail("must not be requested"))
    with pytest.raises(ValueError):
        sources.fetch_sina_text(["hf_CL"])


def test_fetch_sina_text_without_referer_header_is_possible_only_explicitly(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(sources, "urlopen", lambda request, timeout: seen.setdefault("r", request) and _Resp(b""))
    sources.fetch_sina_text(["hf_CL"], referer=None)
    assert seen["r"].get_header("Referer") is None
