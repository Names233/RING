#!/usr/bin/env python3
"""Migrate MemPalace memories into OpenViking-compatible Markdown trees.

Input can be a JSON array or a JSONL file. Each record must contain:
- id (required)
- content (required)
- type (optional: preference, fact, episode, relationship; default: fact)
- user_id (optional; when present goes to users/, otherwise agents/shared/)
- created_at (optional ISO-8601 timestamp)

The script is storage-agnostic: write the emitted tree to any filesystem backed
by OpenViking ragfs, or feed the emitted Markdown files through an OpenViking
import API.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

VALID_TYPES = {"preference", "fact", "episode", "relationship"}
_SAFE = re.compile(r"[^a-z0-9._-]+")


def slugify(value: str) -> str:
    slug = _SAFE.sub("-", value.strip().lower()).strip("-.")
    return slug[:80] or "record"


def parse_timestamp(value: Any) -> str:
    if not value:
        return "unknown"
    text = str(value)
    return text.replace(":", "-").replace("+", "-")


def iter_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        first = fh.read(1)
        fh.seek(0)
        if first == "[":
            loaded = json.load(fh)
            if not isinstance(loaded, list):
                raise ValueError("JSON input must be an array of records")
            records = loaded
        else:
            records = [json.loads(line) for line in fh if line.strip()]

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} is not an object")
        if not record.get("id"):
            raise ValueError(f"record {index} missing id")
        if not record.get("content"):
            raise ValueError(f"record {index} missing content")
    return records


def front_matter(record: dict[str, Any]) -> str:
    fields = [
        "id: " + json.dumps(str(record["id"]), ensure_ascii=False),
        "type: " + str(record.get("type", "fact")),
        "source: mempalace",
    ]
    if record.get("created_at"):
        fields.append("created_at: " + json.dumps(str(record["created_at"]), ensure_ascii=False))
    return "---\n" + "\n".join(fields) + "\n---\n\n"


def record_path(record: dict[str, Any]) -> Path:
    record_type = record.get("type", "fact")
    if record_type not in VALID_TYPES:
        record_type = "fact"
    user_id = record.get("user_id")
    if user_id:
        base = Path("users") / slugify(str(user_id))
        filename = f"{record_type}-{slugify(str(record['id']))}.md"
    else:
        base = Path("agents") / "shared"
        filename = f"{record_type}-{slugify(str(record['id']))}.md"
    return base / filename


def migrate(records: list[dict[str, Any]], output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in records:
        target = output / record_path(record)
        target.parent.mkdir(parents=True, exist_ok=True)
        body = str(record["content"]).strip() + "\n"
        if target.exists():
            # Keep migration idempotent: deterministic filenames + overwrite.
            existing = target.read_text(encoding="utf-8")
            if existing == front_matter(record) + body:
                continue
        target.write_text(front_matter(record) + body, encoding="utf-8")
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="MemPalace JSON array or JSONL export")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output memories/ directory (root of users/, agents/)",
    )
    args = parser.parse_args()

    records = iter_records(args.input)
    written = migrate(records, args.output)
    print(f"migrated {len(written)} new/changed records from {len(records)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
