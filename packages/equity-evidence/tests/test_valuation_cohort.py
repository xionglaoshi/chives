from copy import deepcopy

from pytest import approx

from equity_evidence.valuation_cohort import returns, summarize


def test_suspension_is_not_flat():
    rows = {"2024-01-01": {"CHANGE_RATE": 10}, "2024-01-03": {"CHANGE_RATE": -10}}
    assert returns(rows, list(rows)) == approx([1.1, 0.99])
    assert returns(rows, ["2024-01-01", "2024-01-02"]) is None


def test_split_and_showcase_do_not_train_the_candidate():
    rows = []
    for horizon in (20, 120):
        for start, end in [
            ("2023-12-29", "2024-06-25"),
            ("2024-12-31", "2025-06-25"),
            ("2025-03-31", "2025-09-22"),
            ("2025-05-28", "2025-11-21"),
        ]:
            rows.append(
                dict(
                    date=start,
                    end=end,
                    horizon=horizon,
                    close=10,
                    anchor=11,
                    static=None,
                    momentum=0.03,
                    production=None,
                    history=1,
                    target=1.08,
                    terminal=1.07,
                    gap="财报不可用",
                    mature=True,
                )
            )
    first = summarize(rows, "2025-01-01", "2025-05-28")
    changed = deepcopy(rows)
    for row in changed:
        if row["end"] >= "2025-01-01":
            row["target"] = 0.8
    second = summarize(changed, "2025-01-01", "2025-05-28")
    for h in ("20", "120"):
        assert first[h]["model"] == second[h]["model"]
        assert first[h]["model"]["count"] == 1
        assert first[h]["test"]["scheduled"] == first[h]["example"]["scheduled"] == 1
        assert first[h]["crossing_split"] == 1
