from __future__ import annotations

import http.client
import json
import threading
import time as clock_time
import urllib.parse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import pytest

from chives_signals.calendar import TradingCalendar
from chives_signals.config import (
    ConfigError,
    IFZQ_FALLBACK_DEFAULT_BASE,
    IFZQ_FALLBACK_HOST,
    IFZQ_HOST,
    load_config,
)
from chives_signals.engine import HubEngine
from chives_signals.server import start_server, stop_server
from chives_signals.sources import HttpClient, SourceError, validate_public_url
from chives_signals.spark import (
    CLOSED_CACHE_SECONDS,
    MAX_SPARK_POINTS,
    SparkParamError,
    SparkService,
    downsample_points,
    minute_url,
    parse_minute_payload,
    parse_spark_codes,
    tencent_symbol,
)
from tests.support import (
    FakeClock,
    FakePortfolio,
    FakeSources,
    at,
    make_config,
    write_config,
)

DAY = date(2026, 11, 4)
WEEKDAYS = TradingCalendar(days=frozenset(), source="weekdays")


class FakeMinuteClient:
    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[tuple[str, str, Optional[float]]] = []
        self.delay = 0.0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def get_json_public(
        self,
        name: str,
        url: str,
        *,
        now: Optional[datetime] = None,
        test_mode: bool = False,
        allowed_hosts: Any = (),
        timeout: Optional[float] = None,
    ) -> Any:
        symbol = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["code"][0]
        with self._lock:
            self.calls.append((name, url, timeout))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                clock_time.sleep(self.delay)
            error = self.errors.get(symbol) or self.errors.get("*")
            if error is not None:
                raise error
            return self.payloads.get(symbol, {"code": 0, "data": {}})
        finally:
            with self._lock:
                self.active -= 1


def minute_rows(points: list[tuple[str, float]]) -> list[str]:
    return [f"{stamp} {price:.2f} 100 1000.00" for stamp, price in points]


def series(count: int, start: float = 10.0) -> list[tuple[str, float]]:
    base = datetime(2026, 11, 4, 9, 30)
    return [
        ((base + timedelta(minutes=index)).strftime("%H%M"), round(start + index * 0.01, 2))
        for index in range(count)
    ]


def minute_payload(
    code: str = "600519.SH",
    *,
    day: date = DAY,
    points: Optional[list[tuple[str, float]]] = None,
    prev_close: Any = 100.0,
    qt_style: str = "list",
    status: Any = 0,
) -> dict[str, Any]:
    symbol = tencent_symbol(code)
    rows = minute_rows(points if points is not None else series(5))
    quote = [1, "测试股", code[:6], rows[-1].split()[1] if rows else "", str(prev_close)]
    node: dict[str, Any] = {"data": {"data": rows, "date": day.strftime("%Y%m%d")}}
    if qt_style == "list":
        node["qt"] = quote
    elif qt_style == "dict":
        node["qt"] = {symbol: quote}
    elif qt_style == "string":
        node["qt"] = "~".join(str(item) for item in quote)
    return {"code": status, "data": {symbol: node}}


def make_service(
    tmp_path: Path,
    *,
    client: Optional[FakeMinuteClient] = None,
    clock: Optional[FakeClock] = None,
    calendar: Optional[TradingCalendar] = None,
    env: Optional[dict[str, str]] = None,
) -> SparkService:
    config = make_config(tmp_path)
    return SparkService(
        config,
        client=client or FakeMinuteClient(),
        calendar=calendar or WEEKDAYS,
        clock=clock or FakeClock(at(10, 0)),
        env=env or {"CHIVES_HUB_TEST_MODE": "1"},
    )


# -- parameter validation ---------------------------------------------------
def test_parse_codes_accepts_canonical_and_dedupes() -> None:
    assert parse_spark_codes("600519.SH,300750.SZ,600519.SH") == ["600519.SH", "300750.SZ"]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        ",",
        "600519",
        "600519.HK",
        "600519.sh",
        "60051.SH",
        "600519.SH,",
        " 600519.SH",
        "600519.SH ",
        "600519.SH%0d%0a",
        "../etc/passwd",
        "99999A.SH",
    ],
)
def test_parse_codes_rejects_bad_shapes(raw: str) -> None:
    with pytest.raises(SparkParamError):
        parse_spark_codes(raw)


