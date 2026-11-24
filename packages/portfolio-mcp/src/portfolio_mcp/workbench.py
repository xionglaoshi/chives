"""Local workbench adapter for the same locked ledger used by the portfolio tools."""
import json
import sys
from pathlib import Path
from portfolio_mcp.symbols import normalize_symbol
from portfolio_mcp.errors import PortfolioError
from portfolio_mcp.service import PortfolioService
from portfolio_mcp.store import PortfolioStore


class EditStore(PortfolioStore):
    def __init__(self, expected):
        super().__init__()
        self.expected = expected

    def apply(self, change):
        def checked(state):
            if state.warnings:
                raise PortfolioError("portfolio_corrupt", "持仓文件异常，请先恢复备份。")
            if self.expected is not None and self.expected not in state.positions:
                raise PortfolioError("stale", "这条持仓已经变化，请刷新后再编辑。")
            return change(state)
        return super().apply(checked)


def run(body):
    action = body.get("action")
    row = body.get("row", {})
    expected = body.get("original")
    service = PortfolioService(EditStore(expected), quotes=None, kline=None)
    if action == "get":
        return service.get()
    if action in ("quote", "add"):
        directory = Path(__file__).resolve().parents[4] / "apps/web/public/holdings-securities.json"
        names = json.loads(directory.read_text(encoding="utf-8"))
    if action == "quote":
        from portfolio_mcp.workbench_price import read_price
        return {"ok": True, "warnings": [], "data": read_price(body.get("code"), names)}
    if action == "add":
        try:
            code = normalize_symbol(row.get("code")).canonical
        except PortfolioError:
            code = None
        if code not in names or names[code] != row.get("name"):
            return {"ok": False, "error": {"code": "invalid_security", "message": "证券代码或简称有误，请从本地证券名录中选择。"}}
        result = service.add_position(dict(row, merge=False))
    elif action in ("edit", "remove") and isinstance(expected, dict) and expected.get("code"):
        args = {"code": expected["code"]}
        if action == "edit":
            result = service.update_position(dict(args, fields=row))
        else:
            result = service.remove_position(args)
    else:
        raise ValueError("未知持仓操作")
    return service.get() if result["ok"] else result


if __name__ == "__main__":
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
