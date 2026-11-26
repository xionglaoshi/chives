"""Strict configuration loading and validation for market-watch."""

from __future__ import annotations

import logging
import math
import re
from urllib.parse import urlparse
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from . import yamlmini

logger = logging.getLogger("chives_compass.config")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6")
LEVELS = {"L1", "L2", "L3"}
CALENDAR_SOURCES = {"file", "weekdays"}
MAX_WATCHLIST = 80
STALE_KEYS = ("index", "breadth", "limit_pool", "industry")
SOURCE_KEYS = ("gateway",)

DEFAULT_STALE = {
    "index": 15.0,
    "breadth": 90.0,
    "limit_pool": 150.0,
    "industry": 90.0,
}
DEFAULT_RATE = {"gateway": 600}

RULE_NAMES = {
    "R1": "指数放量下跌",
    "R2": "宽度恶化/背离",
    "R3": "板块排名跃升",
    "R4": "板块涨停骤增",
    "R5": "板块相对强弱穿越",
    "R6": "个股-板块背离",
}

RULE_DEFAULTS: dict[str, dict[str, Any]] = {
    "R1": {
        "enabled": True,
        "level": "L2",
        "confirm": 2,
        "cooldown_minutes": 60,
        "params": {"change_pct_max": -1.0, "volume_ratio_min": 1.5},
    },
    "R2": {
        "enabled": True,
        "level": "L2",
        "confirm": 3,
        "cooldown_minutes": 60,
        "params": {
            "up_ratio_max": 0.30,
            "index_change_pct_min": -0.3,
            "drop_window_minutes": 30,
            "up_ratio_drop_min": 0.15,
        },
    },
    "R3": {
        "enabled": True,
        "level": "L2",
        "confirm": 2,
        "cooldown_minutes": 30,
        "params": {
            "rank_max": 5,
            "rank_before_min": 15,
            "rank_improvement_min": 10,
            "change_pct_min": 1.5,
            "up_ratio_min": 0.6,
            "min_members": 10,
            "min_amount_yuan": 500_000_000.0,
            "window_minutes": 30,
        },
    },
    "R4": {
        "enabled": True,
        "level": "L2",
        "confirm": 2,
        "cooldown_minutes": 30,
        "params": {
            "zt_increase_min": 3,
            "zt_min": 5,
            "up_ratio_min": 0.5,
            "min_members": 10,
            "min_amount_yuan": 500_000_000.0,
            "window_minutes": 30,
        },
    },
    "R5": {
        "enabled": True,
        "level": "L1",
        "confirm": 2,
        "cooldown_minutes": 60,
        "params": {"buffer_pct": 0.3},
    },
    "R6": {
        "enabled": True,
        "level": "L2",
        "confirm": 2,
        "cooldown_minutes": 30,
        "params": {
            "divergence_pct_max": -3.0,
            "volume_ratio_min": 2.0,
            "window_minutes": 30,
            "min_members": 10,
        },
    },
}

# Parameter validation table: name -> (kind, minimum, maximum, inclusive_min)
_PARAM_RULES: dict[str, dict[str, tuple[str, float, float]]] = {
    "R1": {
        "change_pct_max": ("number", -100.0, 100.0),
        "volume_ratio_min": ("number", 0.0, 1000.0),
    },
    "R2": {
        "up_ratio_max": ("ratio", 0.0, 1.0),
        "index_change_pct_min": ("number", -100.0, 100.0),
        "drop_window_minutes": ("int", 1, 240),
        "up_ratio_drop_min": ("ratio", 0.0, 1.0),
    },
    "R3": {
        "rank_max": ("int", 1, 31),
        "rank_before_min": ("int", 1, 31),
        "rank_improvement_min": ("int", 0, 31),
        "change_pct_min": ("number", -100.0, 100.0),
        "up_ratio_min": ("ratio", 0.0, 1.0),
        "min_members": ("int", 0, 10000),
        "min_amount_yuan": ("number", 0.0, 1e15),
        "window_minutes": ("int", 1, 240),
    },
    "R4": {
        "zt_increase_min": ("int", 0, 1000),
        "zt_min": ("int", 0, 1000),
        "up_ratio_min": ("ratio", 0.0, 1.0),
        "min_members": ("int", 0, 10000),
        "min_amount_yuan": ("number", 0.0, 1e15),
        "window_minutes": ("int", 1, 240),
    },
    "R5": {"buffer_pct": ("number", 0.0, 100.0)},
    "R6": {
        "divergence_pct_max": ("number", -100.0, 100.0),
        "volume_ratio_min": ("number", 0.0, 1000.0),
        "window_minutes": ("int", 1, 240),
        "min_members": ("int", 0, 10000),
    },
}


