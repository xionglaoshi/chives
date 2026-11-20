from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta

import pytest

from portfolio_mcp.fields import validate_positions
from portfolio_mcp.kline import GatewayKlineClient
from portfolio_mcp.risk import (
    annualized_volatility,
    board_of,
    correlation,
    max_drawdown,
)
from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioState

from helpers import FakeKlineServer, kline_rows

TODAY = date(2026, 11, 3)
BENCHMARK = "000300.SH"
BENCHMARK_SYMBOL = "sh000300"


def _days(count: int) -> list[str]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _closes(start: float, returns: list[float]) -> list[float]:
    values = [start]
    for value in returns:
        values.append(values[-1] * (1.0 + value))
    return values


def _pattern(values: list[float], count: int) -> list[float]:
    return [values[index % len(values)] for index in range(count)]


def _row(
    code: str,
    qty: int,
    *,
    name: str = "测试股票",
    cost: float = 10.0,
    industry: str | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "name": name,
        "qty": qty,
        "cost_price": cost,
        "industry": industry,
    }


def _seed(store, rows: list[dict[str, object]], cash: float | None = None) -> None:
    validated = validate_positions(rows, today=TODAY)
    store.apply(
        lambda state: PortfolioState(positions=validated, cash=cash, as_of="2026-11-03")
    )


def _service(store, *, min_interval: float = 0.0) -> PortfolioService:
    return PortfolioService(
        store,
        quotes=None,
        kline=GatewayKlineClient(min_interval=min_interval),
        today=lambda: TODAY,
    )


def _env(monkeypatch: pytest.MonkeyPatch, server: FakeKlineServer) -> None:
    monkeypatch.setenv("PORTFOLIO_GATEWAY_URL", server.base)


def _returns(closes: list[float]) -> list[float]:
    return [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]


def _expected_drawdown(returns: list[float]) -> float:
    nav = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        nav *= 1.0 + value
        peak = max(peak, nav)
        worst = max(worst, (peak - nav) / peak)
    return worst


def _expected_beta(returns: list[float], benchmark: list[float]) -> float:
    return statistics.covariance(returns, benchmark) / statistics.variance(benchmark)


def _assert_close(actual: float, expected: float) -> None:
    assert actual == pytest.approx(expected, rel=1e-6, abs=1e-9)


def test_empty_book_returns_status_empty_without_requests(store, monkeypatch) -> None:
    days = _days(5)
    server = FakeKlineServer({BENCHMARK_SYMBOL: {"day": kline_rows(days, [4000.0] * 5)}})
    _env(monkeypatch, server)
    try:
        payload = _service(store).risk({})
        assert payload["status"] == "empty"
        assert payload["private"] is True
        assert payload["data"]["observations"] == 0
        assert payload["data"]["positions"] == []
        assert "hint" in payload["data"]
        assert server.params == []
    finally:
        server.close()


@pytest.mark.parametrize("value", [59, 501, 60.5, True, "60", None])
def test_invalid_window_days_rejected(store, monkeypatch, value) -> None:
    server = FakeKlineServer({})
    _env(monkeypatch, server)
    try:
        payload = _service(store).risk({"window_days": value})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_argument"
        assert server.params == []
    finally:
        server.close()


@pytest.mark.parametrize(
    "value",
    ["000016.SH", "000300.SZ", "AAPL", "", "sh000300", "399001.SH", 123, None],
)
def test_invalid_benchmark_rejected(store, monkeypatch, value) -> None:
    server = FakeKlineServer({})
    _env(monkeypatch, server)
    try:
        payload = _service(store).risk({"benchmark": value})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_benchmark"
        assert server.params == []
    finally:
        server.close()


