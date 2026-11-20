"""Strict parsing and validation of the proxy YAML configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_MAX_ENTRIES = 500
DEFAULT_TTL_SECONDS = 60.0
DEFAULT_MAX_CALLS_PER_MINUTE = 60
MAX_HINT_LENGTH = 300

CHECK_BARS_WITHIN_REQUESTED_DATES = "bars_within_requested_dates"
CHECK_NON_EMPTY_RESULT = "non_empty_result"
KNOWN_CHECK_TYPES = frozenset({CHECK_BARS_WITHIN_REQUESTED_DATES, CHECK_NON_EMPTY_RESULT})
WILDCARD_TOOL = "*"

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """The configuration file is invalid."""


class EmptyAllowlistError(ConfigError):
    """`allow` is missing or empty; there is nothing safe to expose."""


@dataclass(frozen=True)
class UpstreamConfig:
    command: str
    args: tuple[str, ...] = ()
    cwd: str | None = None
    inherit_env: bool = False
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CacheConfig:
    max_entries: int
    ttl_default: float
    ttl_by_tool: Mapping[str, float] = field(default_factory=dict)

    def ttl_for(self, upstream_tool: str) -> float:
        return self.ttl_by_tool.get(upstream_tool, self.ttl_default)


@dataclass(frozen=True)
class RateLimitConfig:
    max_calls_per_minute: int


@dataclass(frozen=True)
class CheckConfig:
    tool: str
    type: str
    start_arg: str | None = None
    end_arg: str | None = None
    date_field: str | None = None
    hint: str | None = None
    allow_empty: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProxyConfig:
    name: str
    upstream: UpstreamConfig
    allow: tuple[str, ...]
    rename_prefix: str
    cache: CacheConfig
    rate_limit: RateLimitConfig
    checks: tuple[CheckConfig, ...] = ()
    annotations: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def checks_for(self, upstream_tool: str) -> tuple[CheckConfig, ...]:
        return tuple(
            check
            for check in self.checks
            if check.tool in (upstream_tool, WILDCARD_TOOL)
        )

    def annotations_for(self, upstream_tool: str) -> Mapping[str, Any]:
        return self.annotations.get(upstream_tool, {})


def expand_env(value: str, environ: Mapping[str, str], field_name: str) -> str:
    """Expand every ${VAR} in *value*, failing with a message that names the variable."""

    def replace(match: re.Match[str]) -> str:
        var = match.group(1)
        if var not in environ:
            raise ConfigError(
                f"{field_name} references environment variable '{var}', but it is not set"
            )
        return environ[var]

    return _ENV_REF.sub(replace, value)


def _mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{what} must be a mapping")
    return value


def _string(value: Any, what: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{what} must be a string")
    if not allow_empty and not value.strip():
        raise ConfigError(f"{what} must not be empty")
    return value


def _integer(value: Any, what: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{what} must be an integer")
    if value < minimum:
        raise ConfigError(f"{what} must be >= {minimum}")
    return value


def _number(value: Any, what: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{what} must be a number")
    number = float(value)
    if number < minimum:
        raise ConfigError(f"{what} must be >= {minimum:g}")
    return number


def _parse_upstream(raw: Any, environ: Mapping[str, str]) -> UpstreamConfig:
    data = _mapping(raw, "upstream")
    command = _string(data.get("command"), "upstream.command")

    args_raw = data.get("args", [])
    if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
        raise ConfigError("upstream.args must be a list of strings")

    cwd_raw = data.get("cwd")
    cwd = None if cwd_raw is None else _string(cwd_raw, "upstream.cwd")

    inherit_raw = data.get("inherit_env", False)
    if not isinstance(inherit_raw, bool):
        raise ConfigError("upstream.inherit_env must be a boolean")

    env_raw = data.get("env", {})
    env_data = _mapping(env_raw, "upstream.env") if env_raw is not None else {}
    env: dict[str, str] = {}
    for key, value in env_data.items():
        if not isinstance(key, str) or not key:
            raise ConfigError("upstream.env keys must be non-empty strings")
        if not isinstance(value, str):
            raise ConfigError(f"upstream.env.{key} must be a string")
        env[key] = expand_env(value, environ, f"upstream.env.{key}")

    return UpstreamConfig(
        command=command,
        args=tuple(args_raw),
        cwd=cwd,
        inherit_env=inherit_raw,
        env=env,
    )


def _parse_allow(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise EmptyAllowlistError("allow must be a non-empty list of upstream tool names")
    names: list[str] = []
    for index, item in enumerate(raw):
        name = _string(item, f"allow[{index}]")
        if name not in names:
            names.append(name)
    return tuple(names)


def _parse_cache(raw: Any) -> CacheConfig:
    data = _mapping(raw, "cache") if raw is not None else {}
    max_entries = _integer(data.get("max_entries", DEFAULT_MAX_ENTRIES), "cache.max_entries", minimum=1)

    ttl_raw = data.get("ttl_seconds", {})
    ttl_data = _mapping(ttl_raw, "cache.ttl_seconds")
    if "default" not in ttl_data:
        ttl_default = DEFAULT_TTL_SECONDS
    else:
        ttl_default = _number(ttl_data["default"], "cache.ttl_seconds.default", minimum=0)

    ttl_by_tool: dict[str, float] = {}
    for tool, ttl in ttl_data.items():
        if tool == "default":
            continue
        if not isinstance(tool, str) or not tool:
            raise ConfigError("cache.ttl_seconds keys must be tool names")
        ttl_by_tool[tool] = _number(ttl, f"cache.ttl_seconds.{tool}", minimum=0)

    return CacheConfig(max_entries=max_entries, ttl_default=ttl_default, ttl_by_tool=ttl_by_tool)


def _parse_rate_limit(raw: Any) -> RateLimitConfig:
    data = _mapping(raw, "rate_limit") if raw is not None else {}
    max_calls = _integer(
        data.get("max_calls_per_minute", DEFAULT_MAX_CALLS_PER_MINUTE),
        "rate_limit.max_calls_per_minute",
        minimum=1,
    )
    return RateLimitConfig(max_calls_per_minute=max_calls)


_REQUIRED_FIELDS_BY_TYPE = {
    CHECK_BARS_WITHIN_REQUESTED_DATES: ("start_arg", "end_arg", "date_field"),
    CHECK_NON_EMPTY_RESULT: (),
}


def _parse_allow_empty(
    raw: Any, index: int, check_type: str, tool: str, allow: tuple[str, ...]
) -> tuple[str, ...]:
    if check_type != CHECK_NON_EMPTY_RESULT:
        raise ConfigError(
            f"checks[{index}].allow_empty is only supported by "
            f"'{CHECK_NON_EMPTY_RESULT}' checks"
        )
    if tool != WILDCARD_TOOL:
        raise ConfigError(
            f"checks[{index}].allow_empty is only valid when tool is '{WILDCARD_TOOL}'"
        )
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            f"checks[{index}].allow_empty must be a non-empty list of tool names"
        )
    names: list[str] = []
    for position, item in enumerate(raw):
        name = _string(item, f"checks[{index}].allow_empty[{position}]")
        if name not in allow:
            raise ConfigError(
                f"checks[{index}].allow_empty tool '{name}' is not in allow"
            )
        if name not in names:
            names.append(name)
    return tuple(names)


def _parse_checks(raw: Any, allow: tuple[str, ...]) -> tuple[CheckConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("checks must be a list")
    checks: list[CheckConfig] = []
    for index, item in enumerate(raw):
        data = _mapping(item, f"checks[{index}]")
        tool = _string(data.get("tool"), f"checks[{index}].tool")
        check_type = _string(data.get("type"), f"checks[{index}].type")
        if check_type not in KNOWN_CHECK_TYPES:
            known = ", ".join(sorted(KNOWN_CHECK_TYPES))
            raise ConfigError(
                f"checks[{index}].type '{check_type}' is not supported "
                f"(known types: {known})"
            )
        if tool != WILDCARD_TOOL and tool not in allow:
            raise ConfigError(f"checks[{index}].tool '{tool}' is not in allow")
        if tool == WILDCARD_TOOL and check_type != CHECK_NON_EMPTY_RESULT:
            raise ConfigError(
                f"checks[{index}].tool '{WILDCARD_TOOL}' is only supported by "
                f"'{CHECK_NON_EMPTY_RESULT}' checks"
            )
        for name in _REQUIRED_FIELDS_BY_TYPE[check_type]:
            if name not in data:
                raise ConfigError(f"checks[{index}].{name} is required")
        hint: str | None = None
        if "hint" in data:
            hint = _string(data["hint"], f"checks[{index}].hint")
            if len(hint) > MAX_HINT_LENGTH:
                raise ConfigError(
                    f"checks[{index}].hint must be at most {MAX_HINT_LENGTH} characters"
                )
        allow_empty: tuple[str, ...] = ()
        if "allow_empty" in data:
            allow_empty = _parse_allow_empty(
                data["allow_empty"], index, check_type, tool, allow
            )
        checks.append(
            CheckConfig(
                tool=tool,
                type=check_type,
                start_arg=(
                    _string(data["start_arg"], f"checks[{index}].start_arg")
                    if "start_arg" in data
                    else None
                ),
                end_arg=(
                    _string(data["end_arg"], f"checks[{index}].end_arg")
                    if "end_arg" in data
                    else None
                ),
                date_field=(
                    _string(data["date_field"], f"checks[{index}].date_field")
                    if "date_field" in data
                    else None
                ),
                hint=hint,
                allow_empty=allow_empty,
            )
        )
    return tuple(checks)


def _parse_annotations(raw: Any, allow: tuple[str, ...]) -> Mapping[str, Mapping[str, Any]]:
    if raw is None:
        return {}
    data = _mapping(raw, "annotations")
    annotations: dict[str, Mapping[str, Any]] = {}
    for tool, value in data.items():
        if not isinstance(tool, str) or not tool:
            raise ConfigError("annotations keys must be non-empty tool names")
        if tool not in allow:
            raise ConfigError(f"annotations.{tool} is not in allow")
        annotations[tool] = _mapping(value, f"annotations.{tool}")
    return annotations


def parse_config(data: Any, environ: Mapping[str, str] | None = None) -> ProxyConfig:
    environ = os.environ if environ is None else environ
    root = _mapping(data, "configuration")

    name = _string(root.get("name"), "name")
    if "upstream" not in root:
        raise ConfigError("upstream is required")
    upstream = _parse_upstream(root["upstream"], environ)
    allow = _parse_allow(root.get("allow"))

    prefix_raw = root.get("rename_prefix", "")
    prefix = _string(prefix_raw, "rename_prefix", allow_empty=True)

    cache = _parse_cache(root.get("cache"))
    rate_limit = _parse_rate_limit(root.get("rate_limit"))
    checks = _parse_checks(root.get("checks"), allow)
    annotations = _parse_annotations(root.get("annotations"), allow)

    return ProxyConfig(
        name=name,
        upstream=upstream,
        allow=allow,
        rename_prefix=prefix,
        cache=cache,
        rate_limit=rate_limit,
        checks=checks,
        annotations=annotations,
    )


def load_config(path: str | Path, environ: Mapping[str, str] | None = None) -> ProxyConfig:
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {config_path}: {exc.strerror or exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        raise ConfigError(f"invalid YAML in {config_path}: {detail}") from exc

    if data is None:
        raise ConfigError(f"config file {config_path} is empty")
    return parse_config(data, environ)
