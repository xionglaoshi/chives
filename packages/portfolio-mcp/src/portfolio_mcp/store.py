"""JSON persistence for the portfolio: locking, atomic writes, corrupt-file recovery."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from portfolio_mcp.atomic import atomic_write_text
from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.fields import (
    MAX_POSITIONS,
    PORTFOLIO_VERSION,
    validate_cash,
    validate_position,
)
from portfolio_mcp.paths import PORTFOLIO_FILENAME, resolve_portfolio_dir

LOCK_FILENAME = ".finance-portfolio.lock"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PortfolioState:
    positions: list[dict[str, Any]] = field(default_factory=list)
    cash: float | None = None
    as_of: str | None = None
    updated_at: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Mutation:
    before: PortfolioState
    after: PortfolioState
    changed: bool
    warnings: list[dict[str, Any]]


def _corrupt(message: str) -> dict[str, Any]:
    return {"code": "portfolio_corrupt", "message": message}


def _empty_state() -> PortfolioState:
    return PortfolioState()


class PortfolioStore:
    """One portfolio file; every mutation is read-modify-write under an exclusive lock."""

    def __init__(
        self,
        *,
        profile_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.profile_dir = (
            Path(profile_dir) if profile_dir is not None else resolve_portfolio_dir(env)
        )
        self.portfolio_path = self.profile_dir / PORTFOLIO_FILENAME
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.profile_dir / LOCK_FILENAME
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _corrupt_state(self, message: str) -> PortfolioState:
        return PortfolioState(warnings=[_corrupt(message)])

    def _load(self) -> PortfolioState:
        try:
            raw = json.loads(self.portfolio_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_state()
        except (OSError, UnicodeDecodeError, ValueError):
            return self._corrupt_state(
                "finance-portfolio.json is unreadable or not valid JSON; treated as empty"
            )
        if not isinstance(raw, dict) or not isinstance(raw.get("positions"), list):
            return self._corrupt_state(
                "finance-portfolio.json has an unexpected shape; treated as empty"
            )

        positions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in raw["positions"]:
            try:
                position = validate_position(record)
            except PortfolioError:
                return self._corrupt_state(
                    "finance-portfolio.json contains an invalid position record; treated as empty"
                )
            if position["code"] in seen:
                return self._corrupt_state(
                    "finance-portfolio.json contains duplicate position codes; treated as empty"
                )
            seen.add(position["code"])
            positions.append(position)
        if len(positions) > MAX_POSITIONS:
            return self._corrupt_state(
                "finance-portfolio.json contains more positions than supported; treated as empty"
            )

        cash: float | None = None
        if raw.get("cash") is not None:
            try:
                cash = validate_cash(raw["cash"])
            except PortfolioError:
                return self._corrupt_state(
                    "finance-portfolio.json has an invalid cash value; treated as empty"
                )

        as_of: str | None = None
        if raw.get("as_of") is not None:
            if not isinstance(raw["as_of"], str):
                return self._corrupt_state(
                    "finance-portfolio.json has an invalid as_of value; treated as empty"
                )
            try:
                as_of = date.fromisoformat(raw["as_of"]).isoformat()
            except ValueError:
                return self._corrupt_state(
                    "finance-portfolio.json has an invalid as_of value; treated as empty"
                )

        updated_at = raw.get("updated_at")
        if not isinstance(updated_at, str):
            updated_at = None
        trades = raw.get("trades", [])
        if not isinstance(trades, list) or any(not isinstance(t,dict) or "id" not in t for t in trades):
            return self._corrupt_state("invalid trade history")
        return PortfolioState(
            positions=positions, cash=cash, as_of=as_of, updated_at=updated_at, trades=trades
        )

    def snapshot(self) -> PortfolioState:
        """Read-only: a read never creates the directory, lock file or portfolio file."""
        if not self.profile_dir.is_dir():
            return _empty_state()
        return self._load()

    def _document(self, state: PortfolioState) -> str:
        doc = {
            "version": PORTFOLIO_VERSION,
            "updated_at": state.updated_at,
            "as_of": state.as_of,
            "cash": state.cash,
            "positions": [{name: row[name] for name in row} for row in state.positions],
        }
        if state.trades:
            doc["trades"] = state.trades
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    def apply(
        self,
        change: Callable[[PortfolioState], PortfolioState],
    ) -> Mutation:
        """Run change() on the current state and persist the result atomically."""
        with self._locked():
            snap = self._load()
            warnings = list(snap.warnings)
            before = copy.deepcopy(snap)
            proposed = change(copy.deepcopy(snap))
            if not isinstance(proposed, PortfolioState):
                raise PortfolioError("internal_error", "store change must return a state")

            positions = [validate_position(row) for row in proposed.positions]
            seen: set[str] = set()
            for row in positions:
                if row["code"] in seen:
                    raise PortfolioError(
                        "duplicate_code", f"duplicate position code: {row['code']}", field="code"
                    )
                seen.add(row["code"])
            if len(positions) > MAX_POSITIONS:
                raise PortfolioError(
                    "too_many_positions",
                    f"at most {MAX_POSITIONS} positions are supported",
                )
            cash = None if proposed.cash is None else validate_cash(proposed.cash)
            as_of = proposed.as_of
            if as_of is not None:
                try:
                    as_of = date.fromisoformat(as_of).isoformat()
                except ValueError as exc:
                    raise PortfolioError("invalid_value", "as_of must be YYYY-MM-DD") from exc

            after = PortfolioState(
                positions=positions,
                cash=cash,
                as_of=as_of,
                updated_at=snap.updated_at,
                trades=proposed.trades,
            )
            changed = (
                before.trades != after.trades
                or before.positions != after.positions
                or before.cash != after.cash
                or before.as_of != after.as_of
            )
            if changed:
                after.updated_at = _now()
                atomic_write_text(self.portfolio_path, self._document(after))
            return Mutation(before=before, after=after, changed=changed, warnings=warnings)
