"""Strict YAML configuration loading and validation for cn-watch."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import replace
from datetime import date, time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from .models import (
    AlertsConfig,
    ApiConfig,
    CalendarConfig,
    LimitsConfig,
    PollingConfig,
    Rule,
    WatchConfig,
)

MAX_WATCHLIST = 80
DEFAULT_MAX_WATCHLIST = 10
DEFAULT_MAX_RULES = 30
BJ_PREFIXES = ("92", "43", "83", "87", "88")
SH_FIRST_DIGITS = {"5", "6", "9"}
INDEX_PREFIXES = ("399",)
RULE_TYPES = {
    "pct_change",
    "vwap_deviation",
    "limit_proximity",
    "price_cross",
    "volume_surge",
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
MARKET_LOOPBACK_HOSTS = LOOPBACK_HOSTS | {"::1"}
DEFAULT_MARKET_WATCH_URL = "http://127.0.0.1:8866"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8868"
CALENDAR_SOURCES = {"weekdays", "file", "akshare"}
_WINDOW_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})-(\d{2}):(\d{2}):(\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
logger = logging.getLogger("cn_watch.config")


class ConfigError(Exception):
    """Raised when the configuration file is missing, malformed or invalid."""


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} 必须是映射")
    return value


def _sequence(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{where} 必须是列表")
    return value


def _string(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{where} 必须是非空字符串")
    return value.strip()


def _number(
    value: Any,
    where: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{where} 必须是有限数字")
    if positive and number <= 0:
        raise ConfigError(f"{where} 必须是正数")
    if nonnegative and number < 0:
        raise ConfigError(f"{where} 不能为负数")
    return number


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{where} 必须是正整数")
    return value


def _infer_suffix(digits: str) -> str:
    return "SH" if digits[0] in SH_FIRST_DIGITS else "SZ"


def _is_index_code(digits: str, suffix: str) -> bool:
    """Reject exchange index families; stocks and funds must keep working."""
    if digits.startswith(INDEX_PREFIXES):
        return True
    # 000xxx is a Shenzhen stock but a Shanghai index (000001.SH, 000300.SH).
    if suffix == "SH" and digits.startswith("000"):
        return True
    return digits == "999999"


def normalize_code(value: Any, where: str = "代码") -> str:
    """Turn 002553 / 002553.SZ / 600000.SH into an exchange-qualified code."""
    if isinstance(value, bool):
        raise ConfigError(f"{where} 格式错误: {value!r}")
    if isinstance(value, int):
        if not 0 <= value <= 999999:
            raise ConfigError(f"{where} 格式错误: {value!r}")
        raw = f"{value:06d}"
    elif isinstance(value, str):
        raw = value.strip().upper()
    else:
        raise ConfigError(f"{where} 格式错误: {value!r}")

    suffix = ""
    digits = raw
    if "." in raw:
        digits, suffix = raw.rsplit(".", 1)
        if suffix not in {"SZ", "SH"}:
            raise ConfigError(f"{where} 格式错误: {value!r}")
    if len(digits) != 6 or not digits.isdigit():
        raise ConfigError(f"{where} 格式错误: {value!r}")
    if not suffix:
        suffix = _infer_suffix(digits)
    if _is_index_code(digits, suffix):
        raise ConfigError(f"{where} 是暂不支持的指数代码: {value!r}")
    return f"{digits}.{suffix}"


class SymbolError(ValueError):
    """A watchlist code was rejected; ``code`` is the machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_watch_code(value: Any) -> str:
    """Normalize a runtime watchlist code, refusing BJ and index codes."""
    if isinstance(value, bool):
        raise SymbolError("invalid_symbol", f"代码格式错误: {value!r}")
    if isinstance(value, int):
        if not 0 <= value <= 999999:
            raise SymbolError("invalid_symbol", f"代码格式错误: {value!r}")
        raw = f"{value:06d}"
    elif isinstance(value, str):
        raw = value.strip().upper()
    else:
        raise SymbolError("invalid_symbol", f"代码格式错误: {value!r}")

    suffix = ""
    digits = raw
    if "." in raw:
        digits, suffix = raw.rsplit(".", 1)
        if suffix == "BJ":
            raise SymbolError("unsupported_market", "引擎暂不支持北交所")
        if suffix not in {"SZ", "SH"}:
            raise SymbolError("invalid_symbol", f"代码格式错误: {value!r}")
    if len(digits) != 6 or not digits.isdigit():
        raise SymbolError("invalid_symbol", f"代码格式错误: {value!r}")
    if digits.startswith(BJ_PREFIXES):
        raise SymbolError("unsupported_market", "引擎暂不支持北交所")
    if not suffix:
        suffix = _infer_suffix(digits)
    if _is_index_code(digits, suffix):
        raise SymbolError("unsupported_instrument", "引擎暂不支持指数代码")
    return f"{digits}.{suffix}"


