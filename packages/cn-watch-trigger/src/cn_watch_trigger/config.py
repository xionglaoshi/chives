"""Strict YAML configuration loading and validation for cn-watch-trigger."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PLACEHOLDER = "{alert_json}"
RUNNER_PLACEHOLDER = "{prompt}"


class ConfigError(Exception):
    """Raised when the configuration file is missing, malformed or invalid."""


@dataclass(frozen=True)
class Trigger:
    rule_ids: tuple[str, ...]
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Limits:
    max_runs_per_day: int
    cooldown_seconds: float
    max_alert_age_seconds: float
    run_timeout_seconds: float
    max_queue: int


@dataclass(frozen=True)
class RunnerConfig:
    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path = Path(".")


@dataclass(frozen=True)
class TriggerConfig:
    engine: str
    state_dir: Path
    poll_seconds: float
    prompt_template: Path
    template_text: str
    triggers: tuple[Trigger, ...]
    limits: Limits
    runner: RunnerConfig
    config_path: Path
    base_dir: Path


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


def _string_list(value: Any, where: str) -> tuple[str, ...]:
    items = _sequence(value, where)
    if not items:
        raise ConfigError(f"{where} 不能为空")
    result: list[str] = []
    for index, item in enumerate(items):
        text = _string(item, f"{where}[{index}]")
        if text not in result:
            result.append(text)
    return tuple(result)


def _resolve_path(value: Any, where: str, base_dir: Path) -> Path:
    raw = _string(value, where)
    target = Path(raw)
    if not target.is_absolute():
        target = base_dir / target
    return target.resolve()


def _parse_engine(value: Any) -> str:
    raw = _string(value, "engine")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ConfigError(f"engine URL 非法: {raw!r}") from exc
    if parts.scheme not in {"http", "https"}:
        raise ConfigError("engine 必须是 http(s) URL")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(f"engine 主机必须是回环地址（127.0.0.1 / localhost / [::1]）: {host or raw!r}")
    if parts.username or parts.password:
        raise ConfigError("engine 不得包含用户名或密码")
    try:
        port = parts.port
    except ValueError as exc:
        raise ConfigError(f"engine 端口非法: {raw!r}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"engine 端口越界: {port}")
    if parts.query or parts.fragment:
        raise ConfigError("engine 不得包含查询参数或片段")
    return raw.rstrip("/")


def _parse_triggers(value: Any) -> tuple[Trigger, ...]:
    items = _sequence(value, "triggers")
    if not items:
        raise ConfigError("triggers 不能为空")
    result: list[Trigger] = []
    for index, item in enumerate(items):
        where = f"triggers[{index}]"
        entry = _mapping(item, where)
        rule_ids = _string_list(entry.get("rule_ids"), f"{where}.rule_ids")
        raw_codes = _string_list(entry.get("codes"), f"{where}.codes")
        codes = tuple(code if code == "*" else code.upper() for code in raw_codes)
        result.append(Trigger(rule_ids=rule_ids, codes=codes))
    return tuple(result)


def _parse_limits(value: Any) -> Limits:
    entry = _mapping(value, "limits")
    return Limits(
        max_runs_per_day=_positive_int(entry.get("max_runs_per_day"), "limits.max_runs_per_day"),
        cooldown_seconds=_number(
            entry.get("cooldown_seconds"), "limits.cooldown_seconds", nonnegative=True
        ),
        max_alert_age_seconds=_number(
            entry.get("max_alert_age_seconds"), "limits.max_alert_age_seconds", positive=True
        ),
        run_timeout_seconds=_number(
            entry.get("run_timeout_seconds"), "limits.run_timeout_seconds", positive=True
        ),
        max_queue=_positive_int(entry.get("max_queue"), "limits.max_queue"),
    )


def _parse_runner(value: Any, base_dir: Path) -> RunnerConfig:
    entry = _mapping(value, "runner")
    raw_command = _sequence(entry.get("command"), "runner.command")
    if not raw_command:
        raise ConfigError("runner.command 不能为空")
    command = tuple(_string(part, f"runner.command[{index}]") for index, part in enumerate(raw_command))
    if command.count(RUNNER_PLACEHOLDER) != 1:
        raise ConfigError(f"runner.command 必须恰好有一个元素等于 {RUNNER_PLACEHOLDER}")

    raw_env = entry.get("env", {})
    env_entry = _mapping(raw_env, "runner.env")
    env: dict[str, str] = {}
    for key, item in env_entry.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError("runner.env 的键必须是非空字符串")
        if not isinstance(item, str):
            raise ConfigError(f"runner.env.{key} 必须是字符串")
        env[key] = item

    raw_cwd = entry.get("cwd", ".")
    cwd = _resolve_path(raw_cwd, "runner.cwd", base_dir)
    if not cwd.is_dir():
        raise ConfigError(f"runner.cwd 不存在或不是目录: {cwd}")
    return RunnerConfig(command=command, env=env, cwd=cwd)


def _load_template(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取 prompt_template: {path}: {exc}") from exc
    if PLACEHOLDER not in text:
        raise ConfigError(f"prompt_template 必须包含 {PLACEHOLDER}: {path}")
    return text


def load_config(path: str | Path) -> TriggerConfig:
    config_path = Path(path).resolve()
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是合法 YAML: {exc}") from exc
    root = _mapping(payload, "配置文件")

    base_dir = config_path.parent
    prompt_template = _resolve_path(root.get("prompt_template"), "prompt_template", base_dir)
    if not prompt_template.is_file():
        raise ConfigError(f"prompt_template 不存在: {prompt_template}")
    template_text = _load_template(prompt_template)

    return TriggerConfig(
        engine=_parse_engine(root.get("engine")),
        state_dir=_resolve_path(root.get("state_dir"), "state_dir", base_dir),
        poll_seconds=_number(root.get("poll_seconds"), "poll_seconds", positive=True),
        prompt_template=prompt_template,
        template_text=template_text,
        triggers=_parse_triggers(root.get("triggers")),
        limits=_parse_limits(root.get("limits")),
        runner=_parse_runner(root.get("runner"), base_dir),
        config_path=config_path,
        base_dir=base_dir,
    )

