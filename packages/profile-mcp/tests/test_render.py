from __future__ import annotations

import stat
from pathlib import Path

import pytest

from profile_mcp.fields import MAX_BLOCK_BYTES, validate_fields
from profile_mcp.render import (
    END_MARKER,
    INTRO,
    START_MARKER,
    render_block,
    sync_agents_md,
)

PROFILE = {
    "investor_type": "long_term",
    "horizon": "years",
    "markets": ["cn", "hk"],
    "sectors": ["半导体", "电力设备"],
    "constraints": ["不碰 ST"],
    "language": "zh",
    "agent_preference": "多给我反方证据，不要只讲多头逻辑。",
}


def test_block_contains_intro_markers_and_quoted_user_text() -> None:
    block = render_block(validate_fields(PROFILE))
    assert block.startswith(START_MARKER)
    assert block.endswith(END_MARKER)
    assert INTRO in block
    assert '"半导体"' in block
    assert '"多给我反方证据，不要只讲多头逻辑。"' in block
    assert "investor_type" in block and "long_term" in block


def test_block_never_exceeds_2kb() -> None:
    big = validate_fields(
        {
            "investor_type": "practitioner",
            "experience_years": 60,
            "risk_level": "aggressive",
            "horizon": "years",
            "markets": ["cn", "us", "hk"],
            "sectors": ["行业" * 15 for _ in range(10)],
            "styles": ["风格" * 15 for _ in range(10)],
            "asset_classes": ["资产" * 15 for _ in range(10)],
            "capital_range": "gt_10m",
            "constraints": ["约束" * 30 for _ in range(8)],
            "research_depth": "thorough",
            "output_format": ["chart", "file", "text"],
            "language": "zh",
            "agent_preference": "长" * 300,
        }
    )
    block = render_block(big)
    assert len(block.encode("utf-8")) <= MAX_BLOCK_BYTES
    assert START_MARKER in block and END_MARKER in block


def test_block_has_no_raw_newlines_from_user_text() -> None:
    block = render_block(validate_fields({"agent_preference": "第一行\n第二行"}))
    assert "第一行 第二行" in block
    body = block.replace(START_MARKER, "").replace(END_MARKER, "")
    for line in body.splitlines():
        assert "\n" not in line


def test_append_preserves_existing_content(home: Path) -> None:
    path = home / "AGENTS.md"
    original = "# 我的全局规则\n\n- 不要追高\n"
    path.write_text(original, encoding="utf-8")
    info, warnings = sync_agents_md(path, validate_fields(PROFILE))
    assert warnings == []
    assert info["status"] == "updated"
    text = path.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert text.count(START_MARKER) == 1
    assert text.count(END_MARKER) == 1
    assert "不要追高" in text


def test_creates_file_when_missing(home: Path) -> None:
    path = home / "AGENTS.md"
    info, warnings = sync_agents_md(path, validate_fields(PROFILE))
    assert warnings == []
    assert info["status"] == "created"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8").startswith(START_MARKER)


def test_replaces_block_instead_of_appending(home: Path) -> None:
    path = home / "AGENTS.md"
    path.write_text(
        "before\n" + START_MARKER + "\n## 旧内容\n- language: en\n" + END_MARKER + "\nafter\n",
        encoding="utf-8",
    )
    info, warnings = sync_agents_md(path, validate_fields(PROFILE))
    assert warnings == []
    assert info["status"] == "updated"
    text = path.read_text(encoding="utf-8")
    assert text.count(START_MARKER) == 1
    assert text.count(END_MARKER) == 1
    assert "旧内容" not in text
    assert text.startswith("before\n")
    assert text.endswith("\nafter\n")
    assert INTRO in text


def test_second_sync_is_a_noop(home: Path) -> None:
    path = home / "AGENTS.md"
    profile = validate_fields(PROFILE)
    sync_agents_md(path, profile)
    first = path.read_text(encoding="utf-8")
    info, warnings = sync_agents_md(path, profile)
    assert warnings == []
    assert info["status"] == "unchanged"
    assert path.read_text(encoding="utf-8") == first


def test_preserves_existing_file_mode(home: Path) -> None:
    path = home / "AGENTS.md"
    path.write_text("keep me\n", encoding="utf-8")
    path.chmod(0o644)
    sync_agents_md(path, validate_fields(PROFILE))
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "text",
    [
        "before\n" + START_MARKER + "\nno end\n",
        "before\nno start\n" + END_MARKER + "\n",
        END_MARKER + "\nold\n" + START_MARKER + "\n",
        START_MARKER + "\na\n" + END_MARKER + "\n" + START_MARKER + "\nb\n" + END_MARKER + "\n",
        START_MARKER + "\n" + START_MARKER + "\n" + END_MARKER + "\n",
    ],
)
def test_broken_markers_leave_file_untouched(home: Path, text: str) -> None:
    path = home / "AGENTS.md"
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    info, warnings = sync_agents_md(path, validate_fields(PROFILE))
    assert info["status"] == "skipped"
    assert [warning["code"] for warning in warnings] == ["agents_md_markers_broken"]
    assert path.read_bytes() == before


def test_empty_profile_removes_block_only(home: Path) -> None:
    path = home / "AGENTS.md"
    sync_agents_md(path, validate_fields(PROFILE))
    with_block = path.read_text(encoding="utf-8")
    assert "半导体" in with_block
    path.write_text("keep-before\n" + with_block + "\nkeep-after\n", encoding="utf-8")
    info, warnings = sync_agents_md(path, {})
    assert warnings == []
    assert info["status"] == "removed"
    text = path.read_text(encoding="utf-8")
    assert START_MARKER not in text
    assert END_MARKER not in text
    assert "keep-before" in text
    assert "keep-after" in text
    assert "半导体" not in text


@pytest.mark.parametrize("original", ["我的规则\n\n- 不要追高\n", "我的规则\n\n- 不要追高", "我的规则"])
def test_update_then_clear_restores_original(home: Path, original: str) -> None:
    path = home / "AGENTS.md"
    path.write_text(original, encoding="utf-8")
    sync_agents_md(path, validate_fields(PROFILE))
    assert START_MARKER in path.read_text(encoding="utf-8")
    sync_agents_md(path, {})
    result = path.read_text(encoding="utf-8")
    assert result.rstrip("\n") == original.rstrip("\n")
    if original.endswith("\n"):
        assert result == original


def test_empty_profile_does_not_create_file(home: Path) -> None:
    path = home / "AGENTS.md"
    info, warnings = sync_agents_md(path, {})
    assert warnings == []
    assert info["status"] == "unchanged"
    assert not path.exists()


def test_unreadable_agents_md_is_left_alone(home: Path) -> None:
    path = home / "AGENTS.md"
    path.write_bytes(b"\xff\xfe\x00broken")
    before = path.read_bytes()
    info, warnings = sync_agents_md(path, validate_fields(PROFILE))
    assert info["status"] == "skipped"
    assert [warning["code"] for warning in warnings] == ["agents_md_unreadable"]
    assert path.read_bytes() == before