def parse_market_watch_url(value: Any) -> str:
    """Validate the read-only market-watch base URL; only loopback is allowed."""
    if value is None:
        return DEFAULT_MARKET_WATCH_URL
    text = _string(value, "market_watch_url")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"}:
        raise ConfigError("market_watch_url 只支持 http/https")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("market_watch_url 不允许包含凭据")
    host = (parts.hostname or "").lower()
    if host not in MARKET_LOOPBACK_HOSTS:
        raise ConfigError(f"market_watch_url 必须是回环地址，实际 {host!r}")
    try:
        parts.port
    except ValueError as exc:
        raise ConfigError("market_watch_url 端口非法") from exc
    if parts.query or parts.fragment:
        raise ConfigError("market_watch_url 不能带查询串或片段")
    return text.rstrip("/")


def parse_gateway_url(value: Any) -> str:
    """Validate the market-data gateway base URL; only loopback is allowed."""
    if value is None:
        return DEFAULT_GATEWAY_URL
    text = _string(value, "gateway_url")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"}:
        raise ConfigError("gateway_url 只支持 http/https")
    if parts.username is not None or parts.password is not None:
        raise ConfigError("gateway_url 不允许包含凭据")
    host = (parts.hostname or "").lower()
    if host not in MARKET_LOOPBACK_HOSTS:
        raise ConfigError(f"gateway_url 必须是回环地址，实际 {host!r}")
    try:
        parts.port
    except ValueError as exc:
        raise ConfigError("gateway_url 端口非法") from exc
    if parts.query or parts.fragment:
        raise ConfigError("gateway_url 不能带查询串或片段")
    return text.rstrip("/")