def test_all_benchmarks_in_whitelist_accepted(store, monkeypatch) -> None:
    days = _days(70)
    data = {
        "sh000300": {"day": kline_rows(days, _closes(4000.0, _pattern([0.001, -0.002], 69)))},
        "sh000001": {"day": kline_rows(days, _closes(3000.0, _pattern([0.002, -0.001], 69)))},
        "sh000905": {"day": kline_rows(days, _closes(5000.0, _pattern([0.003, -0.002], 69)))},
        "sh000852": {"day": kline_rows(days, _closes(6000.0, _pattern([0.001, 0.002], 69)))},
        "sz399001": {"day": kline_rows(days, _closes(10000.0, _pattern([0.002, 0.001], 69)))},
        "sz399006": {"day": kline_rows(days, _closes(2000.0, _pattern([0.004, -0.003], 69)))},
        "sh000688": {"day": kline_rows(days, _closes(900.0, _pattern([0.005, -0.004], 69)))},
        "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002, -0.001], 69)))},
    }
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        service = _service(store)
        for benchmark in (
            "000300.SH",
            "000001.SH",
            "000905.SH",
            "000852.SH",
            "399001.SZ",
            "399006.SZ",
            "000688.SH",
        ):
            payload = service.risk({"window_days": 60, "benchmark": benchmark})
            assert payload["ok"] is True
            assert payload["data"]["benchmark"] == benchmark
    finally:
        server.close()


def test_hand_computed_two_stock_metrics(store, monkeypatch) -> None:
    days = _days(70)
    bench_returns_all = _pattern([0.004, -0.003, 0.002, -0.001, 0.005, -0.002, 0.001], 69)
    a_returns_all = _pattern([0.006, -0.005, 0.004, -0.002, 0.007, -0.003, 0.002], 69)
    b_returns_all = _pattern([-0.003, 0.004, -0.001, 0.002, -0.004, 0.003, 0.0], 69)
    bench_closes = _closes(4000.0, bench_returns_all)
    a_closes = _closes(10.0, a_returns_all)
    b_closes = _closes(20.0, b_returns_all)

    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, bench_closes)},
            "sh600000": {"qfqday": kline_rows(days, a_closes)},
            "sz000001": {"qfqday": kline_rows(days, b_closes)},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("000001", 500)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["ok"] is True
        data = payload["data"]
        assert payload["private"] is True
        assert data["private"] is True
        assert data["benchmark"] == BENCHMARK
        assert data["window_days_requested"] == 60
        assert data["observations"] == 59
        assert data["as_of_bar_date"] == days[-1]
        assert data["methodology"]

        window_days = days[-60:]
        bench_window = bench_closes[-60:]
        a_window = a_closes[-60:]
        b_window = b_closes[-60:]
        bench_returns = _returns(bench_window)
        a_returns = _returns(a_window)
        b_returns = _returns(b_window)
        weights = {
            "600000.SH": a_window[-1] * 1000,
            "000001.SZ": b_window[-1] * 500,
        }
        total = sum(weights.values())
        weights = {code: value / total for code, value in weights.items()}
        portfolio_returns = [
            weights["600000.SH"] * a_returns[index]
            + weights["000001.SZ"] * b_returns[index]
            for index in range(len(bench_returns))
        ]

        _assert_close(data["annualized_vol_ratio"], statistics.stdev(portfolio_returns) * math.sqrt(252))
        _assert_close(data["beta"], _expected_beta(portfolio_returns, bench_returns))
        _assert_close(data["max_drawdown_ratio"], _expected_drawdown(portfolio_returns))
        _assert_close(
            data["benchmark_annualized_vol_ratio"], statistics.stdev(bench_returns) * math.sqrt(252)
        )
        _assert_close(
            data["benchmark_max_drawdown_ratio"], _expected_drawdown(bench_returns)
        )

        items = {item["code"]: item for item in data["positions"]}
        assert set(items) == {"600000.SH", "000001.SZ"}
        _assert_close(items["600000.SH"]["weight_ratio"], weights["600000.SH"])
        _assert_close(items["000001.SZ"]["weight_ratio"], weights["000001.SZ"])
        assert items["600000.SH"]["bars"] == 60
        assert items["000001.SZ"]["bars"] == 60
        _assert_close(
            items["600000.SH"]["annualized_vol_ratio"],
            statistics.stdev(a_returns) * math.sqrt(252),
        )
        _assert_close(
            items["000001.SZ"]["annualized_vol_ratio"],
            statistics.stdev(b_returns) * math.sqrt(252),
        )
        _assert_close(items["600000.SH"]["beta"], _expected_beta(a_returns, bench_returns))
        _assert_close(items["000001.SZ"]["beta"], _expected_beta(b_returns, bench_returns))
        _assert_close(
            items["600000.SH"]["max_drawdown_ratio"], _expected_drawdown(a_returns)
        )
        _assert_close(
            items["000001.SZ"]["max_drawdown_ratio"], _expected_drawdown(b_returns)
        )
        _assert_close(
            items["600000.SH"]["corr_to_portfolio"],
            statistics.correlation(a_returns, portfolio_returns),
        )
        _assert_close(
            items["000001.SZ"]["corr_to_portfolio"],
            statistics.correlation(b_returns, portfolio_returns),
        )

        ordered = sorted(weights.values(), reverse=True)
        _assert_close(data["top1_weight_ratio"], ordered[0])
        _assert_close(data["top5_weight_ratio"], sum(ordered[:5]))
        hhi = sum(value * value for value in ordered)
        _assert_close(data["hhi"], hhi)
        _assert_close(data["effective_n"], 1.0 / hhi)
        assert data["cash_share_ratio"] == 0.0
        _assert_close(sum(data["exposure_by_board"].values()), 1.0)
        _assert_close(sum(data["exposure_by_industry"].values()), 1.0)
        _assert_close(sum(data["asset_class"].values()), 1.0)
        assert data["exposure_by_industry"]["未标注"] == pytest.approx(1.0)
        assert len(data["largest_pair_correlations"]) == 1
        _assert_close(
            data["largest_pair_correlations"][0]["corr_ratio"],
            statistics.correlation(a_returns, b_returns),
        )
        assert server.params[0]["limit"] == 65
        assert server.params[0]["adjust"] == "none"
        assert all(
            param["limit"] == 65 and param["adjust"] == "qfq" for param in server.params[1:]
        )
    finally:
        server.close()


