from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from cn_watch.config import ConfigError, parse_config
from cn_watch.market_context import MarketContextClient, MarketSnapshot, validate_loopback_url
from cn_watch.models import CN_TZ
from support import BASE_CONFIG

NOW = datetime(2026, 11, 3, 10, 0, 0, tzinfo=CN_TZ)


class FakeResponse:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class FakeHTTP:
    def __init__(self, overview=None, sectors=None):
        self.overview = overview if overview is not None else {
            "ok": True,
            "as_of": NOW.isoformat(),
            "regime": {"label": "risk_on"},
            "indexes": [
                {"code": "000001.SH", "change_pct": 1.2},
                {"code": "399001.SZ", "change_pct": -0.5},
            ],
        }
        self.sectors = sectors if sectors is not None else {
            "ok": True,
            "as_of": NOW.isoformat(),
            "rows": [
                {"code": "BK0433", "change_pct": 2.0, "rank": 1},
                {"code": "BK0477", "change_pct": None, "rank": None},
            ],
        }
        self.paths: list[str] = []

    def __call__(self, url, timeout=None, headers=None):
        path = url.split("127.0.0.1:8866", 1)[-1]
        self.paths.append(path)
        if path.startswith("/overview"):
            return FakeResponse(self.overview)
        if path.startswith("/sectors"):
            return FakeResponse(self.sectors)
        return FakeResponse({}, status=404)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8866",
        "http://localhost:8866",
        "http://[::1]:8866",
        "https://127.0.0.1:9999",
    ],
)
def test_loopback_urls_are_accepted(url):
    assert validate_loopback_url(url).startswith("http")


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1:8866",
        "http://example.com",
        "ftp://127.0.0.1:8866",
        "http://127.0.0.1.evil.com:8866",
        "http://user:pass@127.0.0.1:8866",
    ],
)
def test_non_loopback_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_loopback_url(url)


@pytest.mark.parametrize(
    "url",
    ["http://10.0.0.1:8866", "http://example.com:8866", "ftp://127.0.0.1:8866", "127.0.0.1:8866"],
)
def test_config_rejects_non_loopback_market_watch_url(url):
    raw = json.loads(json.dumps(BASE_CONFIG))
    raw["market_watch_url"] = url
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_config_default_market_watch_url():
    parsed = parse_config(json.loads(json.dumps(BASE_CONFIG)))
    assert parsed.market_watch_url == "http://127.0.0.1:8866"


def test_config_accepts_loopback_and_strips_slash():
    raw = json.loads(json.dumps(BASE_CONFIG))
    raw["market_watch_url"] = "http://localhost:9876/"
    assert parse_config(raw).market_watch_url == "http://localhost:9876"


def test_refresh_parses_overview_and_sectors(monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    snapshot = client.snapshot(NOW)
    assert snapshot.ok is True
    assert snapshot.regime == "strong"
    assert snapshot.indexes == {"000001.SH": 1.2, "399001.SZ": -0.5}
    assert snapshot.sectors["BK0433"] == {"change_pct": 2.0, "rank": 1}
    assert snapshot.sectors["BK0477"] == {"change_pct": None, "rank": None}
    assert snapshot.age_s == 0.0
    assert http.paths == ["/overview", "/sectors"]


@pytest.mark.parametrize(
    "label,expected",
    [("risk_on", "strong"), ("risk_off", "weak"), ("neutral", "neutral"), ("unknown", None)],
)
def test_regime_mapping(monkeypatch, label, expected):
    http = FakeHTTP(overview={"ok": True, "as_of": NOW.isoformat(), "regime": {"label": label}, "indexes": []})
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).regime == expected


def test_regime_string_shape_is_supported(monkeypatch):
    http = FakeHTTP(overview={"ok": True, "regime": "risk_off", "indexes": []})
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).regime == "weak"