def test_parse_codes_rejects_31_unique() -> None:
    raw = ",".join(f"{600000 + index}.SH" for index in range(31))
    with pytest.raises(SparkParamError):
        parse_spark_codes(raw)


def test_parse_codes_accepts_30_unique() -> None:
    raw = ",".join(f"{600000 + index}.SH" for index in range(30))
    assert len(parse_spark_codes(raw)) == 30


def test_parse_codes_rejects_oversized_input() -> None:
    with pytest.raises(SparkParamError):
        parse_spark_codes("6" * 5000)


def test_tencent_prefix_mapping() -> None:
    assert tencent_symbol("600519.SH") == "sh600519"
    assert tencent_symbol("300750.SZ") == "sz300750"


def test_minute_url_encodes_symbol() -> None:
    assert minute_url("https://web.ifzq.gtimg.cn", "600519.SH") == (
        "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519"
    )


# -- parsing ----------------------------------------------------------------
def test_parse_minute_payload_metrics() -> None:
    data = parse_minute_payload(minute_payload(), "600519.SH", DAY)
    assert data is not None
    assert data.points == tuple(round(10.0 + index * 0.01, 2) for index in range(5))
    assert data.prev_close == 100.0
    assert data.as_of_minute == "09:34"
    assert data.trading_date == DAY


@pytest.mark.parametrize("style", ["dict", "string"])
def test_parse_minute_prev_close_other_qt_shapes(style: str) -> None:
    data = parse_minute_payload(minute_payload(qt_style=style), "600519.SH", DAY)
    assert data is not None and data.prev_close == 100.0


def test_parse_minute_missing_prev_close_is_null() -> None:
    data = parse_minute_payload(minute_payload(prev_close=""), "600519.SH", DAY)
    assert data is not None and data.prev_close is None


def test_parse_minute_rejects_stale_date() -> None:
    assert parse_minute_payload(minute_payload(day=date(2026, 11, 3)), "600519.SH", DAY) is None


def test_parse_minute_rejects_empty_rows() -> None:
    assert parse_minute_payload(minute_payload(points=[]), "600519.SH", DAY) is None


def test_parse_minute_rejects_wrong_symbol() -> None:
    payload = minute_payload()
    assert parse_minute_payload(payload, "600036.SH", DAY) is None


def test_parse_minute_rejects_nonzero_status() -> None:
    assert parse_minute_payload(minute_payload(status=1), "600519.SH", DAY) is None


@pytest.mark.parametrize("payload", [None, [], {}, {"code": 0, "data": []}, {"code": 0, "data": {"sh600519": []}}])
def test_parse_minute_rejects_malformed_payload(payload: Any) -> None:
    assert parse_minute_payload(payload, "600519.SH", DAY) is None


def test_parse_minute_skips_bad_rows() -> None:
    payload = minute_payload(points=[("0930", 10.0), ("0931", 10.1)])
    payload["data"]["sh600519"]["data"]["data"] = ["bad row", "0932 abc 1 1", "0933 10.2 1 1"]
    data = parse_minute_payload(payload, "600519.SH", DAY)
    assert data is not None
    assert data.points == (10.2,)
    assert data.as_of_minute == "09:33"


def test_parse_minute_rejects_bad_date_text() -> None:
    payload = minute_payload()
    payload["data"]["sh600519"]["data"]["date"] = "2026-11-04"
    assert parse_minute_payload(payload, "600519.SH", DAY) is None


# -- downsampling -----------------------------------------------------------
def test_downsample_keeps_ends_and_cap() -> None:
    raw = [float(index) for index in range(241)]
    picked = downsample_points(raw)
    assert len(picked) == MAX_SPARK_POINTS
    assert picked[0] == raw[0]
    assert picked[-1] == raw[-1]


def test_downsample_points_are_a_real_subsequence() -> None:
    raw = [100.0 + index * 0.01 for index in range(120)]
    picked = downsample_points(raw)
    positions = [raw.index(value) for value in picked]
    assert positions == sorted(set(positions))
    assert all(value in raw for value in picked)


def test_downsample_returns_short_series_unchanged() -> None:
    raw = [1.0, 2.0, 3.0]
    assert downsample_points(raw) == raw


def test_downsample_of_61_has_60_unique_points() -> None:
    picked = downsample_points([float(index) for index in range(61)])
    assert len(picked) == 60
    assert len(set(picked)) == 60