def _code_list(value: Any, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = _sequence(value, where)
    if not items and not allow_empty:
        raise ConfigError(f"{where} 不能为空")
    seen: list[str] = []
    for index, item in enumerate(items):
        code = normalize_code(item, f"{where}[{index}]")
        if code not in seen:
            seen.append(code)
    return tuple(seen)


def _rule_symbols(value: Any, where: str) -> tuple[str, ...]:
    """Strict symbol scope for one rule: no empty lists and no duplicates."""
    items = _sequence(value, where)
    if not items:
        raise ConfigError(f"{where} 不能为空")
    seen: set[str] = set()
    symbols: list[str] = []
    for index, item in enumerate(items):
        code = normalize_code(item, f"{where}[{index}]")
        if code in seen:
            raise ConfigError(f"{where} 含重复代码: {code}")
        seen.add(code)
        symbols.append(code)
    return tuple(symbols)


def _parse_window(value: Any, index: int) -> tuple[time, time]:
    text = _string(value, f"active_windows[{index}]")
    match = _WINDOW_RE.match(text)
    if not match:
        raise ConfigError(f"active_windows[{index}] 格式错误: {text!r}，应为 HH:MM:SS-HH:MM:SS")
    parts = [int(part) for part in match.groups()]
    for hour, minute, second in (parts[0:3], parts[3:6]):
        if hour > 23 or minute > 59 or second > 59:
            raise ConfigError(f"active_windows[{index}] 时间越界: {text!r}")
    start = time(parts[0], parts[1], parts[2])
    end = time(parts[3], parts[4], parts[5])
    if start >= end:
        raise ConfigError(f"active_windows[{index}] 起点必须早于终点: {text!r}")
    return start, end


def _parse_rule(value: Any, index: int, seen_ids: set[str]) -> Rule:
    where = f"rules[{index}]"
    item = _mapping(value, where)
    rule_id = _string(item.get("id"), f"{where}.id")
    if rule_id in seen_ids:
        raise ConfigError(f"规则 id 重复: {rule_id}")
    seen_ids.add(rule_id)
    rule_type = _string(item.get("type"), f"{where}.type")
    if rule_type not in RULE_TYPES:
        raise ConfigError(f"{where}.type 未知规则类型: {rule_type}")

    symbols: tuple[str, ...] | None = None
    codes: tuple[str, ...] | None = None
    if "symbols" in item and "codes" in item:
        raise ConfigError(f"{where} 不能同时指定 symbols 与 codes")
    if "symbols" in item:
        symbols = _rule_symbols(item["symbols"], f"{where}.symbols")
    elif "codes" in item:
        # ``codes`` is the legacy name for the same scope; keep it working.
        codes = _code_list(item["codes"], f"{where}.codes")

    if rule_type == "pct_change":
        direction = _string(item.get("direction"), f"{where}.direction")
        if direction not in {"up", "down"}:
            raise ConfigError(f"{where}.direction 必须是 up 或 down")
        return Rule(
            id=rule_id,
            type=rule_type,
            direction=direction,
            threshold_pct=_number(item.get("threshold_pct"), f"{where}.threshold_pct", positive=True),
            symbols=symbols,
            codes=codes,
        )
    if rule_type == "vwap_deviation":
        return Rule(
            id=rule_id,
            type=rule_type,
            threshold_pct=_number(item.get("threshold_pct"), f"{where}.threshold_pct", positive=True),
            min_amount_yuan=_number(
                item.get("min_amount_yuan"), f"{where}.min_amount_yuan", nonnegative=True
            ),
            symbols=symbols,
            codes=codes,
        )
    if rule_type == "limit_proximity":
        side = _string(item.get("side"), f"{where}.side")
        if side not in {"up", "down"}:
            raise ConfigError(f"{where}.side 必须是 up 或 down")
        return Rule(
            id=rule_id,
            type=rule_type,
            side=side,
            within_pct=_number(item.get("within_pct"), f"{where}.within_pct", positive=True),
            symbols=symbols,
            codes=codes,
        )
    if rule_type == "price_cross":
        direction = _string(item.get("direction"), f"{where}.direction")
        if direction not in {"up", "down"}:
            raise ConfigError(f"{where}.direction 必须是 up 或 down")
        return Rule(
            id=rule_id,
            type=rule_type,
            direction=direction,
            level=_number(item.get("level"), f"{where}.level", positive=True),
            symbols=symbols,
            codes=codes,
        )
    return Rule(
        id=rule_id,
        type=rule_type,
        window_seconds=_number(item.get("window_seconds"), f"{where}.window_seconds", positive=True),
        multiple=_number(item.get("multiple"), f"{where}.multiple", positive=True),
        min_window_amount_yuan=_number(
            item.get("min_window_amount_yuan"), f"{where}.min_window_amount_yuan", nonnegative=True
        ),
        symbols=symbols,
        codes=codes,
    )


def parse_rule_payload(value: Any, *, index: int = 0) -> Rule:
    """Parse one rule object with the same strict validation as the YAML file."""
    return _parse_rule(value, index, set())


def _resolve_path(value: Any, where: str, base_dir: Path) -> Path:
    target = Path(_string(value, where))
    return target if target.is_absolute() else base_dir / target


def _parse_calendar_date(value: Any, where: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ConfigError(f"{where} 必须是 YYYY-MM-DD: {value!r}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{where} 是非法日期: {value!r}") from exc


def _load_calendar_dates(path: Path, where: str) -> tuple[date, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{where} 无法读取交易日历文件 {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{where} 不是合法 JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ConfigError(f"{where} 必须是 JSON 数组")
    if not raw:
        raise ConfigError(f"{where} 不能为空数组")
    days = {
        _parse_calendar_date(item, f"{where}[{index}]")
        for index, item in enumerate(raw)
    }
    return tuple(sorted(days))


def _parse_calendar(value: Any, base_dir: Path) -> CalendarConfig:
    if value is None:
        return CalendarConfig()
    item = _mapping(value, "calendar")
    source = _string(item.get("source"), "calendar.source")
    if source not in CALENDAR_SOURCES:
        raise ConfigError(f"calendar.source 未知: {source}")
    if source == "weekdays":
        return CalendarConfig(source=source)
    if source == "file":
        if "file" not in item:
            raise ConfigError("calendar.file 必填（source=file）")
        path = _resolve_path(item["file"], "calendar.file", base_dir)
        return CalendarConfig(
            source=source,
            file=path,
            dates=_load_calendar_dates(path, "calendar.file"),
        )
    cache_path = None
    if "cache_path" in item:
        cache_path = _resolve_path(item["cache_path"], "calendar.cache_path", base_dir)
    return CalendarConfig(source=source, cache_path=cache_path)


def parse_config(raw: Any, *, base_dir: str | Path | None = None) -> WatchConfig:
    data = _mapping(raw, "配置根节点")
    base = Path(base_dir) if base_dir is not None else Path.cwd()

    watchlist_raw = _sequence(data.get("watchlist"), "watchlist")
    if len(watchlist_raw) > MAX_WATCHLIST:
        raise ConfigError(f"watchlist 最多 {MAX_WATCHLIST} 个，实际 {len(watchlist_raw)}")
    # An empty watchlist is valid: reminder plans add their own codes at runtime.
    watchlist = _code_list(watchlist_raw, "watchlist", allow_empty=True)

    polling_raw = _mapping(data.get("polling"), "polling")
    backoff = _sequence(polling_raw.get("backoff_seconds"), "polling.backoff_seconds")
    if not backoff:
        raise ConfigError("polling.backoff_seconds 不能为空")
    polling = PollingConfig(
        base_seconds=_number(polling_raw.get("base_seconds"), "polling.base_seconds", positive=True),
        fast_seconds=_number(polling_raw.get("fast_seconds"), "polling.fast_seconds", positive=True),
        hot_band_pct=_number(polling_raw.get("hot_band_pct"), "polling.hot_band_pct", nonnegative=True),
        fast_hold_seconds=_number(
            polling_raw.get("fast_hold_seconds"), "polling.fast_hold_seconds", nonnegative=True
        ),
        idle_seconds=_number(polling_raw.get("idle_seconds"), "polling.idle_seconds", positive=True),
        jitter_pct=_number(polling_raw.get("jitter_pct"), "polling.jitter_pct", nonnegative=True),
        timeout_seconds=_number(
            polling_raw.get("timeout_seconds"), "polling.timeout_seconds", positive=True
        ),
        backoff_seconds=tuple(
            _number(item, f"polling.backoff_seconds[{i}]", positive=True)
            for i, item in enumerate(backoff)
        ),
        stale_after_seconds=_number(
            polling_raw.get("stale_after_seconds"), "polling.stale_after_seconds", positive=True
        ),
        max_lag_seconds=_number(
            polling_raw.get("max_lag_seconds", 20), "polling.max_lag_seconds", positive=True
        ),
    )
    if polling.jitter_pct > 100:
        raise ConfigError("polling.jitter_pct 不能超过 100")

    alerts_raw = _mapping(data.get("alerts"), "alerts")
    alerts = AlertsConfig(
        cooldown_seconds=_number(
            alerts_raw.get("cooldown_seconds"), "alerts.cooldown_seconds", nonnegative=True
        ),
        rearm_pct=_number(alerts_raw.get("rearm_pct"), "alerts.rearm_pct", nonnegative=True),
    )

    windows_raw = _sequence(data.get("active_windows"), "active_windows")
    windows = tuple(_parse_window(item, index) for index, item in enumerate(windows_raw))

    rules_raw = _sequence(data.get("rules"), "rules")
    seen_ids: set[str] = set()
    rules = tuple(_parse_rule(item, index, seen_ids) for index, item in enumerate(rules_raw))

    watched = set(watchlist)
    for rule in rules:
        scope = rule.symbols if rule.symbols is not None else rule.codes
        if scope is None:
            continue
        missing = [code for code in scope if code not in watched]
        if missing:
            # Not an error: a symbol may be added at runtime later.
            logger.warning(
                "规则 %s 的 symbols 不在 watchlist 中: %s", rule.id, ", ".join(missing)
            )

    api_raw = _mapping(data.get("api"), "api")
    host = _string(api_raw.get("host"), "api.host")
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(f"api.host 只允许 127.0.0.1 或 localhost，实际 {host!r}")
    port = _positive_int(api_raw.get("port"), "api.port")
    if port > 65535:
        raise ConfigError("api.port 必须在 1..65535")

    limits_raw = data.get("limits")
    limits = LimitsConfig()
    if limits_raw is not None:
        item = _mapping(limits_raw, "limits")
        max_watchlist = _positive_int(
            item.get("max_watchlist", DEFAULT_MAX_WATCHLIST), "limits.max_watchlist"
        )
        if max_watchlist > MAX_WATCHLIST:
            raise ConfigError(f"limits.max_watchlist 不能超过 {MAX_WATCHLIST}")
        max_rules = _positive_int(item.get("max_rules", DEFAULT_MAX_RULES), "limits.max_rules")
        limits = LimitsConfig(max_watchlist=max_watchlist, max_rules=max_rules)
    if len(watchlist) > limits.max_watchlist:
        raise ConfigError(
            f"watchlist 有 {len(watchlist)} 个，超过 limits.max_watchlist {limits.max_watchlist}"
        )
    if len(rules) > limits.max_rules:
        raise ConfigError(
            f"rules 有 {len(rules)} 条，超过 limits.max_rules {limits.max_rules}"
        )

    runtime_file = None
    for key in ("watchlist_runtime_file", "runtime_watchlist_file"):
        if key in data:
            runtime_file = _resolve_path(data[key], key, base)
            break

    calendar = _parse_calendar(data.get("calendar"), base)
    market_watch_url = parse_market_watch_url(data.get("market_watch_url"))
    gateway_url = parse_gateway_url(data.get("gateway_url"))

    return WatchConfig(
        watchlist=watchlist,
        polling=polling,
        alerts=alerts,
        active_windows=windows,
        rules=rules,
        api=ApiConfig(host=host, port=port),
        calendar=calendar,
        limits=limits,
        watchlist_runtime_file=runtime_file,
        market_watch_url=market_watch_url,
        gateway_url=gateway_url,
    )


def load_config(path: str | Path) -> WatchConfig:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {target}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败: {exc}") from exc
    if raw is None:
        raise ConfigError("配置文件为空")
    parsed = parse_config(raw, base_dir=target.parent)
    return replace(parsed, config_path=target)