def test_polling_interval_is_five_seconds(monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert len(http.paths) == 2
    client.refresh(NOW + timedelta(seconds=4))
    assert len(http.paths) == 2
    client.refresh(NOW + timedelta(seconds=5))
    assert len(http.paths) == 4


def test_data_older_than_thirty_seconds_is_unknown(monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    fresh = client.snapshot(NOW + timedelta(seconds=30))
    assert fresh.ok is True
    stale = client.snapshot(NOW + timedelta(seconds=30.001))
    assert stale.ok is False
    assert stale.regime is None
    assert stale.indexes == {}
    assert stale.sectors == {}
    assert stale.age_s == 30.001


def test_as_of_from_payload_governs_freshness(monkeypatch):
    old = (NOW - timedelta(seconds=40)).isoformat()
    http = FakeHTTP(overview={"ok": True, "as_of": old, "regime": {"label": "risk_on"}, "indexes": []})
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    snapshot = client.snapshot(NOW)
    assert snapshot.ok is False
    assert snapshot.regime is None
    assert snapshot.age_s >= 40


def test_failure_makes_context_unknown_immediately(monkeypatch):
    good = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", good)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).ok is True

    def broken(url, timeout=None, headers=None):
        raise OSError("connection refused")

    monkeypatch.setattr("cn_watch.market_context.requests.get", broken)
    later = NOW + timedelta(seconds=10)
    client.refresh(later)
    snapshot = client.snapshot(later)
    assert snapshot.ok is False
    assert snapshot.regime is None
    assert client.last_error


def test_http_error_marks_unknown(monkeypatch):
    def not_found(url, timeout=None, headers=None):
        return FakeResponse({}, status=500)

    monkeypatch.setattr("cn_watch.market_context.requests.get", not_found)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    snapshot = client.snapshot(NOW)
    assert snapshot.ok is False
    assert snapshot.age_s is None
    assert client.last_error


def test_ok_false_payload_is_treated_as_failure(monkeypatch):
    http = FakeHTTP(overview={"ok": False, "regime": {"label": "risk_on"}})
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).regime is None


def test_non_object_payload_is_treated_as_failure(monkeypatch):
    http = FakeHTTP(overview=[])
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).ok is False


def test_bad_json_is_treated_as_failure(monkeypatch):
    http = FakeHTTP(overview=ValueError("not json"))
    monkeypatch.setattr("cn_watch.market_context.requests.get", http)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).ok is False


def test_partial_failure_keeps_other_block(monkeypatch):
    good = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", good)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)

    def sectors_fail(url, timeout=None, headers=None):
        if "/sectors" in url:
            raise OSError("sectors down")
        return FakeResponse(good.overview)

    later = NOW + timedelta(seconds=31)
    good.overview = {
        "ok": True,
        "as_of": later.isoformat(),
        "regime": {"label": "risk_on"},
        "indexes": [{"code": "000001.SH", "change_pct": 1.2}],
    }
    monkeypatch.setattr("cn_watch.market_context.requests.get", sectors_fail)
    client.refresh(later)
    snapshot = client.snapshot(later)
    assert snapshot.ok is True
    assert snapshot.regime == "strong"
    assert snapshot.sectors == {}


def test_snapshot_defaults_are_safe():
    snapshot = MarketSnapshot()
    assert snapshot.ok is False
    assert snapshot.age_s is None
    assert snapshot.regime is None
    assert dict(snapshot.indexes) == {}
    assert dict(snapshot.sectors) == {}


def test_recovery_after_failure(monkeypatch):
    good = FakeHTTP()
    monkeypatch.setattr("cn_watch.market_context.requests.get", good)
    client = MarketContextClient("http://127.0.0.1:8866")
    client.refresh(NOW)
    assert client.snapshot(NOW).ok is True

    def broken(url, timeout=None, headers=None):
        raise OSError("down")

    monkeypatch.setattr("cn_watch.market_context.requests.get", broken)
    client.refresh(NOW + timedelta(seconds=5))
    assert client.snapshot(NOW + timedelta(seconds=5)).ok is False

    good.overview["as_of"] = (NOW + timedelta(seconds=10)).isoformat()
    good.sectors["as_of"] = (NOW + timedelta(seconds=10)).isoformat()
    monkeypatch.setattr("cn_watch.market_context.requests.get", good)
    client.refresh(NOW + timedelta(seconds=10))
    assert client.snapshot(NOW + timedelta(seconds=10)).ok is True