# -- service payload --------------------------------------------------------
def test_payload_intraday_shape(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload(prev_close=10.5)
    service = make_service(tmp_path, client=client)
    payload = service.payload("600519.SH")
    assert payload["ok"] is True
    assert payload["trading_date"] == "2026-11-04"
    assert payload["as_of"].endswith("+08:00")
    spark = payload["sparks"]["600519.SH"]
    assert spark["last"] == 10.04
    assert spark["prev_close"] == 10.5
    assert spark["change_pct"] == round((10.04 / 10.5 - 1) * 100, 2)
    assert spark["as_of_minute"] == "09:34"
    assert spark["complete"] is False
    assert len(spark["points"]) == 5
    assert payload["missing"] == []


def test_payload_after_close_is_complete(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload()
    service = make_service(tmp_path, client=client, clock=FakeClock(at(15, 5)))
    payload = service.payload("600519.SH")
    assert payload["sparks"]["600519.SH"]["complete"] is True


def test_payload_non_trading_day_is_all_missing(tmp_path: Path) -> None:
    calendar = TradingCalendar(days=frozenset({date(2026, 11, 3)}), source="file")
    client = FakeMinuteClient()
    service = make_service(tmp_path, client=client, calendar=calendar)
    payload = service.payload("600519.SH,300750.SZ")
    assert payload["ok"] is True
    assert payload["sparks"] == {}
    assert payload["missing"] == ["600519.SH", "300750.SZ"]
    assert client.calls == []


def test_payload_partial_failure(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload()
    client.errors["sz300750"] = RuntimeError("boom")
    payload = make_service(tmp_path, client=client).payload("600519.SH,300750.SZ")
    assert set(payload["sparks"]) == {"600519.SH"}
    assert payload["missing"] == ["300750.SZ"]


def test_payload_all_fail_is_still_ok(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.errors["*"] = TimeoutError("slow")
    payload = make_service(tmp_path, client=client).payload("600519.SH,300750.SZ")
    assert payload["ok"] is True
    assert payload["sparks"] == {}
    assert payload["missing"] == ["600519.SH", "300750.SZ"]


def test_payload_stale_date_goes_missing(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload(day=date(2026, 11, 3))
    payload = make_service(tmp_path, client=client).payload("600519.SH")
    assert payload["sparks"] == {}
    assert payload["missing"] == ["600519.SH"]


def test_payload_expired_code_goes_missing(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh999999"] = {"code": 0, "data": {"sh999999": {"data": {"data": [], "date": "20261104"}}}}
    payload = make_service(tmp_path, client=client).payload("999999.SH")
    assert payload["sparks"] == {}
    assert payload["missing"] == ["999999.SH"]


# -- cache / limits ---------------------------------------------------------
def test_cache_hits_inside_30s_trading_window(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload()
    clock = FakeClock(at(10, 0))
    service = make_service(tmp_path, client=client, clock=clock)
    service.payload("600519.SH")
    clock.set(at(10, 0, 29))
    service.payload("600519.SH")
    assert len(client.calls) == 1


def test_cache_expires_after_30s_trading_window(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload()
    clock = FakeClock(at(10, 0))
    service = make_service(tmp_path, client=client, clock=clock)
    service.payload("600519.SH")
    clock.set(at(10, 0, 31))
    service.payload("600519.SH")
    assert len(client.calls) == 2


def test_closed_market_cache_last_ten_minutes(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.payloads["sh600519"] = minute_payload()
    clock = FakeClock(at(15, 30))
    service = make_service(tmp_path, client=client, clock=clock)
    service.payload("600519.SH")
    clock.set(at(15, 31))
    service.payload("600519.SH")
    assert len(client.calls) == 1
    clock.set(datetime(2026, 11, 4, 15, 31, 0, tzinfo=at(0).tzinfo) + timedelta(seconds=CLOSED_CACHE_SECONDS))
    service.payload("600519.SH")
    assert len(client.calls) == 2


def test_upstream_concurrency_is_capped_at_four(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.delay = 0.03
    for index in range(12):
        client.payloads[f"sh{600000 + index}"] = minute_payload(f"{600000 + index}.SH")
    raw = ",".join(f"{600000 + index}.SH" for index in range(12))
    payload = make_service(tmp_path, client=client).payload(raw)
    assert len(payload["sparks"]) == 12
    assert client.max_active <= 4


def test_total_upstream_timeout_degrades_to_missing(tmp_path: Path) -> None:
    client = FakeMinuteClient()
    client.delay = 0.4
    service = make_service(tmp_path, client=client)
    service.total_timeout = 0.15
    started = clock_time.monotonic()
    payload = service.payload("600519.SH,300750.SZ,600036.SH")
    elapsed = clock_time.monotonic() - started
    assert payload["ok"] is True
    assert payload["missing"] == ["600519.SH", "300750.SZ", "600036.SH"]
    assert elapsed < 1.0


# -- host whitelist / config ------------------------------------------------
def test_public_host_validation_allows_only_https_fixed_hosts() -> None:
    validate_public_url("https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519", hosts=(IFZQ_HOST,))
    for url in (
        "http://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519",
        "https://qt.gtimg.cn/q=sh600519",
        "https://web.ifzq.gtimg.cn.evil.example/x",
        "https://user:pass@web.ifzq.gtimg.cn/x",
    ):
        with pytest.raises(SourceError):
            validate_public_url(url, hosts=(IFZQ_HOST,))


def test_test_mode_only_allows_loopback(tmp_path: Path) -> None:
    validate_public_url("http://127.0.0.1:19999/x", hosts=(IFZQ_HOST,), test_mode=True)
    with pytest.raises(SourceError):
        validate_public_url("https://web.ifzq.gtimg.cn/x", hosts=(IFZQ_HOST,), test_mode=True)


def test_ifzq_env_requires_test_mode(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path), env={"CHIVES_HUB_IFZQ_BASE": "http://127.0.0.1:19999"})


def test_ifzq_env_must_be_loopback(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            write_config(tmp_path),
            env={"CHIVES_HUB_TEST_MODE": "1", "CHIVES_HUB_IFZQ_BASE": "https://evil.example"},
        )


def test_ifzq_env_override_in_test_mode(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path),
        env={"CHIVES_HUB_TEST_MODE": "1", "CHIVES_HUB_IFZQ_BASE": "http://127.0.0.1:19999/"},
    )
    assert config.ifzq_base == "http://127.0.0.1:19999"


def test_default_ifzq_base_is_the_fixed_https_host(tmp_path: Path) -> None:
    assert make_config(tmp_path).ifzq_base == "https://web.ifzq.gtimg.cn"


# -- real HTTP against a loopback fake upstream -----------------------------
class _MinuteHandler(BaseHTTPRequestHandler):
    payload = minute_payload()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_http_client_fetches_loopback_minute_payload(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MinuteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        config = load_config(
            write_config(tmp_path),
            env={"CHIVES_HUB_TEST_MODE": "1", "CHIVES_HUB_IFZQ_BASE": f"http://127.0.0.1:{port}"},
        )
        service = SparkService(
            config,
            client=HttpClient(timeout=2.0),
            calendar=WEEKDAYS,
            clock=FakeClock(at(10, 0)),
            env={"CHIVES_HUB_TEST_MODE": "1"},
        )
        payload = service.payload("600519.SH")
        spark = payload["sparks"]["600519.SH"]
        assert spark["last"] == 10.04
        assert spark["as_of_minute"] == "09:34"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


# -- primary -> fallback host ------------------------------------------------
class FakeMonotonic:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _minute_payload_for(path: str, *, day: date = DAY) -> dict[str, Any]:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    symbol = query.get("code", ["sh600519"])[0]
    code = symbol[2:] + "." + symbol[:2].upper()
    return minute_payload(code, day=day, points=series(5))


@contextmanager
def fake_ifzq(responder: Any):
    """One loopback fake upstream with /primary and /backup path prefixes."""
    state = {"primary": 0, "backup": 0, "active": 0, "max_active": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            role = "primary" if self.path.startswith("/primary") else "backup"
            with lock:
                state[role] += 1
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                status, payload, delay = responder(role, self.path)
                if delay:
                    clock_time.sleep(delay)
                body = json.dumps(payload).encode("utf-8") if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    state["active"] -= 1

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False

        def handle_error(self, request: Any, client_address: Any) -> None:
            return

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield (
            f"http://127.0.0.1:{port}/primary",
            f"http://127.0.0.1:{port}/backup",
            state,
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def failover_service(
    tmp_path: Path,
    primary: str,
    backup: str,
    *,
    clock: Optional[FakeClock] = None,
    monotonic: Optional[FakeMonotonic] = None,
    timeout: float = 2.0,
) -> SparkService:
    config = load_config(
        write_config(tmp_path, polling=f"{{timeout_seconds: {timeout}}}"),
        env={
            "CHIVES_HUB_TEST_MODE": "1",
            "CHIVES_HUB_IFZQ_BASE": primary,
            "CHIVES_HUB_IFZQ_FALLBACK_BASE": backup,
        },
    )
    return SparkService(
        config,
        client=HttpClient(timeout=timeout),
        calendar=WEEKDAYS,
        clock=clock or FakeClock(at(10, 0)),
        monotonic=monotonic,
        env={"CHIVES_HUB_TEST_MODE": "1"},
    )


def _ok(role: str, path: str, _delay: float = 0.0):
    return 200, _minute_payload_for(path), _delay


def test_primary_501_falls_back_to_backup(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 501, {"code": 1}, 0.0
        return _ok(role, path)

    with fake_ifzq(responder) as (primary, backup, state):
        payload = failover_service(tmp_path, primary, backup).payload("600519.SH")
    spark = payload["sparks"]["600519.SH"]
    assert spark["last"] == 10.04
    assert state["primary"] == 1 and state["backup"] == 1


def test_primary_timeout_falls_back_to_backup(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 200, _minute_payload_for(path), 1.0
        return _ok(role, path)

    with fake_ifzq(responder) as (primary, backup, state):
        started = clock_time.monotonic()
        payload = failover_service(tmp_path, primary, backup, timeout=0.5).payload("600519.SH")
        elapsed = clock_time.monotonic() - started
    assert "600519.SH" in payload["sparks"]
    assert state["primary"] == 1 and state["backup"] == 1
    assert elapsed < 2.0


def test_primary_stale_date_falls_back_to_today(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 200, _minute_payload_for(path, day=date(2026, 11, 3)), 0.0
        return _ok(role, path)

    with fake_ifzq(responder) as (primary, backup, state):
        payload = failover_service(tmp_path, primary, backup).payload("600519.SH")
    assert payload["sparks"]["600519.SH"]["last"] == 10.04
    assert payload["missing"] == []
    assert state["primary"] == 1 and state["backup"] == 1


def test_both_hosts_fail_goes_missing(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        return (501 if role == "primary" else 502), {"code": 1}, 0.0

    with fake_ifzq(responder) as (primary, backup, state):
        payload = failover_service(tmp_path, primary, backup).payload("600519.SH")
    assert payload["ok"] is True
    assert payload["sparks"] == {}
    assert payload["missing"] == ["600519.SH"]
    assert state["primary"] == 1 and state["backup"] == 1


def test_failover_sticks_to_backup_for_60_seconds(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 501, {"code": 1}, 0.0
        return _ok(role, path)

    monotonic = FakeMonotonic()
    with fake_ifzq(responder) as (primary, backup, state):
        service = failover_service(tmp_path, primary, backup, monotonic=monotonic)
        service.payload("600519.SH")
        assert (state["primary"], state["backup"]) == (1, 1)
        monotonic.value += 30
        service.payload("600036.SH")
        assert (state["primary"], state["backup"]) == (1, 2)
        monotonic.value += 31
        service.payload("600000.SH")
    assert (state["primary"], state["backup"]) == (2, 3)


def test_fallback_keeps_upstream_concurrency_at_four(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 501, {"code": 1}, 0.0
        return 200, _minute_payload_for(path), 0.03

    raw = ",".join(f"{600000 + index}.SH" for index in range(12))
    with fake_ifzq(responder) as (primary, backup, state):
        payload = failover_service(tmp_path, primary, backup).payload(raw)
    assert len(payload["sparks"]) == 12
    assert state["max_active"] <= 4


def test_fallback_shares_the_total_timeout(tmp_path: Path) -> None:
    def responder(role: str, path: str):
        if role == "primary":
            return 501, {"code": 1}, 0.1
        return 200, _minute_payload_for(path), 2.0

    raw = "600519.SH,300750.SZ,600036.SH"
    with fake_ifzq(responder) as (primary, backup, _state):
        service = failover_service(tmp_path, primary, backup)
        service.total_timeout = 0.25
        started = clock_time.monotonic()
        payload = service.payload(raw)
        elapsed = clock_time.monotonic() - started
    assert payload["missing"] == raw.split(",")
    assert elapsed < 1.0


def test_public_host_validation_allows_both_ifzq_hosts() -> None:
    hosts = (IFZQ_HOST, IFZQ_FALLBACK_HOST)
    for host in hosts:
        validate_public_url(f"https://{host}/appstock/app/minute/query?code=sh600519", hosts=hosts)
    for url in (
        "http://ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519",
        "https://ifzq.gtimg.cn.evil.example/x",
        "https://evil.example/x",
        "https://user:pass@ifzq.gtimg.cn/x",
    ):
        with pytest.raises(SourceError):
            validate_public_url(url, hosts=hosts)


def test_default_ifzq_fallback_base_is_the_https_host(tmp_path: Path) -> None:
    assert make_config(tmp_path).ifzq_fallback_base == IFZQ_FALLBACK_DEFAULT_BASE


def test_ifzq_fallback_env_rejects_plain_http(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            write_config(tmp_path),
            env={"CHIVES_HUB_IFZQ_FALLBACK_BASE": "http://127.0.0.1:19999"},
        )


def test_ifzq_fallback_env_requires_whitelisted_https_host(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path),
        env={"CHIVES_HUB_IFZQ_FALLBACK_BASE": "https://ifzq.gtimg.cn/"},
    )
    assert config.ifzq_fallback_base == "https://ifzq.gtimg.cn"
    for bad in ("https://evil.example", "http://ifzq.gtimg.cn", "https://user:pass@ifzq.gtimg.cn"):
        with pytest.raises(ConfigError):
            load_config(
                write_config(tmp_path),
                env={"CHIVES_HUB_IFZQ_FALLBACK_BASE": bad},
            )


def test_ifzq_fallback_env_must_be_loopback(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            write_config(tmp_path),
            env={
                "CHIVES_HUB_TEST_MODE": "1",
                "CHIVES_HUB_IFZQ_FALLBACK_BASE": "https://evil.example",
            },
        )


def test_ifzq_fallback_env_override_in_test_mode(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path),
        env={
            "CHIVES_HUB_TEST_MODE": "1",
            "CHIVES_HUB_IFZQ_FALLBACK_BASE": "http://127.0.0.1:19998/",
        },
    )
    assert config.ifzq_fallback_base == "http://127.0.0.1:19998"


# -- HTTP endpoint ----------------------------------------------------------
@contextmanager
def running_hub(tmp_path: Path, service: SparkService):
    config = make_config(tmp_path)
    engine = HubEngine(
        config,
        clock=service.clock,
        sources=FakeSources(),
        portfolio=FakePortfolio(),
        spark_service=service,
    )
    httpd, thread = start_server(engine, "127.0.0.1", 0)
    port = httpd.server_address[1]
    try:
        yield port
    finally:
        stop_server(httpd, thread)


def _get(port: int, path: str) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def test_api_spark_shape(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with running_hub(tmp_path, service) as port:
        status, payload = _get(port, "/spark?codes=600519.SH,300750.SZ")
    assert status == 200
    assert payload["ok"] is True
    assert payload["trading_date"] == "2026-11-04"
    assert "sparks" in payload and "missing" in payload


@pytest.mark.parametrize(
    "query",
    ["/spark", "/spark?codes=", "/spark?codes=600519", "/spark?codes=600519.HK", "/spark?codes=abc", "/spark?x=1"],
)
def test_api_spark_bad_params(tmp_path: Path, query: str) -> None:
    service = make_service(tmp_path)
    with running_hub(tmp_path, service) as port:
        status, payload = _get(port, query)
    assert status == 200
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_params"


def test_api_spark_30_codes_ok(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    raw = ",".join(f"{600000 + index}.SH" for index in range(30))
    with running_hub(tmp_path, service) as port:
        _, payload = _get(port, "/spark?codes=" + raw)
    assert payload["ok"] is True
    assert len(payload["sparks"]) + len(payload["missing"]) == 30


def test_api_spark_31_codes_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    raw = ",".join(f"{600000 + index}.SH" for index in range(31))
    with running_hub(tmp_path, service) as port:
        _, payload = _get(port, "/spark?codes=" + raw)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_params"


def test_api_spark_repeated_codes_param_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with running_hub(tmp_path, service) as port:
        _, payload = _get(port, "/spark?codes=600519.SH&codes=300750.SZ")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_params"
