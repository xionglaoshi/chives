from __future__ import annotations

import pytest

from chives_compass import yamlmini


def test_block_mapping_scalars():
    data = yamlmini.loads("a: 1\nb: 2.5\nc: true\nd: false\ne: null\nf: text\n")
    assert data == {"a": 1, "b": 2.5, "c": True, "d": False, "e": None, "f": "text"}


def test_nested_mapping():
    data = yamlmini.loads("a:\n  b:\n    c: 3\n  d: 4\n")
    assert data == {"a": {"b": {"c": 3}, "d": 4}}


def test_flow_sequence_and_mapping():
    data = yamlmini.loads("a: [1, 2, 3]\nb: {x: 1, y: two}\n")
    assert data == {"a": [1, 2, 3], "b": {"x": 1, "y": "two"}}


def test_block_sequence_of_scalars():
    assert yamlmini.loads("a:\n  - 1\n  - 2\n") == {"a": [1, 2]}


def test_block_sequence_of_mappings():
    text = "rules:\n  - id: R1\n    confirm: 2\n  - {id: R2, confirm: 3}\n"
    assert yamlmini.loads(text) == {"rules": [{"id": "R1", "confirm": 2}, {"id": "R2", "confirm": 3}]}


def test_comments_and_blank_lines():
    data = yamlmini.loads("# top\na: 1  # trailing\n\nb: 2\n")
    assert data == {"a": 1, "b": 2}


def test_quoted_strings_and_hash_inside_quotes():
    data = yamlmini.loads('a: "x # y"\nb: \'it\'\'s\'\n')
    assert data == {"a": "x # y", "b": "it's"}


def test_empty_document_is_empty_mapping():
    assert yamlmini.loads("") == {}
    assert yamlmini.loads("# only comments\n") == {}


def test_tab_indentation_rejected():
    with pytest.raises(yamlmini.YamlError):
        yamlmini.loads("\ta: 1\n")


def test_unexpected_indent_rejected():
    with pytest.raises(yamlmini.YamlError):
        yamlmini.loads("a: 1\n  b: 2\n")


def test_bad_flow_collection_rejected():
    with pytest.raises(yamlmini.YamlError):
        yamlmini.loads("a: [1, 2\n")


def test_duplicate_key_in_sequence_item_rejected():
    with pytest.raises(yamlmini.YamlError):
        yamlmini.loads("a:\n  - id: 1\n    id: 2\n")


def test_unterminated_string_rejected():
    with pytest.raises(yamlmini.YamlError):
        yamlmini.loads('a: "unterminated\n')


def test_load_from_file(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("a: [1, 2]\n", encoding="utf-8")
    assert yamlmini.load(str(path)) == {"a": [1, 2]}
