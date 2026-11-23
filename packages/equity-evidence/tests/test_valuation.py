from copy import deepcopy
from equity_evidence.valuation import evaluate, visible_reports, peer_bands
from equity_evidence.valuation_calibration import sentiment, calibrate, apply_validated
from equity_evidence.storage import save
from equity_evidence.valuation_data import financial_versions


def test_known_then_financials():
    a = dict(CURRENCY="CNY", REPORT_DATE="2023-12-31", NOTICE_DATE="2024-04-20")
    rows = [
        {**a, "UPDATE_DATE": "2024-04-21", "BPS": 8},
        {**a, "UPDATE_DATE": "2025-01-02", "BPS": 10},
    ]
    assert not visible_reports(rows, "2024-04-19")
    assert visible_reports(rows, "2024-05-01")["2023-12-31"]["BPS"] == 8


def test_archived_report_preserves_its_actual_observation_date(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8))).date()
    monkeypatch.setenv("CHIVES_RESEARCH_LIBRARY", str(tmp_path))
    row = dict(
        CURRENCY="CNY",
        REPORT_DATE="2023-12-31",
        NOTICE_DATE="2024-04-20",
        UPDATE_DATE="2024-04-21",
        BPS=8,
    )
    financial_versions("600000.SH", [row], today.isoformat())
    missing = financial_versions("600000.SH", [], today.isoformat())
    assert visible_reports(missing, today.isoformat())["2023-12-31"] == row
    assert not visible_reports(missing, (today - timedelta(days=1)).isoformat())


def sample():
    rows = []
    for d in [
        "2023-01-31",
        "2023-03-31",
        "2023-04-28",
        "2024-01-31",
        "2024-02-29",
        "2024-03-29",
    ]:
        for i, m in enumerate([8, 10, 12, 14, 16]):
            rows.append(dict(SECUCODE=str(i), TRADE_DATE=d, PE_TTM=m, PB_MRQ=1))
        rows.append(dict(SECUCODE="600000.SH", TRADE_DATE=d, PE_TTM=999999, PB_MRQ=500))
    return dict(
        quote=dict(
            SECUCODE="600000.SH",
            TRADE_DATE="2024-04-30",
            BOARD_NAME="制造业",
            TOTAL_SHARES=10,
            CLOSE_PRICE=30,
            PB_MRQ=3,
        ),
        peers=rows,
        reports=[
            dict(
                CURRENCY="CNY",
                REPORT_DATE="2023-12-31",
                NOTICE_DATE="2024-04-26",
                UPDATE_DATE="2024-04-27",
                PARENTNETPROFIT=40,
                KCFJCXSYJLR=20,
                BPS=10,
            )
        ],
    )


def test_price_independence_and_loss():
    inputs = sample()
    r = evaluate("600000.SH", "2024-04-30", deepcopy(inputs))
    assert r["static"] == {"low": 20, "mid": 24, "high": 28} and r["dynamic"] is None
    inputs["quote"]["CLOSE_PRICE"] *= 3
    assert (
        evaluate("600000.SH", "2024-04-30", deepcopy(inputs))["static"] == r["static"]
    )
    inputs["reports"][0]["KCFJCXSYJLR"] = -1
    assert evaluate("600000.SH", "2024-04-30", inputs)["static"] is None
    assert all(
        "600000.SH" not in m["peer_codes"]
        for m in peer_bands(inputs["peers"], "600000.SH", "PE_TTM", None)
    )


def test_sentiment_and_calibration_are_point_in_time(tmp_path, monkeypatch):
    events = [
        dict(
            orgCode=i,
            infoCode=str(i),
            publishDate="2024-04-01",
            emRatingName="买入",
            lastEmRatingName="中性",
        )
        for i in (1, 2, 3)
    ]
    assert sentiment(events + events, "2024-04-02")["institutions"] == 3
    assert sentiment(events, "2024-04-01")["value"] is None
    assert "model" not in calibrate([], "600000.SH", "v1", "2024-04-30")
    monkeypatch.setenv("CHIVES_RESEARCH_LIBRARY", str(tmp_path))
    r = evaluate("600000.SH", "2024-04-30", sample())
    r["signals"]["market"] = {"sh_60d": 0.05, "sz_60d": 0.03}
    path = tmp_path / "valuations/calibration/600000.SH/2024-04-30.json"
    save(
        path,
        dict(
            code=r["code"],
            model_version=r["model_version"],
            validated_through=path.stem,
            holdout={"passed": True},
            model={"names": ["market"], "weights": [0.2], "errors": [-0.1, 0.1]},
        ),
    )
    apply_validated(r)
    assert r["dynamic"] is None
    r["as_of"] = "2024-05-01"
    apply_validated(r)
    assert (
        r["dynamic"]["low"] < r["dynamic"]["mid"] < r["dynamic"]["high"]
        and r["dynamic"]["mid"] > r["static"]["mid"]
    )
    path.write_text("{")
    r["dynamic"] = None
    apply_validated(r)
    assert r["dynamic"] is None


def test_losses_use_revenue_and_loss_peers_not_negative_pe():
    inputs = sample()
    inputs["reports"][0].update(KCFJCXSYJLR=-3, TOTALOPERATEREVE=100)
    for row in inputs["peers"]:
        row.update(PS_TTM=2, PE_TTM=-20)
    result = evaluate("600000.SH", "2024-04-30", inputs)
    assert result["method"] == "亏损企业可比 PS"
    assert result["static"] == {"low": 20, "mid": 20, "high": 20}
    assert result["comparable_ratio"] == -0.03 and result["quality_roe"] is None
    inputs["reports"][0]["TOTALOPERATEREVE"] = 0
    assert evaluate("600000.SH", "2024-04-30", inputs)["static"] is None


def test_direction_asof_no_future_labels_and_suspension():
    from datetime import date, timedelta
    import math
    from equity_evidence.valuation_direction import assess_direction

    days = [(date(2019, 1, 1) + timedelta(days=i)).isoformat() for i in range(1100)]
    indices = {d: {"000001": 3000 + i, "399001": 9000 + i} for i, d in enumerate(days)}
    history = [
        dict(
            TRADE_DATE=d,
            CHANGE_RATE=math.sin(i / 30) * 1.5,
            PB_MRQ=2 + math.sin(i / 200),
        )
        for i, d in enumerate(days)
    ]
    cutoff = days[799]
    full, audit = assess_direction(history, indices, cutoff)
    before, _ = assess_direction(
        history[:800], dict(list(indices.items())[:800]), cutoff
    )
    assert full == before
    replay = next(
        r
        for r in assess_direction(history, indices, days[-1])[1]["windows"]
        if r["date"] == cutoff
    )
    assert replay["predicted"] == ((full["score"] > 0) - (full["score"] < 0))
    windows = audit["windows"]
    assert all(r["predicted"] == r["base"] for r in windows[1:])
    assert all(r["end"] <= cutoff for r in windows)
    assert all(a["end"] <= b["date"] for a, b in zip(windows, windows[1:]))
    assert assess_direction(history[:795], indices, cutoff)[0] is None
