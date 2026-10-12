"""Offline evaluation runner for routing, memory, and persona eval sets.

The runner is intentionally model-free: it consumes prediction JSONL files and
produces deterministic metric reports. Model calls are out of scope so CI can
always execute the offline portion.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS = REPO_ROOT / "evals" / "thresholds.yaml"
DEFAULT_CASES = {
    "routing": REPO_ROOT / "evals" / "routing" / "cases.jsonl",
    "memory": REPO_ROOT / "evals" / "memory" / "cases.jsonl",
    "persona": REPO_ROOT / "evals" / "persona" / "cases.jsonl",
}
VALID_ROUTES = {"chat", "tech", "embodiment"}
VALID_LEVELS = {"L0", "L1", "L2"}


class EvalError(RuntimeError):
    """Raised for malformed cases, predictions, or configuration."""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvalError(f"JSONL file not found: {path}")

    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise EvalError(f"{path}:{line_number}: expected a JSON object")
        cases.append(value)
    return cases


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> dict[str, dict[str, float]]:
    if not path.is_file():
        raise EvalError(f"threshold file not found: {path}")
    thresholds = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(thresholds, dict):
        raise EvalError("threshold file must contain a mapping")
    for kind in ("routing", "memory", "persona"):
        if kind not in thresholds or not isinstance(thresholds[kind], dict):
            raise EvalError(f"threshold file missing `{kind}` section")
    return thresholds


def _require_unique_ids(cases: Iterable[dict[str, Any]]) -> list[str]:
    ids = [case["id"] for case in cases if "id" in case]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise EvalError(f"duplicate case ids: {duplicates}")
    if len(ids) != len(list(cases)):
        raise EvalError("every case must contain an id")
    return ids


def baseline_route(text: str) -> str:
    """Deterministic router used as the offline regression baseline.

    Delegates to the shared astrbot_router package so the eval baseline and
    the deployed degraded path cannot drift apart.
    """
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from astrbot_router.core import rule_classify

    return rule_classify(text).route


def generate_routing_predictions(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": case["id"], "route": baseline_route(case["text"])} for case in cases]


def macro_f1(actual: list[str], predicted: list[str], labels: set[str] | None = None) -> float:
    if len(actual) != len(predicted):
        raise EvalError("actual and predicted labels must have equal length")
    labels = labels or set(actual) | set(predicted)
    if not labels:
        return 0.0

    scores: list[float] = []
    for label in labels:
        tp = sum(1 for expected, got in zip(actual, predicted) if expected == label and got == label)
        fp = sum(1 for expected, got in zip(actual, predicted) if expected != label and got == label)
        fn = sum(1 for expected, got in zip(actual, predicted) if expected == label and got != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(f1)
    return sum(scores) / len(scores)


def evaluate_routing(
    cases: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    _require_unique_ids(cases)
    prediction_by_id = _index_by_id(predictions, "predictions")
    actual: list[str] = []
    predicted: list[str] = []
    badcases: list[dict[str, str]] = []

    for case in cases:
        prediction = prediction_by_id[case["id"]]
        route = prediction.get("route", prediction.get("predicted_route"))
        if route not in VALID_ROUTES:
            raise EvalError(f"{case['id']}: invalid predicted route: {route!r}")
        actual.append(case["expected_route"])
        predicted.append(str(route))
        if route != case["expected_route"]:
            badcases.append(
                {
                    "id": case["id"],
                    "text": case["text"],
                    "expected": case["expected_route"],
                    "predicted": str(route),
                }
            )

    confusion = Counter(zip(actual, predicted))
    chat_to_tech = confusion[("chat", "tech")] / actual.count("chat") if actual.count("chat") else 0.0
    return {
        "kind": "routing",
        "case_count": len(cases),
        "accuracy": sum(1 for expected, got in zip(actual, predicted) if expected == got) / len(actual) if actual else 0.0,
        "macro_f1": macro_f1(actual, predicted, VALID_ROUTES),
        "chat_to_tech_rate": chat_to_tech,
        "confusion_matrix": {f"{left}->{right}": count for (left, right), count in sorted(confusion.items())},
        "badcases": badcases,
    }


def evaluate_memory(
    cases: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    _require_unique_ids(cases)
    prediction_by_id = _index_by_id(predictions, "predictions")
    hit_at_1 = 0
    hit_at_5 = 0
    reciprocal_ranks: list[float] = []
    level_matches = 0
    badcases: list[dict[str, Any]] = []

    for case in cases:
        prediction = prediction_by_id[case["id"]]
        retrieved = prediction.get("retrieved", [])
        if not isinstance(retrieved, list):
            raise EvalError(f"{case['id']}: `retrieved` must be a list")
        if len(retrieved) > 5:
            raise EvalError(f"{case['id']}: at most 5 retrieved items are allowed")

        ranks: list[int] = []
        for rank, item in enumerate(retrieved, start=1):
            if not isinstance(item, dict) or "uri" not in item:
                raise EvalError(f"{case['id']}: retrieved item {rank} must contain `uri`")
            level = item.get("level")
            if level is not None and level not in VALID_LEVELS:
                raise EvalError(f"{case['id']}: invalid retrieved level: {level!r}")
            if any(item["uri"] == expected or item["uri"].rstrip("/") == expected.rstrip("/") for expected in case["expected_uris"]):
                ranks.append(rank)

        if ranks:
            first_rank = min(ranks)
            reciprocal_ranks.append(1 / first_rank)
            if first_rank == 1:
                hit_at_1 += 1
            if first_rank <= 5:
                hit_at_5 += 1
            top_level = retrieved[first_rank - 1].get("level")
            if top_level == case["expected_level"]:
                level_matches += 1
            else:
                badcases.append({"id": case["id"], "reason": "level_mismatch", "expected_level": case["expected_level"], "retrieved_level": top_level})
        else:
            reciprocal_ranks.append(0.0)
            badcases.append({"id": case["id"], "reason": "no_expected_uri_in_results", "expected_uris": case["expected_uris"]})

    count = len(cases)
    return {
        "kind": "memory",
        "case_count": count,
        "hit_at_1": hit_at_1 / count if count else 0.0,
        "hit_at_5": hit_at_5 / count if count else 0.0,
        "mrr": sum(reciprocal_ranks) / count if count else 0.0,
        "level_match": level_matches / count if count else 0.0,
        "badcases": badcases,
    }


def evaluate_persona(
    cases: list[dict[str, Any]], responses: list[dict[str, Any]]
) -> dict[str, Any]:
    _require_unique_ids(cases)
    response_by_id = _index_by_id(responses, "responses")
    invalid: list[dict[str, Any]] = []

    for case in cases:
        response = response_by_id[case["id"]].get("response", response_by_id[case["id"]])
        text = response.get("text", "")
        should_reply = response.get("should_reply", True)
        violations: list[str] = []

        if not should_reply and text:
            violations.append("P1: should_reply=false but text is non-empty")
        if response.get("emotion") not in {"neutral", "happy", "excited", "sad", "angry", "thinking", "shy", "sleepy"}:
            violations.append("P2: invalid emotion")
        for term in case.get("forbidden", []):
            if term and term in text:
                violations.append(f"forbidden term: {term}")
        if violations:
            invalid.append({"id": case["id"], "violations": violations})

    judge_scores = [
        float(item["judge_score"])
        for item in responses
        if item.get("judge_score") is not None and not math.isnan(float(item["judge_score"]))
    ]
    return {
        "kind": "persona",
        "case_count": len(cases),
        "rule_violation_rate": len(invalid) / len(cases) if cases else 0.0,
        "rule_pass_rate": 1 - (len(invalid) / len(cases) if cases else 0.0),
        "judge_score_count": len(judge_scores),
        "average_judge_score": sum(judge_scores) / len(judge_scores) if judge_scores else None,
        "invalid": invalid,
    }


def _index_by_id(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if "id" not in item:
            raise EvalError(f"every {label} entry must contain an id")
        if item["id"] in result:
            raise EvalError(f"duplicate {label} id: {item['id']}")
        result[item["id"]] = item
    return result


def enforce_thresholds(report: dict[str, Any], thresholds: dict[str, dict[str, float]]) -> list[str]:
    failures: list[str] = []
    if report["kind"] == "routing":
        if report["accuracy"] < thresholds["routing"]["accuracy"]:
            failures.append(f"accuracy {report['accuracy']:.3f} < {thresholds['routing']['accuracy']:.3f}")
        if report["macro_f1"] < thresholds["routing"]["macro_f1"]:
            failures.append(f"macro_f1 {report['macro_f1']:.3f} < {thresholds['routing']['macro_f1']:.3f}")
        if report["chat_to_tech_rate"] > thresholds["routing"]["chat_to_tech_rate"]:
            failures.append(f"chat_to_tech_rate {report['chat_to_tech_rate']:.3f} > {thresholds['routing']['chat_to_tech_rate']:.3f}")
    elif report["kind"] == "memory":
        if report["hit_at_5"] < thresholds["memory"]["hit_at_5"]:
            failures.append(f"hit_at_5 {report['hit_at_5']:.3f} < {thresholds['memory']['hit_at_5']:.3f}")
        if report["level_match"] < thresholds["memory"]["level_match"]:
            failures.append(f"level_match {report['level_match']:.3f} < {thresholds['memory']['level_match']:.3f}")
    elif report["kind"] == "persona":
        if report["rule_violation_rate"] > 0:
            failures.append(f"rule_violation_rate {report['rule_violation_rate']:.3f} > 0")
        if report["average_judge_score"] is not None and report["average_judge_score"] < thresholds["persona"]["minimum_average_judge_score"]:
            failures.append(
                f"average_judge_score {report['average_judge_score']:.3f} < {thresholds['persona']['minimum_average_judge_score']:.3f}"
            )
    return failures


def render_markdown(report: dict[str, Any], threshold_failures: list[str]) -> str:
    kind = report["kind"]
    lines = [f"# {kind.capitalize()} eval report", "", f"- cases: {report['case_count']}"]
    for key, value in report.items():
        if key in {"kind", "case_count", "badcases", "invalid", "confusion_matrix"}:
            continue
        rendered = "pending" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(f"- {key}: {rendered}")
    if "confusion_matrix" in report:
        lines += ["", "## Confusion matrix", ""]
        lines += [f"- {pair}: {count}" for pair, count in report["confusion_matrix"].items()]
    for list_key, title in (("badcases", "Badcases"), ("invalid", "Rule violations")):
        items = report.get(list_key, [])
        if items:
            lines += ["", f"## {title}", ""]
            lines += [f"- `{item['id']}`: {json.dumps(item, ensure_ascii=False, sort_keys=True)}" for item in items]
    lines += ["", "## Threshold gate", ""]
    if threshold_failures:
        lines += [f"- ❌ {failure}" for failure in threshold_failures]
    else:
        lines.append("- ✅ all thresholds passed")
    return "\n".join(lines) + "\n"


def run_all(args: argparse.Namespace) -> int:
    """Run routing baseline plus any memory/persona dimensions with prediction files."""
    threshold_failures: list[str] = []
    report_outputs: list[str] = []

    routing_cases = load_jsonl(args.cases or DEFAULT_CASES["routing"])
    routing_predictions = (
        generate_routing_predictions(routing_cases)
        if args.baseline or not args.predictions
        else load_jsonl(args.predictions)
    )
    routing_report = evaluate_routing(routing_cases, routing_predictions)
    thresholds = load_thresholds(args.thresholds)
    failures = enforce_thresholds(routing_report, thresholds)
    rendered = render_markdown(routing_report, failures)
    report_outputs.append(rendered)
    threshold_failures.extend(f"routing: {failure}" for failure in failures)

    for kind in ("memory", "persona"):
        candidate_paths: list[Path] = []
        if args.predictions:
            candidate_paths.append(Path(args.predictions))
        if args.output:
            candidate_paths.append(args.output.with_suffix(f".{kind}.jsonl"))
        candidate_paths.append(DEFAULT_CASES[kind].with_name("predictions.jsonl"))
        prediction_path = next((path for path in candidate_paths if path.is_file()), None)
        if prediction_path is None:
            report_outputs.append(f"# {kind.capitalize()} eval report\n\n- status: skipped (no prediction file)\n")
            continue
        cases = load_jsonl(DEFAULT_CASES[kind])
        predictions = load_jsonl(prediction_path)
        if {item["id"] for item in predictions} != {case["id"] for case in cases}:
            report_outputs.append(f"# {kind.capitalize()} eval report\n\n- status: skipped (prediction ids do not match cases)\n")
            continue
        report = evaluate_memory(cases, predictions) if kind == "memory" else evaluate_persona(cases, predictions)
        failures = enforce_thresholds(report, thresholds)
        rendered = render_markdown(report, failures)
        report_outputs.append(rendered)
        threshold_failures.extend(f"{kind}: {failure}" for failure in failures)

    combined = "# Digital Genesis eval report\n\n" + "\n---\n\n".join(report_outputs)
    rendered = json.dumps({"routing": routing_report}, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else combined
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    if threshold_failures:
        print("threshold failures:", file=sys.stderr)
        for failure in threshold_failures:
            print(f"- {failure}", file=sys.stderr)
    return 1 if threshold_failures and args.enforce_thresholds else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline Digital Genesis eval sets")
    parser.add_argument(
        "kind",
        nargs="?",
        choices=(*sorted(DEFAULT_CASES), "all"),
        help="eval dimension; `all` runs every dimension with an available prediction source",
    )
    parser.add_argument("--cases", type=Path, help="case JSONL path (defaults to evals/<kind>/cases.jsonl)")
    parser.add_argument("--predictions", type=Path, help="prediction JSONL path")
    parser.add_argument("--baseline", action="store_true", help="use the deterministic routing baseline")
    parser.add_argument("--output", type=Path, help="report output path; defaults to stdout")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS, help="threshold YAML path")
    parser.add_argument("--enforce-thresholds", action="store_true", help="exit non-zero when a threshold fails")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often default to a legacy code page; keep reports deterministic.
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in {"utf-8", "utf8"}:
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding and sys.stderr.encoding.lower() not in {"utf-8", "utf8"}:
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.kind == "all":
        return run_all(args)
    cases_path = args.cases or DEFAULT_CASES[args.kind]
    cases = load_jsonl(cases_path)

    if args.kind == "routing" and args.baseline:
        if args.predictions:
            raise EvalError("--baseline and --predictions are mutually exclusive")
        predictions = generate_routing_predictions(cases)
    else:
        if not args.predictions:
            raise EvalError(f"--predictions is required for {args.kind} (routing may use --baseline)")
        predictions = load_jsonl(args.predictions)

    if args.kind == "routing":
        report = evaluate_routing(cases, predictions)
    elif args.kind == "memory":
        report = evaluate_memory(cases, predictions)
    else:
        report = evaluate_persona(cases, predictions)

    thresholds = load_thresholds(args.thresholds)
    failures = enforce_thresholds(report, thresholds)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_markdown(report, failures)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    if failures:
        print("threshold failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    return 1 if failures and args.enforce_thresholds else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
