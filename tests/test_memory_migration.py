import json
from pathlib import Path

import pytest

from scripts.migrate_mempalace_to_openviking import (
    iter_records,
    migrate,
    record_path,
)


def test_user_record_goes_to_user_namespace(tmp_path: Path):
    record = {
        "id": "mem-1",
        "user_id": "Names",
        "type": "preference",
        "content": "Likes concise release notes.",
        "created_at": "2026-10-12T08:00:00Z",
    }
    written = migrate([record], tmp_path)
    target = tmp_path / "users" / "names" / "preference-mem-1.md"
    assert written == [target]
    content = target.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert 'id: "mem-1"' in content
    assert "type: preference" in content
    assert "source: mempalace" in content
    assert "Likes concise release notes." in content


def test_shared_record_is_idempotent(tmp_path: Path):
    record = {"id": "mem-2", "content": "Deployed v3 architecture."}
    first = migrate([record], tmp_path)
    second = migrate([record], tmp_path)
    assert first and not second


def test_jsonl_and_json_array_are_supported(tmp_path: Path):
    jsonl = tmp_path / "records.jsonl"
    jsonl.write_text(
        json.dumps({"id": "a", "content": "A"}) + "\n" + json.dumps({"id": "b", "content": "B"}),
        encoding="utf-8",
    )
    assert [r["id"] for r in iter_records(jsonl)] == ["a", "b"]

    array = tmp_path / "records.json"
    array.write_text(json.dumps([{"id": "c", "content": "C"}]), encoding="utf-8")
    assert [r["id"] for r in iter_records(array)] == ["c"]


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"id": "x", "content": "c", "type": "fact"}, Path("agents/shared/fact-x.md")),
        ({"id": "x", "content": "c", "type": "unknown"}, Path("agents/shared/fact-x.md")),
        (
            {"id": "x", "content": "c", "user_id": "u", "type": "episode"},
            Path("users/u/episode-x.md"),
        ),
    ],
)
def test_record_path_rules(record, expected):
    assert record_path(record) == expected


def test_invalid_records_are_rejected(tmp_path: Path):
    source = tmp_path / "bad.json"
    source.write_text(json.dumps([{"id": "", "content": "missing id"}]), encoding="utf-8")
    try:
        iter_records(source)
    except ValueError as exc:
        assert "missing id" in str(exc)
    else:
        raise AssertionError("expected ValueError")