class ConfigError(Exception):
    """Raised when the configuration file is missing, malformed or invalid."""


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8866


@dataclass(frozen=True)
class RuntimeConfig:
    db_path: Path = Path("runtime/market/market.db")
    out_dir: Path = Path("runtime/market")


@dataclass(frozen=True)
class PollingConfig:
    index_seconds: float = 3.0
    breadth_seconds: float = 20.0
    limit_pool_seconds: float = 40.0
    members_seconds: float = 600.0
    member_min_interval_seconds: float = 0.5
    history_seconds: float = 300.0
    movers_seconds: float = 30.0
    flows_seconds: float = 30.0
    daily_spark_seconds: float = 300.0
    timeout_seconds: float = 5.0
    stale_after: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STALE))


@dataclass(frozen=True)
class LimitsConfig:
    max_per_minute: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RATE))
    max_concurrency: int = 2
    alert_max_per_hour: int = 10


@dataclass(frozen=True)
class SuppressionConfig:
    enabled: bool = True
    open_minutes: int = 15
    close_minutes: int = 5


@dataclass(frozen=True)
class SectorDef:
    code: str
    name: str


@dataclass(frozen=True)
class GatewayConfig:
    url: str = "http://127.0.0.1:8868"


@dataclass(frozen=True)
class RuleConfig:
    id: str
    name: str
    enabled: bool
    level: str
    confirm: int
    cooldown_minutes: float
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "params": dict(self.params),
            "confirm": self.confirm,
            "cooldown_minutes": self.cooldown_minutes,
            "level": self.level,
        }


@dataclass(frozen=True)
class MarketConfig:
    api: ApiConfig = field(default_factory=ApiConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    rules: tuple[RuleConfig, ...] = ()
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    calendar_source: str = "weekdays"
    calendar_file: Path | None = None
    watchlist_file: Path | None = None
    config_path: Path | None = None

    def rule(self, rule_id: str) -> RuleConfig | None:
        for item in self.rules:
            if item.id == rule_id:
                return item
        return None


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} 必须是映射")
    return value


def _sequence(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{where} 必须是列表")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} 必须是非空字符串")
    return value.strip()


def _number(value: Any, where: str, *, positive: bool = False, nonnegative: bool = False) -> float:
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


def _resolve_path(value: Any, where: str, base_dir: Path) -> Path:
    target = Path(_string(value, where))
    return target if target.is_absolute() else base_dir / target


def _parse_polling(raw: Any) -> PollingConfig:
    item = _mapping(raw, "polling")
    stale_raw = item.get("stale_after_seconds")
    stale = dict(DEFAULT_STALE)
    if stale_raw is not None:
        mapping = _mapping(stale_raw, "polling.stale_after_seconds")
        for key, value in mapping.items():
            if key not in STALE_KEYS:
                raise ConfigError(f"polling.stale_after_seconds 未知键: {key}")
            stale[key] = _number(value, f"polling.stale_after_seconds.{key}", positive=True)
    timeout = _number(item.get("timeout_seconds", 5), "polling.timeout_seconds", positive=True)
    if timeout > 5:
        raise ConfigError("polling.timeout_seconds 不能超过 5 秒（任务硬约束）")
    members_seconds = _number(
        item.get("members_seconds", 600), "polling.members_seconds", positive=True
    )
    if members_seconds < 600:
        raise ConfigError("polling.members_seconds 不能小于 600（成分缓存 TTL ≥ 10 分钟）")
    member_interval = _number(
        item.get("member_min_interval_seconds", 0.5),
        "polling.member_min_interval_seconds",
        positive=True,
    )
    if member_interval < 0.5:
        raise ConfigError("polling.member_min_interval_seconds 不能小于 0.5")
    return PollingConfig(
        index_seconds=_number(item.get("index_seconds", 3), "polling.index_seconds", positive=True),
        breadth_seconds=_number(item.get("breadth_seconds", 20), "polling.breadth_seconds", positive=True),
        limit_pool_seconds=_number(
            item.get("limit_pool_seconds", 40), "polling.limit_pool_seconds", positive=True
        ),
        members_seconds=members_seconds,
        member_min_interval_seconds=member_interval,
        history_seconds=_number(
            item.get("history_seconds", 300), "polling.history_seconds", positive=True
        ),
        movers_seconds=_number(
            item.get("movers_seconds", 30), "polling.movers_seconds", positive=True
        ),
        flows_seconds=_number(
            item.get("flows_seconds", 30), "polling.flows_seconds", positive=True
        ),
        daily_spark_seconds=_number(
            item.get("daily_spark_seconds", 300), "polling.daily_spark_seconds", positive=True
        ),
        timeout_seconds=timeout,
        stale_after=stale,
    )


