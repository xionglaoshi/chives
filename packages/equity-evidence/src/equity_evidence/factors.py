from functools import lru_cache
from importlib import import_module
from pathlib import Path
import math
import re
import pandas as pd
from .market import daily

VERSION = "chives-qlib158-0.1.0"


@lru_cache
def registry():
    package = "equity_evidence.vendor.src.factors.zoo.qlib158"
    directory = Path(__file__).parent / "vendor/src/factors/zoo/qlib158"
    result = {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = import_module(package + "." + path.stem)
        result[module.__alpha_meta__["id"]] = module
    return result


def metadata(module):
    meta = module.__alpha_meta__
    # Rolling N changes/returns or an N-day lag require N+1 price observations.
    lagged = re.fullmatch(
        r"qlib158_(?:roc|cnt[dpn]|cord|v?sum[dpn]|wvma)([0-9]+)", meta["id"]
    )
    return {
        **meta,
        "min_warmup_bars": int(lagged[1]) + 1 if lagged else meta["min_warmup_bars"],
    }


def factor_catalog(query: str = "", offset: int = 0, limit: int = 25) -> dict:
    """List/search factor IDs, formulas, required inputs and stated minimum history."""
    if offset < 0 or not 1 <= limit <= 154:
        raise ValueError("limit 应在 1 至 154 之间，offset 应非负")
    rows = [
        metadata(m)
        for k, m in registry().items()
        if query.lower() in k or query.lower() in " ".join(m.__alpha_meta__["theme"])
    ]
    return dict(
        version=VERSION, matched=len(rows), factors=rows[offset : offset + limit]
    )


def compute(series, keys):
    rows = series["bars"]
    panel = {
        k: pd.DataFrame(
            {"value": [r.get("volume_shares" if k == "volume" else k) for r in rows]},
            index=[r["time"] for r in rows],
            dtype=float,
        )
        for k in ("open", "close", "high", "low", "volume")
    }
    values = {}
    for key in keys:
        mod = registry()[key]
        meta = metadata(mod)
        window = meta["min_warmup_bars"]
        reason = None
        value = None
        if len(rows) < window:
            reason = "有效历史不足"
        elif not rows or rows[-1].get("volume_shares") == 0:
            reason = "无成交日"
        elif any(
            panel[k].tail(window).isna().any().iloc[0] for k in meta["columns_required"]
        ):
            reason = "所需输入缺失"
        else:
            num = float(mod.compute(panel).iloc[-1, 0])
            if math.isfinite(num):
                value = num
            else:
                reason = "窗口未就绪、分母或方差为零"
        values[key] = dict(
            value=value,
            minimum_bars=window,
            formula=meta["formula_latex"],
            missing=reason,
        )
    return {
        **{k: v for k, v in series.items() if k != "bars"},
        "history_bars": len(rows),
        "version": VERSION,
        "values": values,
    }


def factor_values(code: str, factors: list[str], as_of: str = "") -> dict:
    """Calculate selected Qlib factors on pre-adjusted A-share daily bars. Accepts ma5 or qlib158_ma5."""
    keys = [
        k.lower() if k.lower().startswith("qlib158_") else "qlib158_" + k.lower()
        for k in factors
    ]
    if not 1 <= len(keys) <= 154 or any(k not in registry() for k in keys):
        raise ValueError("请从 factor_catalog 选择 1 至 154 个因子")
    return compute(daily(code, 120, "qfq", as_of), keys)
