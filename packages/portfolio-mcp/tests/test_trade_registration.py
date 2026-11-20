from datetime import date
from uuid import uuid4
from portfolio_mcp.store import PortfolioStore
from portfolio_mcp.service import PortfolioService


def test_trade_preview_replay_conflict_and_same_book(tmp_path):
    store = PortfolioStore(profile_dir=tmp_path)
    service = PortfolioService(store=store)
    args = dict(
        id=str(uuid4()),
        code="600519.SH",
        side="buy",
        shares=100,
        price=10,
        fees=2,
        date=date.today().isoformat(),
    )
    service.record_trade(args)
    assert not store.portfolio_path.exists()
    service.record_trade(dict(args, confirm=True))
    service.record_trade(dict(args, confirm=True))
    assert (
        store.snapshot().positions[0]["qty"] == 100
        and store.snapshot().positions[0]["cost_price"] == 10.02
    )
    service.record_trade(dict(args, price=15, confirm=True))
    service.record_trade(
        dict(args, id=str(uuid4()), side="sell", shares=101, confirm=True)
    )
    assert len(store.snapshot().trades) == 1
    service.set_cash({"cash": 500})
    assert len(store.snapshot().trades) == 1
    service.record_trade(dict(args, id=str(uuid4()), side="sell", confirm=True))
    assert not store.snapshot().positions and len(store.snapshot().trades) == 2