def _parse_limits(raw: Any) -> LimitsConfig:
    if raw is None:
        return LimitsConfig()
    item = _mapping(raw, "limits")
    rates = dict(DEFAULT_RATE)
    rates_raw = item.get("max_per_minute")
    if rates_raw is not None:
        mapping = _mapping(rates_raw, "limits.max_per_minute")
        for key, value in mapping.items():
            if key not in SOURCE_KEYS:
                raise ConfigError(f"limits.max_per_minute 未知源: {key}")
            rates[key] = _positive_int(value, f"limits.max_per_minute.{key}")
    concurrency = _positive_int(item.get("max_concurrency", 2), "limits.max_concurrency")
    if concurrency > 2:
        raise ConfigError("limits.max_concurrency 不能超过 2（契约要求每源最多 2 个并发）")
    return LimitsConfig(
        max_per_minute=rates,
        max_concurrency=concurrency,
        alert_max_per_hour=_positive_int(
            item.get("alert_max_per_hour", 10), "limits.alert_max_per_hour"
        ),
    )


def _parse_suppression(raw: Any) -> SuppressionConfig:
    if raw is None:
        return SuppressionConfig()
    item = _mapping(raw, "suppression")
    enabled = item.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("suppression.enabled 必须是布尔值")
    open_minutes = _positive_int(item.get("open_minutes", 15), "suppression.open_minutes")
    close_minutes = _positive_int(item.get("close_minutes", 5), "suppression.close_minutes")
    if open_minutes > 120 or close_minutes > 30:
        raise ConfigError("suppression 窗口过大")
    return SuppressionConfig(enabled=enabled, open_minutes=open_minutes, close_minutes=close_minutes)


