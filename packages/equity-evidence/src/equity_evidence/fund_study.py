import re
from collections import defaultdict
from uuid import uuid4
from .funds import rankings, holdings
from .storage import library, save, stamp, snapshot


def study(limit, year):
    rank = rankings(limit)
    observed = defaultdict(list)
    failures = {}
    comparisons = []
    source_snapshots = {}
    for fund in rank["rows"]:
        code = fund["基金代码"]
        try:
            holding = holdings(code, year)
            source_snapshots[code] = snapshot({"result": holding})
            rows = holding["rows"]
            periods = defaultdict(dict)
            for r in rows:
                period = re.search(r"(\d{4})年(\d)季度", r["季度"])
                if period:
                    periods[tuple(map(int, period.groups()))][r["股票代码"]] = r
            if not periods:
                raise ValueError("缺少带季度的持仓明细")
            last = max(periods)
            for sid, r in periods[last].items():
                observed[sid].append(
                    {"fund": code, "period": last, "weight_pct": r["占净值比例"]}
                )
            if len(periods) > 1:
                prev = sorted(periods)[-2]
                for sid in sorted(periods[prev].keys() & periods[last].keys()):
                    before, after = periods[prev][sid], periods[last][sid]
                    comparisons.append(
                        {
                            "fund": code,
                            "stock": sid,
                            "previous": prev,
                            "latest": last,
                            "shares_delta_10k": after["持股数"] - before["持股数"],
                            "weight_delta_pp": after["占净值比例"]
                            - before["占净值比例"],
                        }
                    )
        except Exception as exc:
            failures[code] = type(exc).__name__
    key = uuid4().hex
    result = {
        "id": key,
        "observed": stamp(),
        "fund_snapshots": source_snapshots,
        "ranking_snapshot": snapshot({"result": rank}),
        "scope": rank["scope"],
        "interpretation": "只比较两期均披露的记录。股数差未校正送转，权重变化还受价格影响。各份额单列。",
        "failures": failures,
        "holdings": dict(observed),
        "changes": comparisons,
    }
    save(library() / f"studies/funds/{year}/study-{key}.json", result)
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, choices=range(1, 101), default=100)
    p.add_argument("--year", type=int, required=True)
    a = p.parse_args()
    r = study(a.limit, a.year)
    print(
        r["id"],
        "股票数",
        len(r["holdings"]),
        "可比记录",
        len(r["changes"]),
        "缺失基金",
        len(r["failures"]),
    )
