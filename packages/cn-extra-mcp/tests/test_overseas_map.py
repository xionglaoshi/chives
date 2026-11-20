from __future__ import annotations

from pathlib import Path

import pytest

from cn_extra_mcp import overseas_map as om

REPO_MAP = Path(__file__).resolve().parents[3] / "config" / "overseas-map.yaml"

GOOD = """leaders:
  - symbol: usNVDA
    name: 英伟达
    a_share_sectors: [算力, 光模块]
    note: "关联逻辑"
"""


def errors_of(text: str) -> list[str]:
    with pytest.raises(om.MapError) as info:
        om.parse_map_text(text)
    return info.value.errors


def test_good_block_entry() -> None:
    assert om.parse_map_text(GOOD) == [
        {"symbol": "usNVDA", "name": "英伟达", "a_share_sectors": ["算力", "光模块"], "note": "关联逻辑"}
    ]


def test_flow_entry_and_comments() -> None:
    text = "# c\nleaders:\n  - {symbol: hk00700, name: 腾讯, a_share_sectors: [游戏, 传媒], note: '约束'}\n"
    rows = om.parse_map_text(text)
    assert rows[0]["symbol"] == "hk00700" and rows[0]["a_share_sectors"] == ["游戏", "传媒"]
    assert rows[0]["note"] == "约束"


def test_note_optional_defaults_empty() -> None:
    text = "leaders:\n  - symbol: usAMD\n    name: 超威\n    a_share_sectors: [算力]\n"
    assert om.parse_map_text(text)[0]["note"] == ""


def test_empty_leaders_list() -> None:
    assert om.parse_map_text("leaders: []\n") == []


def test_unknown_entry_key_rejected_with_line() -> None:
    errs = errors_of(GOOD + "    price_target: 200\n")
    assert any(e.startswith("line 2:") and "unknown key 'price_target'" in e for e in errs)


def test_unknown_top_level_key() -> None:
    errs = errors_of(GOOD + "other: 1\n")
    assert any("line 6" in e and "unknown top-level key" in e for e in errs)


def test_duplicate_symbol_reports_second_entry_line() -> None:
    errs = errors_of(GOOD + GOOD.split("\n", 1)[1])
    assert any(e.startswith("line 6:") and "duplicate symbol" in e for e in errs)


@pytest.mark.parametrize("symbol", ["nvda", "usnvda", "us123", "sh600000", "hk123", "usTOOLONGX"])
def test_invalid_symbol_rejected(symbol: str) -> None:
    errs = errors_of(GOOD.replace("usNVDA", symbol))
    assert any("line 2:" in e and "invalid symbol" in e for e in errs)


def test_more_than_thirty_leaders_rejected() -> None:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = "leaders:\n" + "".join(
        f"  - symbol: us{letters[i // 26]}{letters[i % 26]}\n    name: n\n    a_share_sectors: [s]\n" for i in range(31)
    )
    errs = errors_of(body)
    assert any("more than 30 leaders" in e and e.startswith("line 92:") for e in errs)
    assert len(om.parse_map_text(body.rsplit("  - symbol", 1)[0])) == 30


def test_note_too_long_rejected() -> None:
    errs = errors_of(GOOD.replace("关联逻辑", "字" * 41))
    assert any("note must be" in e for e in errs)
    assert om.parse_map_text(GOOD.replace("关联逻辑", "字" * 40))


def test_missing_required_key() -> None:
    errs = errors_of("leaders:\n  - symbol: usNVDA\n    name: 英伟达\n")
    assert any("missing key 'a_share_sectors'" in e for e in errs)


def test_sectors_must_be_nonempty_list() -> None:
    assert any("a_share_sectors" in e for e in errors_of(GOOD.replace("[算力, 光模块]", "[]")))
    assert any("a_share_sectors" in e for e in errors_of(GOOD.replace("[算力, 光模块]", "算力")))


def test_duplicate_key_in_entry() -> None:
    assert any("duplicate key 'name'" in e for e in errors_of(GOOD + "    name: x\n"))


def test_malformed_lines_report_line_numbers() -> None:
    errs = errors_of("leaders:\n  - symbol: usNVDA\n    name 英伟达\n")
    assert any(e.startswith("line 3:") for e in errs)


def test_tab_indentation_rejected() -> None:
    assert any("tab" in e for e in errors_of("leaders:\n  - symbol: usNVDA\n\tname: x\n"))


def test_unsupported_syntax_rejected() -> None:
    assert any("unsupported" in e for e in errors_of(GOOD.replace("英伟达", "&anchor")))


def test_missing_leaders_key() -> None:
    assert any("missing 'leaders:'" in e for e in errors_of("# nothing\n"))


def test_load_missing_file_returns_none(tmp_path) -> None:
    assert om.load_map(tmp_path / "nope.yaml") is None


def test_load_reads_file(tmp_path) -> None:
    target = tmp_path / "m.yaml"
    target.write_text(GOOD, encoding="utf-8")
    assert om.load_map(target)[0]["symbol"] == "usNVDA"


def test_env_override_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(om.MAP_ENV, str(tmp_path / "x.yaml"))
    assert om.default_map_path() == tmp_path / "x.yaml"


def test_repository_map_is_valid_and_sized() -> None:
    rows = om.load_map(REPO_MAP)
    assert rows is not None and 8 <= len(rows) <= 12
    for row in rows:
        assert len(row["note"]) <= 40
        assert row["a_share_sectors"] and all(not s.isdigit() for s in row["a_share_sectors"])


def test_repository_map_notes_contain_no_forecast_words() -> None:
    rows = om.load_map(REPO_MAP)
    for word in ("将", "预计", "有望", "看涨", "看跌", "目标价", "买入", "上涨", "下跌"):
        assert all(word not in row["note"] for row in rows), word
