from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.store import PortfolioState, PortfolioStore


def _position(code: str, *, qty: int = 1000, cost: float = 9.5) -> dict[str, object]:
    return {
        "code": code,
        "name": "测试股票",
        "qty": qty,
        "available_qty": None,
        "cost_price": cost,
        "opened_date": None,
        "industry": None,
        "note": None,
    }


def test_read_does_not_create_anything(home: Path) -> None:
    store = PortfolioStore(profile_dir=home / "missing")
    snap = store.snapshot()
    assert snap.positions == []
    assert not (home / "missing").exists()
    assert not store.portfolio_path.exists()


def test_write_is_atomic_and_0600(store: PortfolioStore) -> None:
    mutation = store.apply(
        lambda state: PortfolioState(
            positions=[_position("600000")], cash=100.0, as_of="2026-11-03"
        )
    )
    assert mutation.changed is True
    assert store.portfolio_path.exists()
    mode = stat.S_IMODE(os.stat(store.portfolio_path).st_mode)
    assert mode == 0o600
    assert sorted(path.name for path in store.profile_dir.iterdir()) == [
        ".finance-portfolio.lock",
        "finance-portfolio.json",
    ]
    doc = json.loads(store.portfolio_path.read_text(encoding="utf-8"))
    assert doc["positions"][0]["code"] == "600000.SH"
    assert doc["cash"] == 100.0
    assert doc["as_of"] == "2026-11-03"


def test_no_op_does_not_rewrite(store: PortfolioStore) -> None:
    store.apply(lambda state: PortfolioState(positions=[_position("600000")]))
    before = store.portfolio_path.stat().st_mtime_ns
    mutation = store.apply(lambda state: PortfolioState(positions=state.positions))
    assert mutation.changed is False
    assert store.portfolio_path.stat().st_mtime_ns == before


def test_corrupt_json_is_empty_with_warning(store: PortfolioStore) -> None:
    store.profile_dir.mkdir(parents=True, exist_ok=True)
    store.portfolio_path.write_text("{not json", encoding="utf-8")
    snap = store.snapshot()
    assert snap.positions == []
    assert snap.warnings[0]["code"] == "portfolio_corrupt"


def test_wrong_shape_is_empty_with_warning(store: PortfolioStore) -> None:
    store.profile_dir.mkdir(parents=True, exist_ok=True)
    store.portfolio_path.write_text(json.dumps({"positions": "nope"}), encoding="utf-8")
    assert store.snapshot().warnings[0]["code"] == "portfolio_corrupt"


def test_invalid_or_duplicate_record_is_corrupt(store: PortfolioStore) -> None:
    store.profile_dir.mkdir(parents=True, exist_ok=True)
    store.portfolio_path.write_text(
        json.dumps({"positions": [{"code": "600000", "name": "x", "qty": 0, "cost_price": 1}]}),
        encoding="utf-8",
    )
    assert store.snapshot().warnings

    store.portfolio_path.write_text(
        json.dumps({"positions": [_position("600000"), _position("600000")]}),
        encoding="utf-8",
    )
    assert store.snapshot().warnings


def test_invalid_cash_and_as_of_are_corrupt(store: PortfolioStore) -> None:
    store.profile_dir.mkdir(parents=True, exist_ok=True)
    store.portfolio_path.write_text(
        json.dumps({"positions": [], "cash": -1}), encoding="utf-8"
    )
    assert store.snapshot().warnings
    store.portfolio_path.write_text(
        json.dumps({"positions": [], "as_of": "not-a-date"}), encoding="utf-8"
    )
    assert store.snapshot().warnings


def test_apply_rejects_too_many_and_duplicates(store: PortfolioStore) -> None:
    with pytest.raises(PortfolioError) as excinfo:
        store.apply(
            lambda state: PortfolioState(
                positions=[_position(f"6{index:05d}") for index in range(101)]
            )
        )
    assert excinfo.value.code == "too_many_positions"
    with pytest.raises(PortfolioError) as excinfo:
        store.apply(
            lambda state: PortfolioState(positions=[_position("600000"), _position("600000")])
        )
    assert excinfo.value.code == "duplicate_code"
    assert not store.portfolio_path.exists()


def test_overwrite_preserves_previous_document_when_change_raises(store: PortfolioStore) -> None:
    store.apply(lambda state: PortfolioState(positions=[_position("600000")]))
    original = store.portfolio_path.read_text(encoding="utf-8")

    def boom(state: PortfolioState) -> PortfolioState:
        raise PortfolioError("invalid_value", "boom")

    with pytest.raises(PortfolioError):
        store.apply(boom)
    assert store.portfolio_path.read_text(encoding="utf-8") == original
