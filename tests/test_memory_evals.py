import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "memory" / "cases.jsonl"
VALID_LEVELS = {"L0", "L1", "L2"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_memory_cases_are_valid():
    cases = load_jsonl(CASES)
    assert len(cases) >= 20

    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "memory case ids must be unique"

    for case in cases:
        assert case["query"].strip(), case
        assert case["expected_uris"], case
        assert all(uri.startswith("viking://") for uri in case["expected_uris"]), case
        assert case["expected_level"] in VALID_LEVELS, case


def test_memory_cases_cover_namespace_types():
    cases = load_jsonl(CASES)
    all_uris = [uri for case in cases for uri in case["expected_uris"]]
    for namespace in ["memories/users/", "memories/agents/", "memories/shared/", "resources/", "skills/"]:
        assert any(namespace in uri for uri in all_uris), namespace


def test_memory_cases_cover_difficulty_levels():
    cases = load_jsonl(CASES)
    difficulties = {case["difficulty"] for case in cases}
    assert {"easy", "medium", "hard"}.issubset(difficulties)


def test_memory_cases_are_l0_first():
    """Directory summary cases should prefer L0, mirroring OpenViking progressive context."""
    cases = load_jsonl(CASES)
    l0_cases = [case for case in cases if case["expected_level"] == "L0"]
    assert len(l0_cases) >= 12
    assert all(
        case["expected_uris"][0].endswith("/")
        or any(part in case["expected_uris"][0] for part in ("/docs", "/code", "/config", "/evals"))
        for case in l0_cases
    ), "L0 cases should target directories or generated summaries"
