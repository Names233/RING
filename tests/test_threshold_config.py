import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_thresholds_match_eval_design():
    thresholds = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text(encoding="utf-8"))
    assert thresholds["routing"] == {"accuracy": 0.90, "macro_f1": 0.85, "chat_to_tech_rate": 0.05}
    assert thresholds["memory"] == {"hit_at_5": 0.85, "level_match": 0.70}
    assert thresholds["persona"] == {
        "max_average_score_regression": 0.5,
        "minimum_average_judge_score": 3.0,
    }


def test_evals_readme_documents_runner_commands():
    readme = (ROOT / "evals" / "README.md").read_text(encoding="utf-8")
    for command in [
        "python scripts/run_evals.py routing --baseline",
        "python scripts/run_evals.py routing --predictions",
        "python scripts/run_evals.py memory --predictions",
        "python scripts/run_evals.py persona --predictions",
        "--enforce-thresholds",
    ]:
        assert command in readme
