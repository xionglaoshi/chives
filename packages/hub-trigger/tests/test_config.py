"""Configuration validation: loopback-only hub, limits and runner safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub_trigger.config import (
    DEFAULT_HUB_URL,
    ConfigError,
    load_config,
    validate_hub_url,
)

from support import TEMPLATE, base_config_dict, write_config


def _payload(tmp_path: Path, **overrides: object) -> dict[str, object]:
    payload = base_config_dict(tmp_path, "http://127.0.0.1:8867")
    payload.update(overrides)
    return payload


def test_json_config_loads(tmp_path: Path) -> None:
    path = write_config(tmp_path, _payload(tmp_path))
    config = load_config(path, environ={"CHIVES_HUB_URL": ""})
    assert config.hub == "http://127.0.0.1:8867"
    assert config.poll_seconds == 0.5
    assert config.limits.max_runs_per_day == 20


def test_yaml_block_config_loads(tmp_path: Path) -> None:
    path = tmp_path / "fastjudge.yaml"
    path.write_text(
        "\n".join(
            [
                "hub: http://127.0.0.1:8867",
                "state_dir: state",
                "poll_seconds: 1.5",
                f"prompt_template: {TEMPLATE}",
                "limits:",
                "  max_runs_per_day: 4",
                "  cooldown_seconds: 0",
                "  max_trigger_age_seconds: 60",
                "  run_timeout_seconds: 3",
                "  max_queue: 1",
                "runner:",
                "  command:",
                f"  - {Path('/usr/bin/python3')}",
                "  - -c",
                "  - 'print(1)'",
                "  - '{prompt}'",
                "  env: {}",
                "  cwd: .",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(path, environ={"CHIVES_HUB_URL": ""})
    assert config.poll_seconds == 1.5
    assert config.limits.max_runs_per_day == 4
    assert config.runner.command[-1] == "{prompt}"


def test_comment_before_json_is_allowed(tmp_path: Path) -> None:
    path = tmp_path / "fastjudge.yaml"
    path.write_text(
        "# generated\n" + json.dumps(_payload(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    assert load_config(path, environ={"CHIVES_HUB_URL": ""}).limits.max_queue == 3


def test_env_hub_overrides_config(tmp_path: Path) -> None:
    path = write_config(tmp_path, _payload(tmp_path))
    config = load_config(path, environ={"CHIVES_HUB_URL": "http://localhost:9999"})
    assert config.hub == "http://localhost:9999"


def test_empty_env_hub_keeps_config(tmp_path: Path) -> None:
    path = write_config(tmp_path, _payload(tmp_path))
    config = load_config(path, environ={"CHIVES_HUB_URL": "  "})
    assert config.hub == "http://127.0.0.1:8867"


def test_default_hub_when_absent(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload.pop("hub")
    path = write_config(tmp_path, payload)
    assert load_config(path, environ={"CHIVES_HUB_URL": ""}).hub == DEFAULT_HUB_URL


def test_engine_alias_is_accepted(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload.pop("hub")
    payload["engine"] = "http://127.0.0.1:8888/"
    path = write_config(tmp_path, payload)
    assert load_config(path, environ={"CHIVES_HUB_URL": ""}).hub == "http://127.0.0.1:8888"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8867",
        "http://127.0.0.1.evil.com:8867",
        "http://localhost.evil.com",
        "https://0.0.0.0:8867",
        "ftp://127.0.0.1:8867",
        "http://user:pass@127.0.0.1:8867",
        "http://127.0.0.1:8867?x=1",
        "http://127.0.0.1:8867#frag",
        "http://127.0.0.1:8867/api",
        "http://127.0.0.1:99999",
        "not-a-url",
        "",
    ],
)
def test_non_loopback_or_malformed_hub_is_rejected(url: str) -> None:
    with pytest.raises(ConfigError):
        validate_hub_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8867",
        "http://127.0.0.1",
        "http://localhost:8867/",
        "http://[::1]:8867",
        "https://127.0.0.1:8867",
    ],
)
def test_loopback_hub_is_accepted(url: str) -> None:
    assert validate_hub_url(url) == url.rstrip("/")


def test_env_non_loopback_rejected_at_load(tmp_path: Path) -> None:
    path = write_config(tmp_path, _payload(tmp_path))
    with pytest.raises(ConfigError):
        load_config(path, environ={"CHIVES_HUB_URL": "http://10.0.0.1:8867"})


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml", environ={})


def test_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("a: 1\n   b: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_prompt_template_missing(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["prompt_template"] = str(tmp_path / "nope.md")
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_prompt_template_without_placeholder(tmp_path: Path) -> None:
    template = tmp_path / "template.md"
    template.write_text("hello", encoding="utf-8")
    payload = _payload(tmp_path)
    payload["prompt_template"] = str(template)
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_state_dir_cannot_be_a_file(tmp_path: Path) -> None:
    target = tmp_path / "state-file"
    target.write_text("x", encoding="utf-8")
    payload = _payload(tmp_path)
    payload["state_dir"] = str(target)
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


@pytest.mark.parametrize("path", ["/", str(Path.home())])
def test_state_dir_cannot_be_root_or_home(tmp_path: Path, path: str) -> None:
    payload = _payload(tmp_path)
    payload["state_dir"] = path
    config_path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(config_path, environ={})


def test_state_dir_cannot_be_dsh_home(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["state_dir"] = str(Path.home() / ".dsh" / "state")
    config_path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(config_path, environ={})


@pytest.mark.parametrize("value", [0, -1, True, "3", None])
def test_poll_seconds_must_be_positive(tmp_path: Path, value: object) -> None:
    payload = _payload(tmp_path)
    payload["poll_seconds"] = value
    path = write_config(tmp_path, payload)
    if value is None:
        config = load_config(path, environ={})
        assert config.poll_seconds == 2.0
    else:
        with pytest.raises(ConfigError):
            load_config(path, environ={})


def test_limits_default_when_absent(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload.pop("limits")
    path = write_config(tmp_path, payload)
    limits = load_config(path, environ={}).limits
    assert limits.max_runs_per_day == 20
    assert limits.cooldown_seconds == 600
    assert limits.max_trigger_age_seconds == 120
    assert limits.run_timeout_seconds == 120
    assert limits.max_queue == 3


def test_limits_alias(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["limits"] = {"max_judgements_per_day": 7}
    path = write_config(tmp_path, payload)
    assert load_config(path, environ={}).limits.max_runs_per_day == 7


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_runs_per_day", 0),
        ("max_runs_per_day", -2),
        ("max_runs_per_day", 1.5),
        ("cooldown_seconds", -1),
        ("max_trigger_age_seconds", 0),
        ("run_timeout_seconds", 0),
        ("max_queue", 0),
        ("max_queue", 2.5),
    ],
)
def test_invalid_limits_are_rejected(tmp_path: Path, key: str, value: object) -> None:
    payload = _payload(tmp_path)
    payload["limits"] = {key: value}
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_zero_cooldown_is_allowed(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["limits"] = {"cooldown_seconds": 0}
    path = write_config(tmp_path, payload)
    assert load_config(path, environ={}).limits.cooldown_seconds == 0


def test_runner_command_must_be_a_list(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["command"] = "python {prompt}"  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_command_needs_exactly_one_prompt(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["command"] = ["python", "script.py"]  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_command_rejects_two_prompts(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["command"] = ["python", "{prompt}", "{prompt}"]  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_empty_env_defaults_to_empty_mapping(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["env"] = None  # type: ignore[index]
    path = write_config(tmp_path, payload)
    assert dict(load_config(path, environ={}).runner.env) == {}


def test_runner_empty_cwd_defaults_to_config_dir(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["cwd"] = None  # type: ignore[index]
    path = write_config(tmp_path, payload)
    assert load_config(path, environ={}).runner.cwd == tmp_path.resolve()


def test_runner_cwd_must_exist(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["cwd"] = "missing-dir"  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_cwd_cannot_be_sensitive(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["cwd"] = str(Path.home() / ".dsh")  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_env_must_be_strings(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["env"] = {"PORT": 8867}  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_runner_env_rejects_bad_names(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["runner"]["env"] = {"BAD=NAME": "x"}  # type: ignore[index]
    path = write_config(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_config(path, environ={})


def test_relative_paths_resolve_against_config_dir(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    payload["state_dir"] = "nested/state"
    path = write_config(tmp_path, payload)
    config = load_config(path, environ={})
    assert config.state_dir == (tmp_path / "nested/state").resolve()


def test_inline_comments_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "fastjudge.yaml"
    text = "\n".join(
        [
            "hub: http://127.0.0.1:8867  # local",
            "state_dir: state  # cursor",
            "poll_seconds: 1  # second",
            f"prompt_template: {TEMPLATE}",
            "limits: {}",
            "runner:",
            "  command: ['python', '{prompt}']",
            "  env: {}",
            "  cwd: .",
        ]
    )
    path.write_text(text, encoding="utf-8")
    config = load_config(path, environ={})
    assert config.hub == "http://127.0.0.1:8867"
    assert config.poll_seconds == 1.0
