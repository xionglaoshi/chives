"""Configuration for chives-hub.

The file format is a small YAML subset (mappings, scalars, comments) so the
package keeps a standard-library-only runtime.  Relative paths are resolved
against the directory holding the configuration file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

TEST_MODE_ENV = "CHIVES_HUB_TEST_MODE"
CN_WATCH_ENV = "CHIVES_HUB_CN_WATCH_BASE"
MARKET_WATCH_ENV = "CHIVES_HUB_MARKET_WATCH_BASE"
TENCENT_ENV = "CHIVES_HUB_TENCENT_BASE"
IFZQ_ENV = "CHIVES_HUB_IFZQ_BASE"
IFZQ_FALLBACK_ENV = "CHIVES_HUB_IFZQ_FALLBACK_BASE"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_UPSTREAM_PORTS = {"cn_watch": 8865, "market_watch": 8866}
TENCENT_HOST = "qt.gtimg.cn"
IFZQ_HOST = "web.ifzq.gtimg.cn"
IFZQ_DEFAULT_BASE = "https://web.ifzq.gtimg.cn"
IFZQ_FALLBACK_HOST = "ifzq.gtimg.cn"
IFZQ_FALLBACK_DEFAULT_BASE = "https://ifzq.gtimg.cn"

DEFAULTS: dict[str, Any] = {
    "api": {"host": "127.0.0.1", "port": 8867},
    "runtime": {
        "db_path": "../../runtime/hub/hub.db",
        "out_dir": "../../runtime/hub",
    },
    "upstreams": {
        "cn_watch": "http://127.0.0.1:8865",
        "market_watch": "http://127.0.0.1:8866",
    },
    "analyses_dir": "../../runtime/watch/analyses",
    "watchlist_file": "../../config/watch.yaml",
    "calendar_file": "../../config/trade_calendar.json",
    "portfolio": {"profile_dir": None},
    "snapshots": {"close_time": "15:05", "enabled": True},
    "polling": {"alerts_seconds": 3.0, "plans_seconds": 3.0, "timeout_seconds": 3.0},
    "limits": {
        "max_active_plans": 30,
        "max_plan_days": 30,
        "max_body_bytes": 65536,
        "max_tencent_codes": 80,
    },
}


class ConfigError(ValueError):
    """Raised when the configuration file cannot be parsed or validated."""


def _strip_comment(line: str) -> str:
    quote: Optional[str] = None
    for index, char in enumerate(line):
        if quote:
            if char == quote and (index == 0 or line[index - 1] != "\\"):
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _split_inline(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: Optional[str] = None
    current: list[str] = []
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
        elif char in "[{":
            depth += 1
            current.append(char)
        elif char in "]}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _scalar(text: str) -> Any:
    value = text.strip()
    if not value:
        return None
    if value[0] in {'"', "'"} and value[-1:] == value[0] and len(value) >= 2:
        body = value[1:-1]
        return body.replace('\\"', '"').replace("\\n", " ")
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [_scalar(item) for item in _split_inline(inner)]
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        result: dict[str, Any] = {}
        if inner:
            for item in _split_inline(inner):
                if ":" not in item:
                    raise ConfigError(f"非法内联映射项: {item!r}")
                key, raw = item.split(":", 1)
                result[key.strip()] = _scalar(raw)
        return result
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _parse_block(lines: list[tuple[int, str]], start: int, indent: int) -> tuple[Any, int]:
    """Parse one block; returns (value, next_index)."""
    items: list[Any] = []
    mapping: dict[str, Any] = {}
    index = start
    is_list: Optional[bool] = None
    while index < len(lines):
        current_indent, text = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ConfigError(f"缩进不一致: {text!r}")
        if text.startswith("- "):
            if is_list is False:
                raise ConfigError("映射中不能混入列表项")
            is_list = True
            items.append(_scalar(text[2:]))
            index += 1
            continue
        if ":" not in text:
            raise ConfigError(f"无法解析的行: {text!r}")
        if is_list is True:
            raise ConfigError("列表中不能混入映射项")
        is_list = False
        key, raw = text.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        index += 1
        if raw:
            mapping[key] = _scalar(raw)
            continue
        if index < len(lines) and lines[index][0] > current_indent:
            value, index = _parse_block(lines, index, lines[index][0])
            mapping[key] = value
        else:
            mapping[key] = {}
    return (items if is_list else mapping), index


def parse_text(text: str) -> dict[str, Any]:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("配置根必须是映射")
        return payload
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        expanded = line.replace("\t", "  ")
        indent = len(expanded) - len(expanded.lstrip(" "))
        lines.append((indent, expanded.strip()))
    if not lines:
        return {}
    if lines[0][0] != 0:
        raise ConfigError("配置第一行不能缩进")
    value, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        raise ConfigError("配置尾部存在无法解析的内容")
    if not isinstance(value, dict):
        raise ConfigError("配置根必须是映射")
    return value


def _merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


@dataclass(frozen=True)
class HubConfig:
    api_host: str
    api_port: int
    db_path: Path
    out_dir: Path
    cn_watch_base: str
    market_watch_base: str
    tencent_base: str
    ifzq_base: str
    ifzq_fallback_base: str
    analyses_dir: Path
    watchlist_file: Optional[Path]
    calendar_file: Optional[Path]
    profile_dir: Optional[Path]
    close_time: time
    snapshots_enabled: bool
    alerts_seconds: float
    plans_seconds: float
    timeout_seconds: float
    max_active_plans: int
    max_plan_days: int
    max_body_bytes: int
    max_tencent_codes: int
    config_path: Optional[Path] = None
    raw: dict[str, Any] = field(default_factory=dict)


def _path(value: Any, base: Path, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} 必须是非空路径")
    raw = value.strip()
    expanded = Path(os.path.expanduser(raw))
    return expanded if expanded.is_absolute() else (base / expanded).resolve()


def _loopback_base(raw: Any, name: str, allowed_port: Optional[int], test_mode: bool) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(f"{name} 必须是非空 URL")
    parsed = urlsplit(raw.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError(f"{name} 必须是 http(s) URL")
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise ConfigError(f"{name} 必须指向回环地址")
    if parsed.username or parsed.password:
        raise ConfigError(f"{name} 不能带用户名或密码")
    if not test_mode and allowed_port is not None and parsed.port != allowed_port:
        raise ConfigError(f"{name} 生产环境端口必须是 {allowed_port}")
    return raw.strip().rstrip("/")


def _public_quote_base(
    value: Optional[str],
    default: str,
    *,
    name: str,
    test_mode: bool,
) -> str:
    raw = value or default
    if not value:
        return raw
    parsed = urlsplit(raw)
    if parsed.username or parsed.password:
        raise ConfigError(f"{name} 不能带用户名或密码")
    if test_mode:
        if parsed.hostname not in LOOPBACK_HOSTS:
            raise ConfigError(f"测试模式{name}必须指向回环地址")
        return raw.rstrip("/")
    if parsed.scheme != "https" or parsed.hostname not in {IFZQ_HOST, IFZQ_FALLBACK_HOST}:
        raise ConfigError(
            f"{name} 生产环境只允许 https 的 {IFZQ_HOST} 或 {IFZQ_FALLBACK_HOST}"
        )
    return raw.rstrip("/")


def _parse_close_time(value: Any) -> time:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("snapshots.close_time 必须是 HH:MM")
    text = value.strip()
    try:
        hour_text, minute_text = text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError) as exc:
        raise ConfigError("snapshots.close_time 必须是 HH:MM") from exc


def load_config(path: str | Path, *, env: Optional[Mapping[str, str]] = None) -> HubConfig:
    source = os.environ if env is None else env
    config_path = Path(path).resolve()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    raw = _merge(DEFAULTS, parse_text(text))
    base = config_path.parent
    test_mode = source.get(TEST_MODE_ENV) == "1"

    api = raw.get("api") or {}
    host = api.get("host", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        raise ConfigError("api.host 只允许 127.0.0.1 或 localhost")
    try:
        port = int(api.get("port", 8867))
    except (TypeError, ValueError) as exc:
        raise ConfigError("api.port 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise ConfigError("api.port 必须在 1..65535")

    runtime = raw.get("runtime") or {}
    db_path = _path(runtime.get("db_path"), base, "runtime.db_path")
    out_dir = _path(runtime.get("out_dir"), base, "runtime.out_dir")

    upstreams = raw.get("upstreams") or {}
    cn_watch_base = _loopback_base(
        source.get(CN_WATCH_ENV) or upstreams.get("cn_watch"),
        "upstreams.cn_watch",
        ALLOWED_UPSTREAM_PORTS["cn_watch"],
        test_mode,
    )
    market_watch_base = _loopback_base(
        source.get(MARKET_WATCH_ENV) or upstreams.get("market_watch"),
        "upstreams.market_watch",
        ALLOWED_UPSTREAM_PORTS["market_watch"],
        test_mode,
    )
    tencent_raw = source.get(TENCENT_ENV) or "https://qt.gtimg.cn"
    if source.get(TENCENT_ENV):
        if not test_mode:
            raise ConfigError(f"只有 {TEST_MODE_ENV}=1 时才允许覆盖腾讯基址")
        parsed = urlsplit(tencent_raw)
        if parsed.hostname not in LOOPBACK_HOSTS:
            raise ConfigError("测试模式腾讯基址必须指向回环地址")
        tencent_base = tencent_raw.rstrip("/")
    else:
        tencent_base = tencent_raw

    ifzq_base = _public_quote_base(
        source.get(IFZQ_ENV),
        IFZQ_DEFAULT_BASE,
        name="腾讯分时基址",
        test_mode=test_mode,
    )
    ifzq_fallback_base = _public_quote_base(
        source.get(IFZQ_FALLBACK_ENV),
        IFZQ_FALLBACK_DEFAULT_BASE,
        name="腾讯分时备用基址",
        test_mode=test_mode,
    )

    analyses_dir = _path(raw.get("analyses_dir"), base, "analyses_dir")
    watchlist_raw = raw.get("watchlist_file")
    watchlist_file = (
        _path(watchlist_raw, base, "watchlist_file") if watchlist_raw else None
    )
    calendar_raw = raw.get("calendar_file")
    calendar_file = _path(calendar_raw, base, "calendar_file") if calendar_raw else None

    portfolio = raw.get("portfolio") or {}
    profile_raw = portfolio.get("profile_dir")
    profile_dir = _path(profile_raw, base, "portfolio.profile_dir") if profile_raw else None

    snapshots = raw.get("snapshots") or {}
    close_time = _parse_close_time(snapshots.get("close_time", "15:05"))
    snapshots_enabled = bool(snapshots.get("enabled", True))

    polling = raw.get("polling") or {}
    try:
        alerts_seconds = float(polling.get("alerts_seconds", 3.0))
        plans_seconds = float(polling.get("plans_seconds", 3.0))
        timeout_seconds = float(polling.get("timeout_seconds", 3.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError("polling 间隔必须是数字") from exc
    if alerts_seconds < 1.0 or plans_seconds < 1.0:
        raise ConfigError("轮询间隔不得小于 1 秒")
    if not 0.5 <= timeout_seconds <= 10.0:
        raise ConfigError("polling.timeout_seconds 必须在 0.5..10")

    limits = raw.get("limits") or {}
    try:
        max_active_plans = int(limits.get("max_active_plans", 30))
        max_plan_days = int(limits.get("max_plan_days", 30))
        max_body_bytes = int(limits.get("max_body_bytes", 65536))
        max_tencent_codes = int(limits.get("max_tencent_codes", 80))
    except (TypeError, ValueError) as exc:
        raise ConfigError("limits 必须是整数") from exc
    if max_active_plans < 1:
        raise ConfigError("limits.max_active_plans 必须为正")
    if not 1 <= max_plan_days <= 30:
        raise ConfigError("limits.max_plan_days 必须在 1..30")
    if max_body_bytes != 65536:
        raise ConfigError("limits.max_body_bytes 固定为 65536")
    if not 1 <= max_tencent_codes <= 80:
        raise ConfigError("limits.max_tencent_codes 必须在 1..80")

    return HubConfig(
        api_host=host,
        api_port=port,
        db_path=db_path,
        out_dir=out_dir,
        cn_watch_base=cn_watch_base,
        market_watch_base=market_watch_base,
        tencent_base=tencent_base,
        ifzq_base=ifzq_base,
        ifzq_fallback_base=ifzq_fallback_base,
        analyses_dir=analyses_dir,
        watchlist_file=watchlist_file,
        calendar_file=calendar_file,
        profile_dir=profile_dir,
        close_time=close_time,
        snapshots_enabled=snapshots_enabled,
        alerts_seconds=alerts_seconds,
        plans_seconds=plans_seconds,
        timeout_seconds=timeout_seconds,
        max_active_plans=max_active_plans,
        max_plan_days=max_plan_days,
        max_body_bytes=max_body_bytes,
        max_tencent_codes=max_tencent_codes,
        config_path=config_path,
        raw=raw,
    )
