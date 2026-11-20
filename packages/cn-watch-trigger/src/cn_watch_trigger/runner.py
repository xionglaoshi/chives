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

SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
STDERR_TAIL_CHARS = 400
REAP_TIMEOUT_SECONDS = 10.0

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class RunResult:
    status: str
    session_id: str | None
    text: str | None
    reason: str | None
    started_at: datetime
    finished_at: datetime


def build_runner_env(
    base_env: Mapping[str, str], extra_env: Mapping[str, str]
) -> dict[str, str]:
    """Drop secret-looking variables, then apply the configured overlay."""

    env = {
        key: value
        for key, value in base_env.items()
        if not any(marker in key.upper() for marker in SECRET_MARKERS)
    }
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


def _one_line(text: str, limit: int = STDERR_TAIL_CHARS) -> str:
    flattened = " ".join(part.strip() for part in text.strip().splitlines() if part.strip())
    return flattened[-limit:]


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
            session_id=None,
            text=None,
            reason=f"无法启动 runner: {exc}",
            started_at=started_at,
            finished_at=clock(),
        )

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

    finished_at = clock()
    session_id, final_text = parse_events(stdout)
    if timed_out:
        return RunResult(
            status="timeout",
            session_id=session_id,
            text=None,
            reason=f"runner 超过 {timeout_seconds:g}s 未结束，已杀掉进程组",
            started_at=started_at,
            finished_at=finished_at,
        )
    if process.returncode != 0:
        detail = _one_line(stderr)
        reason = f"runner 退出码 {process.returncode}"
        if detail:
            reason = f"{reason}: {detail}"
        return RunResult(
            status="failed",
            session_id=session_id,
            text=None,
            reason=reason,
            started_at=started_at,
            finished_at=finished_at,
        )
    if final_text is None:
        detail = _one_line(stderr)
        reason = "runner 没有输出 final 事件"
        if detail:
            reason = f"{reason}: {detail}"
        return RunResult(
            status="failed",
            session_id=session_id,
            text=None,
            reason=reason,
            started_at=started_at,
            finished_at=finished_at,
        )
    return RunResult(
        status="done",
        session_id=session_id,
        text=final_text,
        reason=None,
        started_at=started_at,
        finished_at=finished_at,
    )
