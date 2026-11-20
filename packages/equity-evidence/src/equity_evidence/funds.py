import akshare as ak
import json

from .storage import library, save, stamp


def table(frame):
    return json.loads(
        frame.to_json(orient="records", date_format="iso", force_ascii=False)
    )


def rankings(n):
    frame = ak.fund_open_fund_rank_em(symbol="股票型")
    import pandas as pd

    frame["近1年"] = pd.to_numeric(frame["近1年"], errors="coerce")
    frame = (
        frame.dropna(subset=["近1年"])
        .sort_values(["近1年", "基金代码"], ascending=[False, True])
        .head(n)
    )
    result = {
        "scope": "股票型基金份额，含不同份额类别，近一年收益率降序",
        "observed": stamp(),
        "source": "https://fund.eastmoney.com/data/fundranking.html",
        "rows": table(frame),
    }
    save(library() / f"studies/funds/{stamp()[:10]}/ranking-{n}.json", result)
    return result


def holdings(code, year):
    data = ak.fund_portfolio_hold_em(symbol=code, date=str(year))
    result = {
        "fund": code,
        "year": year,
        "retrieved": stamp(),
        "source": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
        "rows": table(data),
        "coverage": "各期已披露记录；需按季度列区分范围",
    }
    save(library() / f"studies/funds/{year}/{code}.json", result)
    return result