def test_default_window_is_250_and_requests_255_bars(store, monkeypatch) -> None:
    days = _days(70)
    data = {
        BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001, -0.002], 69)))},
        "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002, -0.001], 69)))},
    }
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        data_out = _service(store).risk({})["data"]
        assert data_out["window_days_requested"] == 250
        assert data_out["observations"] == 69
        assert server.params[0]["limit"] == 255
        assert server.params[0]["adjust"] == "none"
        assert all(
            param["limit"] == 255 and param["adjust"] == "qfq" for param in server.params[1:]
        )
    finally:
        server.close()


def test_excluded_insufficient_bars_and_weight_renormalization(store, monkeypatch) -> None:
    days = _days(70)
    bench_closes = _closes(4000.0, _pattern([0.001, -0.002], 69))
    a_closes = _closes(10.0, _pattern([0.002, -0.001], 69))
    b_closes = _closes(20.0, _pattern([-0.001, 0.002], 69))
    short_days = days[:30]
    short_closes = _closes(5.0, _pattern([0.001], 29))
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, bench_closes)},
            "sh600000": {"qfqday": kline_rows(days, a_closes)},
            "sz000001": {"qfqday": kline_rows(days, b_closes)},
            "sz300750": {"qfqday": kline_rows(short_days, short_closes)},
        }
    )
    _env(monkeypatch, server)
    _seed(
        store,
        [
            _row("600000", 1000),
            _row("000001", 500),
            _row("300750", 1000),
        ],
    )
    try:
        payload = _service(store).risk({"window_days": 60})
        data = payload["data"]
        assert "excluded_positions" in payload["warnings"]
        assert [item["code"] for item in data["positions"]] == ["600000.SH", "000001.SZ"]
        assert len(data["excluded"]) == 1
        excluded = data["excluded"][0]
        assert excluded["code"] == "300750.SZ"
        assert excluded["reason"] == "insufficient_bars"
        assert excluded["bars"] == 30
        weights = {item["code"]: item["weight_ratio"] for item in data["positions"]}
        _assert_close(sum(weights.values()), 1.0)
        expected = {
            "600000.SH": a_closes[-1] * 1000,
            "000001.SZ": b_closes[-1] * 500,
        }
        total = sum(expected.values())
        _assert_close(weights["600000.SH"], expected["600000.SH"] / total)
        _assert_close(weights["000001.SZ"], expected["000001.SZ"] / total)
    finally:
        server.close()


