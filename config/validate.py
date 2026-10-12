#!/usr/bin/env python3
"""Validate Digital Genesis configuration files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_LITELLM_MODELS = {
    "persona-chat",
    "persona-trigger",
    "coding-primary",
    "coding-fallback",
    "intent-router",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = yaml.safe_load(fh)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def validate_litellm(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    models = config.get("model_list", [])
    names = {item.get("model_name") for item in models if isinstance(item, dict)}

    missing = REQUIRED_LITELLM_MODELS - names
    if missing:
        errors.append(f"litellm model_list missing: {sorted(missing)}")

    for item in models:
        if not isinstance(item, dict):
            errors.append("litellm model_list contains a non-object entry")
            continue
        name = item.get("model_name")
        params = item.get("litellm_params", {})
        if not name or not isinstance(name, str):
            errors.append("litellm model entry requires a string model_name")
        if not isinstance(params, dict) or not params.get("model"):
            errors.append(f"model {name}: litellm_params.model is required")

    fallbacks = config.get("router_settings", {}).get("fallbacks", [])
    flat = [pair for entry in fallbacks if isinstance(entry, dict) for pair in entry.items()]
    for source, targets in flat:
        if source not in names:
            errors.append(f"fallback source is not declared: {source}")
        for target in targets or []:
            if target not in names:
                errors.append(f"fallback target is not declared: {target}")
    return errors


def validate_soul(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section in ("persona", "perception", "execution", "memory", "model_gateway"):
        if section not in config:
            errors.append(f"soul.yaml missing section: {section}")

    routing = config.get("perception", {}).get("routing", {})
    expected_routes = {"chat", "tech", "embodiment"}
    missing_routes = expected_routes - set(routing)
    if missing_routes:
        errors.append(f"perception.routing missing: {sorted(missing_routes)}")

    namespaces = config.get("memory", {}).get("namespaces", {})
    for namespace in ("resources", "memories", "skills"):
        if namespace not in namespaces:
            errors.append(f"memory.namespaces missing: {namespace}")

    viking_re = re.compile(r"^viking://")

    def check_namespace(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                check_namespace(f"{prefix}.{child_key}", child_value)
        elif not isinstance(value, str) or not viking_re.match(value):
            errors.append(f"memory namespace {prefix} is not a viking:// URI: {value}")

    for key, value in namespaces.items():
        check_namespace(str(key), value)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root

    checks: list[tuple[Path, Any, Any]] = [
        (root / "config" / "litellm.yaml", validate_litellm, None),
    ]
    checks.append((root / "config" / "soul.example.yaml", validate_soul, None))

    failures = 0
    for path, validator, _ in checks:
        if not path.exists():
            print(f"FAIL {path.relative_to(root)}: file is missing")
            failures += 1
            continue
        try:
            errors = validator(load_yaml(path))
        except Exception as exc:
            print(f"FAIL {path.relative_to(root)}: {exc}")
            failures += 1
            continue
        if errors:
            failures += 1
            for error in errors:
                print(f"FAIL {path.relative_to(root)}: {error}")
        else:
            print(f"PASS {path.relative_to(root)}")

    if failures:
        print(f"{failures} configuration check(s) failed")
        return 1
    print("All configuration checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())


