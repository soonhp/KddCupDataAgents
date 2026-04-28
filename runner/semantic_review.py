from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runner.verification import VerificationReport

NUMERIC_QUESTION_SIGNALS = {
    "count",
    "sum",
    "average",
    "avg",
    "median",
    "variance",
    "correlation",
    "rank",
    "top",
    "total",
    "calculate",
    "compute",
}
COMPARISON_SIGNALS = {"compare", "trend", "distribution", "time series", "by", "per", "group"}
DOCUMENT_SIGNALS = {"according to", "policy", "definition", "define", "rule", "manual", "guideline", "explain"}


@dataclass(slots=True)
class SemanticReviewCheck:
    name: str
    passed: bool
    severity: str
    detail: str


@dataclass(slots=True)
class SemanticReviewReport:
    task_id: str
    all_passed: bool
    checks: list[SemanticReviewCheck]
    repair_recommendations: list[str]


def _check(name: str, passed: bool, severity: str, detail: str) -> SemanticReviewCheck:
    return SemanticReviewCheck(name=name, passed=passed, severity=severity, detail=detail)


def _get_attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _signals(task_profile: Any, key: str) -> list[str]:
    question_signals = _get_attr_or_key(task_profile, "question_signals", None) or {}
    values = question_signals.get(key, []) if isinstance(question_signals, dict) else []
    return [str(value).lower() for value in values]


def _safe_read_prediction(path: Path) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _non_empty_cells(rows: list[list[str]]) -> list[str]:
    return [cell.strip() for row in rows[1:] for cell in row if cell.strip()]


def _numeric_cell_ratio(cells: list[str]) -> float:
    if not cells:
        return 0.0
    numeric_count = 0
    for cell in cells:
        normalized = cell.replace(",", "").replace("%", "")
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
            numeric_count += 1
    return numeric_count / len(cells)


def _row_count(rows: list[list[str]]) -> int:
    return max(len(rows) - 1, 0)


def _verification_failed_names(verification_report: VerificationReport) -> list[str]:
    return [check.name for check in verification_report.checks if not check.passed]


def run_semantic_review(
    *,
    task_id: str,
    task_profile: Any,
    route_decision: Any,
    verification_report: VerificationReport,
    prediction_path: Path,
) -> SemanticReviewReport:
    """Run deterministic semantic sanity checks and produce repair hints.

    This is intentionally offline and conservative. It does not claim semantic
    correctness. It detects likely answer-shape/intent mismatches that should be
    repaired or escalated to a stronger solver/verifier loop.
    """

    checks: list[SemanticReviewCheck] = []
    recommendations: list[str] = []
    rows = _safe_read_prediction(prediction_path)
    cells = _non_empty_cells(rows)
    route = str(_get_attr_or_key(route_decision, "route", ""))
    sql_signals = _signals(task_profile, "sql")
    python_signals = _signals(task_profile, "python")
    document_signals = _signals(task_profile, "document")
    all_signals = set(sql_signals + python_signals + document_signals)

    failed_verification = _verification_failed_names(verification_report)
    verification_ok = verification_report.all_passed
    checks.append(
        _check(
            "verification_gate",
            passed=verification_ok,
            severity="error" if not verification_ok else "info",
            detail=(
                "verification failed before semantic review: " + ", ".join(failed_verification)
                if failed_verification
                else "verification passed before semantic review"
            ),
        )
    )
    if failed_verification:
        recommendations.append("repair prediction.csv contract/sanity failures before semantic validation")

    if any(signal in all_signals for signal in NUMERIC_QUESTION_SIGNALS):
        ratio = _numeric_cell_ratio(cells)
        passed = bool(cells) and ratio > 0.0
        checks.append(
            _check(
                "numeric_intent_check",
                passed=passed,
                severity="warning" if not passed else "info",
                detail=f"numeric cell ratio={ratio:.2%}; non_empty_cells={len(cells)}",
            )
        )
        if not passed:
            recommendations.append("numeric question intent detected; recompute answer with SQL/Python and emit numeric evidence")

    if any(signal in all_signals for signal in COMPARISON_SIGNALS):
        data_rows = _row_count(rows)
        passed = data_rows >= 1 and bool(cells)
        checks.append(
            _check(
                "comparative_answer_shape_check",
                passed=passed,
                severity="warning" if not passed else "info",
                detail=f"data_rows={data_rows}; non_empty_cells={len(cells)}; route={route}",
            )
        )
        if not passed:
            recommendations.append("comparative/grouped question detected; regenerate a non-empty tabular comparison")

    if any(signal in all_signals for signal in DOCUMENT_SIGNALS):
        doc_context_count = len(_get_attr_or_key(task_profile, "doc_files", []) or []) + len(
            _get_attr_or_key(task_profile, "knowledge_files", []) or []
        )
        passed = doc_context_count > 0
        checks.append(
            _check(
                "document_grounding_check",
                passed=passed,
                severity="warning" if not passed else "info",
                detail=f"document_signals={document_signals}; doc_context_count={doc_context_count}",
            )
        )
        if not passed:
            recommendations.append("document-style question detected without document context; inspect task packaging or fallback source")

    if route.startswith("hybrid"):
        recommended_tools = list(_get_attr_or_key(route_decision, "recommended_tools", []) or [])
        passed = len(recommended_tools) >= 2
        checks.append(
            _check(
                "hybrid_route_tool_check",
                passed=passed,
                severity="warning" if not passed else "info",
                detail=f"route={route}; recommended_tools={recommended_tools}",
            )
        )
        if not passed:
            recommendations.append("hybrid route selected; include both retrieval/profiling and computation tools in next solver pass")

    if len(checks) == 1:
        checks.append(_check("semantic_signal_check", True, "info", "no high-risk semantic signal detected"))

    all_passed = all(check.passed or check.severity == "warning" for check in checks)
    return SemanticReviewReport(
        task_id=task_id,
        all_passed=all_passed,
        checks=checks,
        repair_recommendations=recommendations,
    )


def semantic_review_report_to_dict(report: SemanticReviewReport) -> dict:
    return asdict(report)