def test_excluded_missing_key_does_not_abort(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002], 69)))},
            "sz300750": {"day": kline_rows(days, _closes(5.0, _pattern([0.003], 69)))},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("300750", 1000)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["ok"] is True
        assert "excluded_positions" in payload["warnings"]
        assert payload["data"]["excluded"][0]["reason"] == "kline_unavailable"
        assert len(payload["data"]["positions"]) == 1
        _assert_close(payload["data"]["positions"][0]["weight_ratio"], 1.0)
    finally:
        server.close()


def test_suspension_day_is_forward_filled_with_zero_return(store, monkeypatch) -> None:
    days = _days(70)
    bench_closes = _closes(4000.0, _pattern([0.002, -0.001], 69))
    a_returns = _pattern([0.003, -0.002, 0.004, -0.001], 69)
    a_closes = _closes(10.0, a_returns)
    b_closes = _closes(20.0, _pattern([-0.001, 0.002], 69))
    # Remove one bar inside the 60-day window: the replay must use the prior close.
    missing_day = days[-30]
    a_rows = [row for row in kline_rows(days, a_closes) if row[0] != missing_day]
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, bench_closes)},
            "sh600000": {"qfqday": a_rows},
            "sz000001": {"qfqday": kline_rows(days, b_closes)},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("000001", 500)])
    try:
        data = _service(store).risk({"window_days": 60})["data"]
        items = {item["code"]: item for item in data["positions"]}
        assert items["600000.SH"]["bars"] == 59
        bench_window = bench_closes[-60:]
        a_window = a_closes[-60:]
        b_window = b_closes[-60:]
        bench_returns = _returns(bench_window)
        b_returns = _returns(b_window)
        weights = {
            "600000.SH": a_window[-1] * 1000,
            "000001.SZ": b_window[-1] * 500,
        }
        total = sum(weights.values())
        weights = {code: value / total for code, value in weights.items()}
        window_labels = days[-60:]
        missing_index = window_labels.index(missing_day)
        expected_a_returns = []
        for index in range(1, len(window_labels)):
            if index == missing_index:
                expected_a_returns.append(0.0)
            elif index - 1 == missing_index:
                expected_a_returns.append(a_window[index] / a_window[index - 2] - 1.0)
            else:
                expected_a_returns.append(a_window[index] / a_window[index - 1] - 1.0)
        portfolio_returns = [
            weights["600000.SH"] * expected_a_returns[index]
            + weights["000001.SZ"] * b_returns[index]
            for index in range(len(bench_returns))
        ]
        _assert_close(
            items["600000.SH"]["annualized_vol_ratio"],
            statistics.stdev(expected_a_returns) * math.sqrt(252),
        )
        _assert_close(data["annualized_vol_ratio"], statistics.stdev(portfolio_returns) * math.sqrt(252))
        _assert_close(items["600000.SH"]["beta"], _expected_beta(expected_a_returns, bench_returns))
    finally:
        server.close()


def test_as_of_bar_date_is_last_common_date(store, monkeypatch) -> None:
    days = _days(70)
    common_days = days[:66]
    bench_closes = _closes(4000.0, _pattern([0.001, -0.002], 69))
    a_closes = _closes(10.0, _pattern([0.002, -0.001], 65))
    b_closes = _closes(20.0, _pattern([-0.001, 0.002], 65))
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, bench_closes)},
            "sh600000": {"qfqday": kline_rows(common_days, a_closes)},
            "sz000001": {"qfqday": kline_rows(common_days, b_closes)},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("000001", 500)])
    try:
        data = _service(store).risk({"window_days": 60})["data"]
        assert data["as_of_bar_date"] == common_days[-1]
        assert data["observations"] == 59
        assert data["positions"][0]["bars"] == 60
    finally:
        server.close()