def _parse_gateway(raw: Any) -> GatewayConfig:
    if raw is None:
        return GatewayConfig()
    item = _mapping(raw, "gateway")
    unknown = set(item) - {"url"}
    if unknown:
        raise ConfigError(f"gateway 含未知键: {', '.join(sorted(unknown))}")
    url = _string(item.get("url", "http://127.0.0.1:8868"), "gateway.url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise ConfigError("gateway.url 必须是回环 http(s) 地址")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("gateway.url 不允许包含凭据")
    return GatewayConfig(url=url.rstrip("/"))


def _parse_rule(rule_id: str, raw: Any) -> RuleConfig:
    defaults = RULE_DEFAULTS[rule_id]
    item = {} if raw is None else _mapping(raw, f"rules.{rule_id}")
    allowed = {"enabled", "level", "confirm", "cooldown_minutes", "params"}
    unknown = set(item) - allowed
    if unknown:
        raise ConfigError(f"rules.{rule_id} 含未知键: {', '.join(sorted(unknown))}")
    enabled = item.get("enabled", defaults["enabled"])
    if not isinstance(enabled, bool):
        raise ConfigError(f"rules.{rule_id}.enabled 必须是布尔值")
    level = _string(item.get("level", defaults["level"]), f"rules.{rule_id}.level")
    if level not in LEVELS:
        raise ConfigError(f"rules.{rule_id}.level 必须是 L1/L2/L3")
    confirm = _positive_int(item.get("confirm", defaults["confirm"]), f"rules.{rule_id}.confirm")
    if confirm > 20:
        raise ConfigError(f"rules.{rule_id}.confirm 不能超过 20")
    cooldown = _number(
        item.get("cooldown_minutes", defaults["cooldown_minutes"]),
        f"rules.{rule_id}.cooldown_minutes",
        nonnegative=True,
    )
    if cooldown > 1440:
        raise ConfigError(f"rules.{rule_id}.cooldown_minutes 不能超过 1440")
    params = dict(defaults["params"])
    params_raw = item.get("params")
    if params_raw is not None:
        mapping = _mapping(params_raw, f"rules.{rule_id}.params")
        for key, value in mapping.items():
            if key not in params:
                raise ConfigError(f"rules.{rule_id}.params 含未知参数: {key}")
            kind, minimum, maximum = _PARAM_RULES[rule_id][key]
            if kind == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigError(f"rules.{rule_id}.params.{key} 必须是整数")
                number = value
            else:
                number = _number(value, f"rules.{rule_id}.params.{key}")
            if number < minimum or number > maximum:
                raise ConfigError(
                    f"rules.{rule_id}.params.{key} 超出范围 [{minimum}, {maximum}]: {number}"
                )
            params[key] = number
    return RuleConfig(
        id=rule_id,
        name=RULE_NAMES[rule_id],
        enabled=enabled,
        level=level,
        confirm=confirm,
        cooldown_minutes=cooldown,
        params=params,
    )


def _parse_rules(raw: Any) -> tuple[RuleConfig, ...]:
    if raw is None:
        return tuple(_parse_rule(rule_id, None) for rule_id in RULE_IDS)
    mapping = _mapping(raw, "rules")
    unknown = set(mapping) - set(RULE_IDS)
    if unknown:
        raise ConfigError(f"rules 含未知规则: {', '.join(sorted(unknown))}")
    return tuple(_parse_rule(rule_id, mapping.get(rule_id)) for rule_id in RULE_IDS)


def _parse_calendar(raw: Any, base_dir: Path) -> tuple[str, Path | None]:
    if raw is None:
        return "weekdays", None
    item = _mapping(raw, "calendar")
    source = _string(item.get("source"), "calendar.source")
    if source not in CALENDAR_SOURCES:
        raise ConfigError(f"calendar.source 未知: {source}")
    if source == "weekdays":
        return source, None
    if "file" not in item:
        raise ConfigError("calendar.file 必填（source=file）")
    return source, _resolve_path(item["file"], "calendar.file", base_dir)


def parse_config(raw: Any, *, base_dir: str | Path | None = None) -> MarketConfig:
    data = _mapping(raw, "配置根节点")
    base = Path(base_dir) if base_dir is not None else Path.cwd()

    api_raw = data.get("api", {})
    api_map = _mapping(api_raw, "api")
    host = _string(api_map.get("host", "127.0.0.1"), "api.host")
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(f"api.host 只允许 127.0.0.1 或 localhost，实际 {host!r}")
    port = _positive_int(api_map.get("port", 8866), "api.port")
    if port > 65535:
        raise ConfigError("api.port 必须在 1..65535")

    runtime_raw = data.get("runtime", {})
    runtime_map = _mapping(runtime_raw, "runtime")
    runtime = RuntimeConfig(
        db_path=_resolve_path(
            runtime_map.get("db_path", "../../runtime/market/market.db"),
            "runtime.db_path",
            base,
        ),
        out_dir=_resolve_path(
            runtime_map.get("out_dir", "../../runtime/market"), "runtime.out_dir", base
        ),
    )

    calendar_source, calendar_file = _parse_calendar(data.get("calendar"), base)
    watchlist_file = None
    if "watchlist_file" in data:
        watchlist_file = _resolve_path(data["watchlist_file"], "watchlist_file", base)

    return MarketConfig(
        api=ApiConfig(host=host, port=port),
        runtime=runtime,
        polling=_parse_polling(data.get("polling", {})),
        limits=_parse_limits(data.get("limits")),
        suppression=_parse_suppression(data.get("suppression")),
        rules=_parse_rules(data.get("rules")),
        gateway=_parse_gateway(data.get("gateway")),
        calendar_source=calendar_source,
        calendar_file=calendar_file,
        watchlist_file=watchlist_file,
    )


def load_config(path: str | Path) -> MarketConfig:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {target}: {exc}") from exc
    try:
        raw = yamlmini.loads(text)
    except yamlmini.YamlError as exc:
        raise ConfigError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("配置文件为空或根节点不是映射")
    parsed = parse_config(raw, base_dir=target.parent)
    return replace(parsed, config_path=target)


def load_watchlist(path: str | Path | None, *, limit: int = MAX_WATCHLIST) -> tuple[str, ...]:
    """Read the ``watchlist`` key of chives-radar's ``config/watch.yaml`` (read-only)."""
    if path is None:
        return ()
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("无法读取自选股文件 %s: %s", target, exc)
        return ()
    try:
        raw = yamlmini.loads(text)
    except yamlmini.YamlError as exc:
        logger.warning("自选股文件 YAML 解析失败 %s: %s", target, exc)
        return ()
    items = raw.get("watchlist") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return ()
    codes: list[str] = []
    for item in items:
        code = _normalize_stock(item)
        if code and code not in codes:
            codes.append(code)
    if len(codes) > limit:
        logger.warning("自选股超过 %d 个，只取前 %d 个", limit, limit)
        codes = codes[:limit]
    return tuple(codes)


def _normalize_stock(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        raw = f"{value:06d}"
    elif isinstance(value, str):
        raw = value.strip().upper()
    else:
        return None
    suffix = ""
    digits = raw
    if "." in raw:
        digits, suffix = raw.rsplit(".", 1)
        if suffix not in {"SH", "SZ"}:
            return None
    if len(digits) != 6 or not digits.isdigit():
        return None
    if not suffix:
        suffix = "SH" if digits[0] in {"5", "6", "9"} else "SZ"
    return f"{digits}.{suffix}"
