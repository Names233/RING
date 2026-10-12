import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "tests" / "schemas"

try:
    import jsonschema
except ImportError:  # pragma: no cover - CI installs it via acp-bridge dev deps
    jsonschema = None


@pytest.mark.skipif(jsonschema is None, reason="jsonschema is not installed")
@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
        ("persona-provider.schema.json", "persona-provider-request.json"),
        ("persona-provider-response.schema.json", "persona-provider-response.json"),
    ],
)
def test_schema_examples_are_valid(schema_name, example_name):
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    example = json.loads((EXAMPLES / example_name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(example)


def test_response_contract_invariants_are_documented():
    contract = (ROOT / "docs" / "PERSONA_PROVIDER_CONTRACT.md").read_text(encoding="utf-8")
    for invariant in ["P1", "P2", "P3", "P4", "P5"]:
        assert invariant in contract


def test_permission_matrix_covers_all_agents():
    matrix = (ROOT / "docs" / "OPENVIKING_PERMISSION_MATRIX.md").read_text(encoding="utf-8")
    for agent in ["AstrBot", "MaiBot", "AIRI", "dsh", "Bridge"]:
        assert agent in matrix
    for namespace in ["resources/", "memories/users/", "memories/shared/", "skills/"]:
        assert namespace in matrix