def test_benchmark_unavailable_when_day_key_missing(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"unexpected": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002], 69)))},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "benchmark_unavailable"
        assert payload["data"] == {}
    finally:
        server.close()


def test_benchmark_with_one_bar_is_unavailable(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {BENCHMARK_SYMBOL: {"day": kline_rows(days[:1], [4000.0])}}
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["error"]["code"] == "benchmark_unavailable"
    finally:
        server.close()


def test_benchmark_redirect_is_not_followed(store, monkeypatch) -> None:
    server = FakeKlineServer({}, status=302, location="http://127.0.0.1:9/evil")
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        payload = _service(store, min_interval=0.0).risk({"window_days": 60})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "benchmark_unavailable"
        assert len(server.calls) == 1
    finally:
        server.close()


def test_all_positions_excluded_returns_empty_without_estimates(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days[:30], _closes(10.0, _pattern([0.002], 29)))},
            "sz000001": {"day": kline_rows(days, _closes(20.0, _pattern([0.003], 69)))},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("000001", 1000)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["status"] == "empty"
        assert payload["data"]["positions"] == []
        assert payload["data"]["annualized_vol_ratio"] is None
        assert len(payload["data"]["excluded"]) == 2
        assert "excluded_positions" in payload["warnings"]
        assert "hint" in payload["data"]
    finally:
        server.close()


def test_exposure_board_asset_class_and_broad_index_etf(store, monkeypatch) -> None:
    days = _days(70)
    returns = _pattern([0.002, -0.001, 0.003, -0.002], 69)
    data = {
        BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, returns))},
    }
    rows = [
        _row("600000", 1000, industry="银行"),
        _row("300750", 100, industry="电池"),
        _row("688981", 100, industry="半导体"),
        _row("920418", 100, industry=None),
        _row("510300", 1000, name="沪深300ETF", industry=None),
    ]
    for row in rows:
        code = str(row["code"])
        symbol = ("sh" if code.startswith(("6", "5")) else "sz" if code.startswith(("0", "3", "1")) else "bj") + code
        data[symbol] = {"qfqday": kline_rows(days, _closes(10.0, returns))}
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    _seed(store, rows)
    try:
        result = _service(store).risk({"window_days": 60})["data"]
        items = {item["code"]: item for item in result["positions"]}
        assert items["600000.SH"]["board"] == "主板"
        assert items["300750.SZ"]["board"] == "创业板"
        assert items["688981.SH"]["board"] == "科创板"
        assert items["920418.BJ"]["board"] == "北交所"
        assert items["510300.SH"]["board"] == "ETF 基金"
        assert items["510300.SH"]["asset_class"] == "etf"
        assert items["600000.SH"]["asset_class"] == "stock"
        assert items["510300.SH"]["broad_index_etf"] is True
        assert items["600000.SH"]["broad_index_etf"] is False
        assert [item["code"] for item in result["broad_index_etfs"]] == ["510300.SH"]
        assert set(result["exposure_by_board"]) == {"主板", "创业板", "科创板", "北交所", "ETF 基金"}
        _assert_close(sum(result["exposure_by_board"].values()), 1.0)
        assert result["exposure_by_industry"]["未标注"] > 0.0
        _assert_close(sum(result["asset_class"].values()), 1.0)
        assert result["asset_class"]["etf"] == pytest.approx(items["510300.SH"]["weight_ratio"])
    finally:
        server.close()


