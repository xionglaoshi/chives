from datetime import date
import json
from pathlib import Path
import pytest
import pandas as pd
from equity_evidence import filings
from equity_evidence.research import (
    financial_ratio,
    discounted_cashflow,
    valuation_scenarios,
)
from equity_evidence.cash_parser import subsequent
from equity_evidence.factors import compute, registry
from equity_evidence.registry import TOOLS
from equity_evidence.storage import library
from equity_evidence.evidence import cash_quality, research_snapshot, evidence_page


def test_catalog_matches_registration():
    catalog = json.loads(
        (Path(__file__).resolve().parents[3] / "config/equity-tools.json").read_bytes()
    )
    assert set(catalog) == {f.__name__ for f in TOOLS}


@pytest.mark.parametrize("scenario", ["up", "down", "flat", "halt", "short"])
def test_all_factors(scenario):
    bars = []
    for i in range(2 if scenario == "short" else 120):
        price = 1 + i if scenario == "up" else 200 - i if scenario == "down" else 100
        bars.append(
            dict(
                time=str(i),
                open=price,
                high=price + 1,
                low=price - 0.5,
                close=price,
                volume_shares=0 if scenario == "halt" else 100 + i,
            )
        )
    out = compute({"bars": bars}, registry())["values"]
    assert len(out) == 154 and out["qlib158_roc5"]["minimum_bars"] == 6
    ma = out["qlib158_ma5"]["value"]
    if scenario in ("short", "halt"):
        assert ma is None
    else:
        assert ma == pytest.approx(
            sum(r["close"] for r in bars[-5:]) / 5 / bars[-1]["close"]
        )
    for row in out.values():
        assert (row["value"] is None) == bool(row["missing"])


def test_unsigned_volume_and_tied_extremes():
    volume = pd.DataFrame({"A": [10, 9, 9, 12, 8, 11]}, dtype="uint32")
    factors = registry()
    losses = factors["qlib158_vsumn5"].compute({"volume": volume})
    assert losses.iloc[-1, 0] == pytest.approx(5 / 11)
    highs = pd.DataFrame({"A": [3, 5, 5, 2, 1]})
    position = factors["qlib158_imax5"].compute({"high": highs})
    assert position.iloc[-1, 0] == pytest.approx(2 / 5)


def test_valuation_boundaries():
    assert financial_ratio(3, 0)["value"] is None
    assert valuation_scenarios(2, [10])["scenarios"][0]["price"] == 20
    with pytest.raises(ValueError):
        valuation_scenarios(-1, [10])
    with pytest.raises(ValueError):
        discounted_cashflow(10, 0.03, 2, 0.04, 0.04, 0, 10)
    with pytest.raises(ValueError):
        discounted_cashflow(10, 0.03, 2, 0.08, 0.04, 0, 0)


def test_target_period_does_not_change_while_parsing(monkeypatch):
    rows = [
        dict(title=f"{year}年年度报告", date=f"{int(year) + 1}-04-01", url="")
        for year in ["2025", "2024"]
    ]
    monkeypatch.setattr(
        filings.gateway, "call", lambda *args: {"data": {"announcements": rows}}
    )
    assert (
        filings.discover("600519.SH", date(2026, 11, 19))[0][0]["period"]
        == "2025-12-31"
    )
    assert (
        filings.discover("600519.SH", date(2026, 11, 19), "2024-12-31")[0][0]["period"]
        == "2024-12-31"
    )


def test_no_estimated_receipt():
    assert subsequent(["检查期后回款情况。"])[0]["amount"] is None
    assert subsequent(["预计项目期后回款300万元。"])[0]["amount"] is None


@pytest.mark.parametrize(
    "code,gross,old,ratio",
    [
        ("920427.BJ", 129458673.97, 51303700.64, 3.74),
        ("688588.SH", 114242232.71, 2241490, 7.69),
    ],
)
def test_raw_pdf_evidence(code, gross, old, ratio):
    if not (library() / "filings" / code / "2026-11-18.json").exists():
        pytest.skip("需恢复冻结的公开公告")
    res = cash_quality(code, "2026-11-18")
    rec = json.loads(
        (library() / "snapshots" / (res["snapshot_id"] + ".json")).read_bytes()
    )["result"]
    latest = next(f for f in rec["filings"] if f["meta"]["period"] == "2026-09-30")
    half = next(f for f in rec["filings"] if f["meta"]["period"] == "2026-06-30")
    a = half["aging"]
    assert (
        abs(a["gross"] - gross) < 0.01
        and abs(sum(r["now"] for r in a["rows"] if r["start"] >= 3) - old) < 0.01
    )
    assert abs(a["gross"] - a["allowance"] - a["net"]) < 0.01
    st = latest["statements"]["合并"]
    assert round(st["cash"]["now"] / st["profit"]["now"], 2) == ratio
    assert (
        research_snapshot(res["snapshot_id"], "filings", 0)["value"]["meta"]["sha256"]
        == latest["meta"]["sha256"]
    )
    text = evidence_page(latest["meta"]["sha256"], st["cash"]["page"])["text"]
    assert "现金" in text
    hits = [r for f in rec["filings"] for r in f["receipts"]]
    if code.startswith("920"):
        assert any(h["amount"] == 3160000 and h["page"] == 39 for h in hits)
    else:
        assert hits and all(h["amount"] is None for h in hits)
