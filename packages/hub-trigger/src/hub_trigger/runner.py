"""Run a headless dsh-like command and parse its JSON event stream."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from .config import RUNNER_PLACEHOLDER, RunnerConfig

REAP_TIMEOUT_SECONDS = 10.0

# Only these inherited variables are handed to the runner.  DSH_HOME and any
# other run-specific values must be declared explicitly in runner.env.
ENV_WHITELIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TZ",
        "TERM",
        "TMPDIR",
        "TEMP",
        "TMP",
        "USER",
        "LOGNAME",
        "SHELL",
        "PYTHONIOENCODING",
        "PYTHONUNBUFFERED",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
    }
)

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class RunResult:
    status: str
    text: str | None
    reason: str | None
    started_at: datetime
    finished_at: datetime
    exit_code: int | None = None


def build_runner_env(
    base_env: Mapping[str, str], extra_env: Mapping[str, str]
) -> dict[str, str]:
    """Keep only whitelisted inherited variables, then apply runner.env."""

    env = {key: value for key, value in base_env.items() if key in ENV_WHITELIST}
    env.update(extra_env)
    return env


def build_argv(command: tuple[str, ...], prompt: str) -> list[str]:
    return [prompt if part == RUNNER_PLACEHOLDER else part for part in command]


def parse_events(stdout: str) -> tuple[str | None, str | None]:
    session_id: str | None = None
    final_text: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "session":
            candidate = event.get("sessionId")
            if isinstance(candidate, str):
                session_id = candidate
        elif event.get("type") == "final":
            candidate = event.get("text")
            if isinstance(candidate, str):
                final_text = candidate
    return session_id, final_text


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def run_runner(
    runner: RunnerConfig,
    prompt: str,
    timeout_seconds: float,
    clock: Clock,
    base_env: Mapping[str, str] | None = None,
) -> RunResult:
    argv = build_argv(runner.command, prompt)
    env = build_runner_env(os.environ if base_env is None else base_env, runner.env)
    started_at = clock()
    try:
        process: subprocess.Popen[str] = subprocess.Popen(
            argv,
            cwd=str(runner.cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return RunResult(
            status="failed",
            text=None,
            reason=f"无法启动 runner: {exc}",
            started_at=started_at,
            finished_at=clock(),
        )

    timed_out = False
    try:
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        try:
            stdout, _stderr = process.communicate(timeout=REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _stderr = process.communicate()

    finished_at = clock()
    _session_id, final_text = parse_events(stdout)
    if timed_out:
        return RunResult(
            status="timeout",
            text=None,
            reason=f"runner 超过 {timeout_seconds:g}s 未结束，已杀掉进程组",
            started_at=started_at,
            finished_at=finished_at,
        )
    if process.returncode != 0:
        return RunResult(
            status="failed",
            text=None,
            reason=f"runner 退出码 {process.returncode}",
            started_at=started_at,
            finished_at=finished_at,
            exit_code=process.returncode,
        )
    if final_text is None:
        return RunResult(
            status="failed",
            text=None,
            reason="runner 没有输出 final 事件",
            started_at=started_at,
            finished_at=finished_at,
            exit_code=process.returncode,
        )
    return RunResult(
        status="done",
        text=final_text,
        reason=None,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=process.returncode,
    )