def test_cash_share_ratio_uses_total_assets(store, monkeypatch) -> None:
    days = _days(70)
    a_closes = _closes(10.0, _pattern([0.002], 69))
    b_closes = _closes(20.0, _pattern([-0.001], 69))
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days, a_closes)},
            "sz000001": {"qfqday": kline_rows(days, b_closes)},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000), _row("000001", 500)], cash=5000.0)
    try:
        data = _service(store).risk({"window_days": 60})["data"]
        total_mv = a_closes[-1] * 1000 + b_closes[-1] * 500
        _assert_close(data["cash_share_ratio"], 5000.0 / (total_mv + 5000.0))
    finally:
        server.close()


def test_pair_correlations_sorted_and_capped_at_three(store, monkeypatch) -> None:
    days = _days(70)
    base_returns = _pattern([0.002, -0.001, 0.003, -0.002, 0.001], 69)
    data = {
        BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, base_returns))},
    }
    rows = []
    for index, multiplier in enumerate((1.0, 2.0, -1.0)):
        code = f"60000{index}"
        rows.append(_row(code, 1000))
        data[f"sh{code}"] = {
            "qfqday": kline_rows(days, _closes(10.0 + index, [value * multiplier for value in base_returns]))
        }
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    _seed(store, rows)
    try:
        result = _service(store).risk({"window_days": 60})["data"]
        pairs = result["largest_pair_correlations"]
        assert len(pairs) == 3
        values = [item["corr_ratio"] for item in pairs]
        assert values == sorted(values, reverse=True)
        pair_map = {
            frozenset((item["code_a"], item["code_b"])): item["corr_ratio"] for item in pairs
        }
        _assert_close(pair_map[frozenset(("600000.SH", "600001.SH"))], 1.0)
        _assert_close(pair_map[frozenset(("600000.SH", "600002.SH"))], -1.0)
        assert all(item["correlation"] == item["corr_ratio"] for item in pairs)
    finally:
        server.close()


def test_private_flag_on_ready_result(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002], 69)))},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["status"] == "ready"
        assert payload["private"] is True
        assert payload["data"]["private"] is True
        assert payload["data"]["untrusted_text"] is False
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    finally:
        server.close()


def test_no_cash_means_zero_cash_share(store, monkeypatch) -> None:
    days = _days(70)
    server = FakeKlineServer(
        {
            BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, _pattern([0.001], 69)))},
            "sh600000": {"qfqday": kline_rows(days, _closes(10.0, _pattern([0.002], 69)))},
        }
    )
    _env(monkeypatch, server)
    _seed(store, [_row("600000", 1000)])
    try:
        data = _service(store).risk({"window_days": 60})["data"]
        assert data["cash_share_ratio"] == 0.0
    finally:
        server.close()


def test_pure_math_helpers_match_hand_calculation() -> None:
    values = [0.01, -0.02, 0.03, 0.005]
    assert annualized_volatility(values) == pytest.approx(
        statistics.stdev(values) * math.sqrt(252)
    )
    assert max_drawdown([0.1, -0.2, 0.05]) == pytest.approx(0.2)
    assert correlation([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert board_of("510300.SH") == "ETF 基金"
    assert board_of("159915.SZ") == "ETF 基金"


def test_100_positions_use_exactly_101_serial_requests(store, monkeypatch) -> None:
    days = _days(70)
    returns = _pattern([0.001, -0.002], 69)
    data = {
        BENCHMARK_SYMBOL: {"day": kline_rows(days, _closes(4000.0, returns))},
    }
    rows = []
    for index in range(100):
        code = f"60{index:04d}"
        rows.append(_row(code, 100))
        data[f"sh{code}"] = {"qfqday": kline_rows(days, _closes(10.0, returns))}
    server = FakeKlineServer(data)
    _env(monkeypatch, server)
    _seed(store, rows)
    try:
        payload = _service(store).risk({"window_days": 60})
        assert payload["status"] == "ready"
        assert len(payload["data"]["positions"]) == 100
        assert len(server.calls) == 101
        assert server.params[0]["code"] == "sh000300"
        assert all(param["code"].startswith("sh60") for param in server.params[1:])
    finally:
        server.close()
