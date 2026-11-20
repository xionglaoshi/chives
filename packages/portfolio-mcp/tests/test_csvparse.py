from __future__ import annotations

from datetime import date, timedelta

import pytest

from portfolio_mcp.csvparse import parse_csv_text
from portfolio_mcp.errors import PortfolioError

BASIC = """证券代码,证券名称,股票余额,可用余额,成本价,参考市值,盈亏,手续费
600000,浦发银行,"1,000",500,10.50,"10,500.00",100.00,5.00
002553,南方精工,300,300,15.00,4749.00,-51.00,5.00
"""


def test_basic_comma_with_thousands_and_ignored_columns() -> None:
    parsed = parse_csv_text(BASIC)
    assert parsed["count"] == 2
    assert parsed["rejected"] == []
    assert parsed["rows"][0] == {
        "code": "600000.SH",
        "name": "浦发银行",
        "qty": 1000,
        "available_qty": 500,
        "cost_price": 10.5,
        "opened_date": None,
        "industry": None,
        "note": None,
    }
    assert parsed["columns"]["cost"] == "成本价"
    # market value / PnL / fee columns are not echoed into rows
    assert "market_value" not in parsed["rows"][0]


def test_tab_separated_huatai_style() -> None:
    text = (
        "证券代码\t证券名称\t股票余额\t可用余额\t成本价\t市价\t市值\t盈亏\n"
        "600000\t浦发银行\t1000\t500\t9.50\t10.00\t10000\t500\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["rows"][0]["qty"] == 1000
    assert parsed["rows"][0]["available_qty"] == 500


def test_citic_style_headers() -> None:
    text = "代码,名称,持仓数量,可用数量,成本价,现价,市值,盈亏比例\n600000,浦发银行,1000,500,9.50,10.00,10000,5%\n"
    parsed = parse_csv_text(text)
    assert parsed["rows"][0]["code"] == "600000.SH"


def test_ths_style_headers() -> None:
    text = "代码,名称,持股数量,可用数量,成本价\n600000,浦发银行,1000,500,9.50\n"
    assert parse_csv_text(text)["rows"][0]["qty"] == 1000


def test_aligned_multi_space() -> None:
    text = (
        "证券代码  证券名称  持仓数量  可用数量  成本价  市值\n"
        "600000    浦发银行  1000      500       9.50    9500\n"
        "000001    平安银行  2000      2000      11.20   22400\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["count"] == 2
    assert parsed["rows"][1]["code"] == "000001.SZ"


def test_blank_lines_and_crlf() -> None:
    text = (
        "\r\n"
        "证券代码,证券名称,股票余额,成本价\r\n"
        "\r\n"
        "600000,浦发银行,1000,9.5\r\n"
        "\r\n"
        "000001,平安银行,2000,11.2\r\n"
        "\r\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["count"] == 2
    assert parsed["rejected"] == []


def test_bom_title_line_and_repeated_header() -> None:
    text = (
        "\ufeff导出时间：2026-11-03 10:00:00\n"
        "证券代码,证券名称,股票余额,成本价\n"
        "600000,浦发银行,1000,9.5\n"
        "证券代码,证券名称,股票余额,成本价\n"
        "000001,平安银行,2000,11.2\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["count"] == 2
    assert parsed["rejected"] == []


def test_excel_text_prefix_and_prefix_zero() -> None:
    text = '代码,名称,数量,成本价\n="000001",平安银行,1000,11.20\n="600000",浦发银行,500,9.50\n'
    parsed = parse_csv_text(text)
    assert [row["code"] for row in parsed["rows"]] == ["000001.SZ", "600000.SH"]


def test_excel_stripped_leading_zero_and_single_quote() -> None:
    text = "代码,名称,数量,成本价\n1,平安银行,1000,11.2\n'000001,平安银行,1000,11.2\n"
    parsed = parse_csv_text(text)
    assert [row["code"] for row in parsed["rows"]] == ["000001.SZ"]
    assert parsed["rejected"][0]["reason"] == "duplicate_code"


def test_dash_empty_values_and_optional_columns() -> None:
    text = (
        "证券代码,证券名称,持仓数量,可用数量,成本价,行业,备注\n"
        "600000,浦发银行,1000,--,9.50,银行,--\n"
    )
    parsed = parse_csv_text(text)
    row = parsed["rows"][0]
    assert row["available_qty"] is None
    assert row["industry"] == "银行"
    assert row["note"] is None


def test_duplicate_code_is_rejected_not_merged() -> None:
    text = "代码,名称,数量,成本价\n600000,浦发银行,1000,9.5\n600000,浦发银行,2000,9.6\n"
    parsed = parse_csv_text(text)
    assert parsed["count"] == 1
    assert parsed["rejected"] == [{"line": 3, "reason": "duplicate_code", "field": "code"}]


def test_missing_required_headers() -> None:
    with pytest.raises(PortfolioError) as excinfo:
        parse_csv_text("代码,名称,数量\n600000,浦发银行,1000\n")
    assert excinfo.value.code == "missing_header"


def test_invalid_rows_are_rejected_with_reasons() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    text = (
        "代码,名称,数量,可用数量,成本价,建仓日期\n"
        "900901,退市股,100,100,1.0,2025-01-01\n"
        "600000,浦发银行,0,0,9.5,2025-01-01\n"
        "600001,空成本,100,100,0,2025-01-01\n"
        f"600002,未来日期,100,100,9.5,{tomorrow}\n"
        "600003,超可用,100,200,9.5,2025-01-01\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["count"] == 0
    reasons = [item["reason"] for item in parsed["rejected"]]
    assert reasons == [
        "invalid_code",
        "invalid_value",
        "invalid_value",
        "invalid_value",
        "invalid_value",
    ]


def test_column_count_mismatch_is_rejected() -> None:
    text = "代码,名称,数量,成本价\n600000,浦发银行,1000,9.5,EXTRA\n600000,浦发银行\n"
    parsed = parse_csv_text(text)
    assert parsed["count"] == 0
    assert [item["reason"] for item in parsed["rejected"]] == [
        "column_count_mismatch",
        "column_count_mismatch",
    ]


def test_short_row_is_rejected() -> None:
    text = "代码,名称,数量,成本价,行业,备注\n600000,浦发银行,1000,9.5\n"
    parsed = parse_csv_text(text)
    assert parsed["count"] == 0
    assert parsed["rejected"] == [{"line": 2, "reason": "column_count_mismatch"}]


def test_gbk_decoded_text_works() -> None:
    text = "证券代码,证券名称,股票余额,成本价\n600000,浦发银行,1000,9.5\n"
    gbk_roundtrip = text.encode("gbk").decode("gbk")
    assert parse_csv_text(gbk_roundtrip)["rows"][0]["name"] == "浦发银行"


def test_header_units_and_fullwidth_parentheses() -> None:
    text = "证券代码,证券名称,持仓数量（股）,成本价(元)\n600000,浦发银行,1000,9.5\n"
    parsed = parse_csv_text(text)
    assert parsed["rows"][0]["qty"] == 1000


def test_unquoted_thousands_are_rejoined() -> None:
    text = (
        "代码,名称,数量,可用数量,成本价\n"
        "600000,浦发银行,1,000,500,9.50\n"
        "000001,平安银行,2,500,2,500,11.20\n"
    )
    parsed = parse_csv_text(text)
    assert parsed["count"] == 2
    assert parsed["rows"][0]["qty"] == 1000
    assert parsed["rows"][1]["qty"] == 2500
    assert parsed["rows"][1]["available_qty"] == 2500


def test_unquoted_thousands_in_cost() -> None:
    text = "代码,名称,数量,成本价\n600000,浦发银行,100,1,234.56\n"
    assert parse_csv_text(text)["rows"][0]["cost_price"] == 1234.56


def test_cost_with_yuan_suffix_and_space_thousands() -> None:
    text = "代码,名称,数量,成本价\n600000,浦发银行,1 000,9.50元\n"
    assert parse_csv_text(text)["rows"][0]["qty"] == 1000


def test_target_column_is_rejected() -> None:
    text = (
        "证券代码,证券名称,股票余额,成本价,资金账号\n"
        f"600000,浦发银行,1000,9.5,{'12' * 6}\n"
    )
    with pytest.raises(PortfolioError) as excinfo:
        parse_csv_text(text)
    assert excinfo.value.code == "sensitive_text"


def test_empty_text() -> None:
    with pytest.raises(PortfolioError) as excinfo:
        parse_csv_text("  \n\n")
    assert excinfo.value.code == "empty_text"


def test_non_string_text() -> None:
    with pytest.raises(PortfolioError):
        parse_csv_text(None)
