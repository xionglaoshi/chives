"""Strict configuration loading and validation for hub-trigger."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import yamlish

DEFAULT_HUB_URL = "http://127.0.0.1:8867"
HUB_ENV = "CHIVES_HUB_URL"
CONTEXT_PLACEHOLDER = "{context_json}"
RUNNER_PLACEHOLDER = "{prompt}"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SENSITIVE_HOME_DIRS = (".dsh", ".ssh", ".aws", ".config")

DEFAULT_MAX_RUNS_PER_DAY = 20
DEFAULT_COOLDOWN_SECONDS = 600.0
DEFAULT_MAX_TRIGGER_AGE_SECONDS = 120.0
DEFAULT_RUN_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_QUEUE = 3
DEFAULT_POLL_SECONDS = 2.0


class ConfigError(Exception):
    """Raised when the configuration file is missing, malformed or invalid."""


@dataclass(frozen=True)
class Limits:
    max_runs_per_day: int = DEFAULT_MAX_RUNS_PER_DAY
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    max_trigger_age_seconds: float = DEFAULT_MAX_TRIGGER_AGE_SECONDS
    run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS
    max_queue: int = DEFAULT_MAX_QUEUE


@dataclass(frozen=True)
class RunnerConfig:
    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: Path = Path(".")


@dataclass(frozen=True)
class FastJudgeConfig:
    hub: str
    state_dir: Path
    poll_seconds: float
    prompt_template: Path
    template_text: str
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


def _resolve_path(value: Any, where: str, base_dir: Path) -> Path:
    raw = _string(value, where)
    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = base_dir / target
    try:
        return target.resolve()
    except OSError as exc:
        raise ConfigError(f"{where} 无法解析: {raw}: {exc}") from exc


def _reject_unsafe_path(path: Path, where: str) -> None:
    if path == Path(path.anchor):
        raise ConfigError(f"{where} 不能是文件系统根目录")
    home = Path.home().resolve()
    if path == home:
        raise ConfigError(f"{where} 不能是用户主目录")
    for name in SENSITIVE_HOME_DIRS:
        sensitive = (home / name).resolve()
        if path == sensitive or sensitive in path.parents:
            raise ConfigError(f"{where} 不能指向敏感目录: {path}")


def validate_hub_url(raw: str) -> str:
    text = raw.strip()
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise ConfigError(f"hub URL 非法: {raw!r}") from exc
    if parts.scheme not in {"http", "https"}:
        raise ConfigError("hub 必须是 http(s) URL")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(
            f"hub 主机必须是回环地址（127.0.0.1 / localhost / [::1]）: {host or raw!r}"
        )
    if parts.username or parts.password:
        raise ConfigError("hub 不得包含用户名或密码")
    try:
        port = parts.port
    except ValueError as exc:
        raise ConfigError(f"hub 端口非法: {raw!r}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"hub 端口越界: {port}")
    if parts.query or parts.fragment:
        raise ConfigError("hub 不得包含查询参数或片段")
    if parts.path not in {"", "/"}:
        raise ConfigError("hub 不得包含路径")
    return text.rstrip("/")


def _hub_from(entry: Mapping[str, Any], environ: Mapping[str, str]) -> str:
    env_value = environ.get(HUB_ENV)
    if isinstance(env_value, str) and env_value.strip():
        return validate_hub_url(env_value)
    configured = entry.get("hub", entry.get("engine"))
    if configured is None:
        return DEFAULT_HUB_URL
    return validate_hub_url(_string(configured, "hub"))


def _first(entry: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in entry:
            return entry[name]
    return None


def _parse_limits(value: Any) -> Limits:
    if value is None:
        entry: Mapping[str, Any] = {}
    else:
        entry = _mapping(value, "limits")
    max_runs = _first(entry, ("max_runs_per_day", "max_judgements_per_day", "daily_limit"))
    cooldown = entry.get("cooldown_seconds")
    max_age = _first(entry, ("max_trigger_age_seconds", "max_age_seconds"))
    timeout = _first(entry, ("run_timeout_seconds", "timeout_seconds"))
    max_queue = entry.get("max_queue")
    return Limits(
        max_runs_per_day=(
            DEFAULT_MAX_RUNS_PER_DAY
            if max_runs is None
            else _positive_int(max_runs, "limits.max_runs_per_day")
        ),
        cooldown_seconds=(
            DEFAULT_COOLDOWN_SECONDS
            if cooldown is None
            else _number(cooldown, "limits.cooldown_seconds", nonnegative=True)
        ),
        max_trigger_age_seconds=(
            DEFAULT_MAX_TRIGGER_AGE_SECONDS
            if max_age is None
            else _number(max_age, "limits.max_trigger_age_seconds", positive=True)
        ),
        run_timeout_seconds=(
            DEFAULT_RUN_TIMEOUT_SECONDS
            if timeout is None
            else _number(timeout, "limits.run_timeout_seconds", positive=True)
        ),
        max_queue=(
            DEFAULT_MAX_QUEUE if max_queue is None else _positive_int(max_queue, "limits.max_queue")
        ),
    )


def _parse_runner(value: Any, base_dir: Path) -> RunnerConfig:
    entry = _mapping(value, "runner")
    raw_command = _sequence(entry.get("command"), "runner.command")
    if not raw_command:
        raise ConfigError("runner.command 不能为空")
    command = tuple(
        _string(part, f"runner.command[{index}]") for index, part in enumerate(raw_command)
    )
    if command.count(RUNNER_PLACEHOLDER) != 1:
        raise ConfigError(f"runner.command 必须恰好有一个元素等于 {RUNNER_PLACEHOLDER}")
    raw_env = entry.get("env", {})
    env_entry = _mapping({} if raw_env is None else raw_env, "runner.env")
    env: dict[str, str] = {}
    for key, item in env_entry.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError("runner.env 的键必须是非空字符串")
        if "=" in key or "\x00" in key:
            raise ConfigError(f"runner.env.{key} 不是合法的环境变量名")
        if not isinstance(item, str):
            raise ConfigError(f"runner.env.{key} 必须是字符串")
        env[key] = item
    raw_cwd = entry.get("cwd", ".")
    cwd = _resolve_path("." if raw_cwd is None else raw_cwd, "runner.cwd", base_dir)
    if not cwd.is_dir():
        raise ConfigError(f"runner.cwd 不存在或不是目录: {cwd}")
    _reject_unsafe_path(cwd, "runner.cwd")
    return RunnerConfig(command=command, env=env, cwd=cwd)


def _load_template(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取 prompt_template: {path}: {exc}") from exc
    if CONTEXT_PLACEHOLDER not in text:
        raise ConfigError(f"prompt_template 必须包含 {CONTEXT_PLACEHOLDER}: {path}")
    return text


def load_config(path: str | Path, environ: Mapping[str, str] | None = None) -> FastJudgeConfig:
    config_path = Path(path).resolve()
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    try:
        payload = yamlish.parse(raw_text)
    except yamlish.YamlError as exc:
        raise ConfigError(f"配置文件不是合法 YAML: {exc}") from exc
    root = _mapping(payload, "配置文件")

    base_dir = config_path.parent
    prompt_template = _resolve_path(root.get("prompt_template"), "prompt_template", base_dir)
    if not prompt_template.is_file():
        raise ConfigError(f"prompt_template 不存在: {prompt_template}")
    template_text = _load_template(prompt_template)

    state_dir = _resolve_path(root.get("state_dir"), "state_dir", base_dir)
    _reject_unsafe_path(state_dir, "state_dir")
    if state_dir.exists() and not state_dir.is_dir():
        raise ConfigError(f"state_dir 已存在但不是目录: {state_dir}")

    poll_raw = root.get("poll_seconds")
    poll_seconds = (
        DEFAULT_POLL_SECONDS
        if poll_raw is None
        else _number(poll_raw, "poll_seconds", positive=True)
    )

    return FastJudgeConfig(
        hub=_hub_from(root, os.environ if environ is None else environ),
        state_dir=state_dir,
        poll_seconds=poll_seconds,
        prompt_template=prompt_template,
        template_text=template_text,
        limits=_parse_limits(root.get("limits")),
        runner=_parse_runner(root.get("runner"), base_dir),
        config_path=config_path,
        base_dir=base_dir,
    )
