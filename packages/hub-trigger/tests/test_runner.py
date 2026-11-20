"""Runner isolation: argv, environment whitelist and process-group timeout."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from hub_trigger.config import RunnerConfig
from hub_trigger.runner import (
    ENV_WHITELIST,
    build_argv,
    build_runner_env,
    parse_events,
    run_runner,
)

from support import DEFAULT_TEXT, FAKE_RUNNER, NOW, runner_config, runner_log


def test_build_argv_keeps_prompt_as_one_element() -> None:
    argv = build_argv(("python", "script.py", "{prompt}"), "多行\n提示｜x")
    assert argv == ["python", "script.py", "多行\n提示｜x"]


def test_env_whitelist_only() -> None:
    env = build_runner_env(
        {"PATH": "/bin", "HOME": "/tmp", "SECRET_TOKEN": "x", "RANDOM": "y"},
        {"DSH_HOME": "/home/test"},
    )
    assert env["PATH"] == "/bin"
    assert env["HOME"] == "/tmp"
    assert env["DSH_HOME"] == "/home/test"
    assert "SECRET_TOKEN" not in env
    assert "RANDOM" not in env
    assert set(ENV_WHITELIST).issuperset({"PATH", "HOME"})


def test_env_extra_overrides_base() -> None:
    env = build_runner_env({"LANG": "C"}, {"LANG": "zh_CN.UTF-8"})
    assert env["LANG"] == "zh_CN.UTF-8"


def test_parse_events_takes_last_final() -> None:
    stdout = "\n".join(
        [
            "noise",
            '{"type": "session", "sessionId": "s1"}',
            '{"type": "final", "text": "first"}',
            '{"type": "final", "text": "last"}',
        ]
    )
    session, text = parse_events(stdout)
    assert session == "s1"
    assert text == "last"


def test_parse_events_ignores_non_objects_and_bad_json() -> None:
    assert parse_events("[]\n{bad}\n") == (None, None)


def test_successful_run(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path), "prompt", 5, lambda: NOW)
    assert result.status == "done"
    assert result.text == DEFAULT_TEXT
    assert result.exit_code == 0


def test_prompt_is_single_argv_element(tmp_path: Path) -> None:
    run_runner(runner_config(tmp_path), "line1\nline2", 5, lambda: NOW)
    log = runner_log(tmp_path)
    assert log[0]["argc"] == 1
    assert log[0]["prompt"] == "line1\nline2"


def test_runner_env_reaches_child(tmp_path: Path) -> None:
    result = run_runner(
        runner_config(tmp_path),
        "p",
        5,
        lambda: NOW,
        base_env={"PATH": "/bin", "SECRET_TOKEN": "hidden", "OTHER": "hidden"},
    )
    assert result.status == "done"
    names = runner_log(tmp_path)[0]["env_names"]
    assert "SECRET_TOKEN" not in names
    assert "OTHER" not in names
    assert "FAKE_RUNNER_MODE" in names


def test_runner_cwd_is_used(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_runner(runner_config(tmp_path, cwd=workspace), "p", 5, lambda: NOW)
    assert runner_log(tmp_path)[0]["cwd"] == str(workspace)


def test_nonzero_exit_is_failed_without_stderr_leak(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path, mode="fail"), "secret context", 5, lambda: NOW)
    assert result.status == "failed"
    assert result.reason == "runner 退出码 1"
    assert "boom" not in (result.reason or "")
    assert "secret context" not in (result.reason or "")


def test_missing_final_event_is_failed(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path, mode="no_final"), "p", 5, lambda: NOW)
    assert result.status == "failed"
    assert result.reason == "runner 没有输出 final 事件"


def test_timeout_kills_the_process_group(tmp_path: Path) -> None:
    result = run_runner(runner_config(tmp_path, mode="slow"), "p", 0.3, lambda: NOW)
    assert result.status == "timeout"
    assert "未结束" in (result.reason or "")
    pid = runner_log(tmp_path)[0]["pid"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail("timeout 后 runner 进程仍存活")


def test_timeout_kills_child_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    config = runner_config(
        tmp_path,
        mode="slow_spawn",
        extra_env={"FAKE_RUNNER_CHILD_PID": str(child_pid_path)},
    )
    result = run_runner(config, "p", 0.5, lambda: NOW)
    assert result.status == "timeout"
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_path.exists(), "fake runner 没有写出子进程 pid"
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail("timeout 后子进程仍存活")


def test_start_failure_is_failed(tmp_path: Path) -> None:
    config = RunnerConfig(command=("definitely-not-a-real-binary-xyz", "{prompt}"), cwd=tmp_path)
    result = run_runner(config, "p", 5, lambda: NOW)
    assert result.status == "failed"
    assert "无法启动" in (result.reason or "")


def test_custom_final_text(tmp_path: Path) -> None:
    result = run_runner(
        runner_config(tmp_path, mode="text", text="放弃｜跌破止损｜收盘前｜不再跟"),
        "p",
        5,
        lambda: NOW,
    )
    assert result.status == "done"
    assert result.text == "放弃｜跌破止损｜收盘前｜不再跟"


def test_stdout_non_json_is_ignored(tmp_path: Path) -> None:
    runner = tmp_path / "plain.py"
    runner.write_text(
        "import sys\nprint('观察｜理由｜10:30｜边界')\nprint(sys.argv[-1][:0])\n",
        encoding="utf-8",
    )
    config = RunnerConfig(command=(sys.executable, str(runner), "{prompt}"), cwd=tmp_path)
    result = run_runner(config, "p", 5, lambda: NOW)
    assert result.status == "failed"
    assert result.text is None


def test_fake_runner_module_exists() -> None:
    assert FAKE_RUNNER.is_file()
