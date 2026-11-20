from __future__ import annotations

import pandas as pd
import pytest

from cn_research_mcp import sources
from cn_research_mcp.symbols import normalize_symbol


class Recorder:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.missing = missing or set()

    def __call__(self, name: str, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.missing:
            raise AttributeError(name)
        return pd.DataFrame({"ok": [1]})


def test_audit_allows_legacy_names():
    from cn_research_mcp.infra import audit_sources_text

    assert audit_sources_text('def f():\n    return _ak("stock_info_global_cls")\n') == []
    assert audit_sources_text('def f():\n    return _ak("news_economic_baidu")\n') == []


def test_stock_news_calls_expected_function_with_digits(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().stock_news(normalize_symbol("600519"))
    assert rec.calls == [("stock_news_em", (), {"symbol": "600519"})]


def test_irm_calls_expected_function_with_digits(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().irm_qa(normalize_symbol("002594"))
    assert rec.calls == [("stock_irm_cninfo", (), {"symbol": "002594"})]


def test_flash_cls_uses_new_name(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().flash_cls()
    assert rec.calls == [("stock_news_global_cls", (), {"symbol": "全部"})]


def test_flash_cls_falls_back_to_legacy_name(monkeypatch):
    rec = Recorder(missing={"stock_news_global_cls"})
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().flash_cls()
    assert [c[0] for c in rec.calls] == ["stock_news_global_cls", "stock_info_global_cls"]


def test_flash_em_falls_back_to_legacy_name(monkeypatch):
    rec = Recorder(missing={"stock_news_global_em"})
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().flash_em()
    assert [c[0] for c in rec.calls] == ["stock_news_global_em", "stock_info_global_em"]


def test_calendar_falls_back_to_legacy_name(monkeypatch):
    rec = Recorder(missing={"macro_calendar_baidu"})
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().econ_calendar("20261116")
    assert [c[0] for c in rec.calls] == ["macro_calendar_baidu", "news_economic_baidu"]
    assert rec.calls[-1][2] == {"date": "20261116"}


def test_suspensions_and_calendar_pass_yyyymmdd(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().suspensions("20261116")
    sources.Sources().econ_calendar("20261116")
    assert rec.calls == [
        ("stock_tfp_em", (), {"date": "20261116"}),
        ("macro_calendar_baidu", (), {"date": "20261116"}),
    ]


def test_flash_em_calls_expected_function(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(sources, "_ak", rec)
    sources.Sources().flash_em()
    assert rec.calls == [("stock_news_global_em", (), {})]


@pytest.mark.parametrize("method", ["stock_news", "flash_cls", "flash_em", "econ_calendar", "suspensions", "irm_qa"])
def test_new_endpoints_are_declared(method):
    assert method in sources.ENDPOINTS
