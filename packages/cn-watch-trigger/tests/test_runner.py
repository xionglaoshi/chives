from __future__ import annotations

import os
import time
from pathlib import Path

from cn_watch_trigger.config import RunnerConfig
from cn_watch_trigger.runner import build_argv, build_runner_env, parse_events, run_runner

from support import FAKE_RUNNER, NOW, runner_log, runner_config


def wait_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_done_parses_session_and_final(tmp_path: Path) -> None:
    runner = runner_config(tmp_path)
    env = {"MY_API_KEY": "secret", "FAKE_SECRET_TOKEN": "secret", "KEEP_ME": "ok"}
    result = run_runner(runner, "hello {alert_json}", 5, lambda: NOW, base_env=env)
    assert result.status == "done"
    assert result.session_id and result.session_id.startswith("session-fake-")
    assert result.text and "分析完成" in result.text
    assert result.reason is None
    rows = runner_log(tmp_path)
    assert rows[0]["argc"] == 1
    assert rows[0]["prompt"] == "hello {alert_json}"
    assert rows[0]["cwd"] == str(tmp_path)
    names = set(rows[0]["env_names"])
    assert "MY_API_KEY" not in names
    assert "FAKE_SECRET_TOKEN" not in names
    assert "KEEP_ME" in names
    assert "FAKE_RUNNER_MODE" in names


def test_env_overlay_is_not_filtered(tmp_path: Path) -> None:
    runner = runner_config(tmp_path, extra_env={"EXTRA_SECRET_TOKEN": "from-config"})
    result = run_runner(runner, "x", 5, lambda: NOW, base_env={"KEEP": "1"})
    assert result.status == "done"
    assert "EXTRA_SECRET_TOKEN" in set(runner_log(tmp_path)[0]["env_names"])


def test_fail_exit_code_is_failed(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path, mode="fail"), "x", 5, lambda: NOW)
    assert result.status == "failed"
    assert "退出码 1" in (result.reason or "")
    assert "boom" in (result.reason or "")
    assert result.text is None


def test_no_final_is_failed(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path, mode="no_final"), "x", 5, lambda: NOW)
    assert result.status == "failed"
    assert "final" in (result.reason or "")


def test_timeout_kills_whole_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    runner = runner_config(
        tmp_path,
        mode="slow_spawn",
        extra_env={"FAKE_RUNNER_CHILD_PID": str(child_pid_path)},
    )
    started = time.monotonic()
    result = run_runner(runner, "x", 1, lambda: NOW)
    elapsed = time.monotonic() - started
    assert result.status == "timeout"
    assert "进程组" in (result.reason or "")
    assert elapsed < 15
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    assert wait_gone(child_pid), f"child {child_pid} still alive"


def test_missing_executable_is_failed(tmp_path: Path) -> None:
    runner = RunnerConfig(command=("/nonexistent/runner", "{prompt}"), env={}, cwd=tmp_path)
    result = run_runner(runner, "x", 5, lambda: NOW)
    assert result.status == "failed"
    assert "无法启动" in (result.reason or "")


def test_build_argv_replaces_exactly_one_element() -> None:
    argv = build_argv(("prog", "--json", "{prompt}"), "prompt text")
    assert argv == ["prog", "--json", "prompt text"]
    assert build_argv(("prog", "literal {prompt}"), "prompt") == ["prog", "literal {prompt}"]


def test_build_runner_env_case_insensitive() -> None:
    env = build_runner_env(
        {"my_api_key": "x", "Token": "y", "passwd": "z", "SECRET_X": "s", "PASSWORD": "p", "KEEP": "ok"},
        {},
    )
    assert env == {"passwd": "z", "KEEP": "ok"}


def test_parse_events_uses_last_values() -> None:
    stdout = "\n".join(
        [
            "garbage",
            '{"type":"session","sessionId":"s1"}',
            '{"type":"final","text":"one"}',
            '{"type":"session","sessionId":"s2"}',
            '{"type":"final","text":"two"}',
            "[1,2,3]",
        ]
    )
    assert parse_events(stdout) == ("s2", "two")


def test_runner_command_has_no_shell(tmp_path: Path) -> None:
    # The prompt contains shell metacharacters; a shell=True implementation would break or execute them.
    prompt = "x; echo SHOULD_NOT_RUN $(touch pwned) `touch pwned2`"
    result = run_runner(runner_config(tmp_path), prompt, 5, lambda: NOW)
    assert result.status == "done"
    assert runner_log(tmp_path)[0]["prompt"] == prompt
    assert not (tmp_path / "pwned").exists()
    assert not (tmp_path / "pwned2").exists()


def test_fake_runner_is_a_file() -> None:
    assert FAKE_RUNNER.exists()
