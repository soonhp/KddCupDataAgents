from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runner.agent_review import AgentReviewReport
from runner.semantic_review import SemanticReviewReport
from runner.verification import VerificationReport


@dataclass(slots=True)
class AttemptEvaluation:
    attempt_name: str
    failed_verification_checks: int
    failed_agent_reviews: int
    failed_semantic_checks: int
    failed_semantic_error_checks: int
    failed_semantic_warning_checks: int
    total_penalty: int


@dataclass(slots=True)
class AttemptSelection:
    selected_attempt: str
    rationale: str
    candidate_count: int
    has_retry_attempt: bool
    candidates: list[AttemptEvaluation]


@dataclass(slots=True)
class AttemptSelectionPlan:
    expected_retry_attempt_name: str
    retry_attempt_prediction_path: str
    compare_with_existing_attempts: bool
    note: str


def _failed_verification_count(report: VerificationReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


def _failed_agent_count(report: AgentReviewReport) -> int:
    return sum(1 for comment in report.comments if not comment.passed)


def _failed_semantic_count(report: SemanticReviewReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


def _failed_semantic_error_count(report: SemanticReviewReport) -> int:
    return sum(1 for check in report.checks if not check.passed and check.severity == "error")


def _failed_semantic_warning_count(report: SemanticReviewReport) -> int:
    return sum(1 for check in report.checks if not check.passed and check.severity == "warning")


def build_attempt_evaluation(
    *,
    attempt_name: str,
    verification_report: VerificationReport,
    semantic_review_report: SemanticReviewReport,
    agent_review_report: AgentReviewReport,
) -> AttemptEvaluation:
    failed_verification_checks = _failed_verification_count(verification_report)
    failed_agent_reviews = _failed_agent_count(agent_review_report)
    failed_semantic_checks = _failed_semantic_count(semantic_review_report)
    failed_semantic_error_checks = _failed_semantic_error_count(semantic_review_report)
    failed_semantic_warning_checks = _failed_semantic_warning_count(semantic_review_report)
    total_penalty = (
        (failed_verification_checks * 1000)
        + (failed_agent_reviews * 100)
        + (failed_semantic_error_checks * 10)
        + failed_semantic_warning_checks
    )
    return AttemptEvaluation(
        attempt_name=attempt_name,
        failed_verification_checks=failed_verification_checks,
        failed_agent_reviews=failed_agent_reviews,
        failed_semantic_checks=failed_semantic_checks,
        failed_semantic_error_checks=failed_semantic_error_checks,
        failed_semantic_warning_checks=failed_semantic_warning_checks,
        total_penalty=total_penalty,
    )


def build_attempt_selection_plan(*, retry_attempt_prediction_path: str) -> AttemptSelectionPlan:
    return AttemptSelectionPlan(
        expected_retry_attempt_name="retry",
        retry_attempt_prediction_path=retry_attempt_prediction_path,
        compare_with_existing_attempts=True,
        note="When retry execution produces a prediction file, compare original/post_repair/retry with the same deterministic selector.",
    )


def _attempt_sort_key(item: AttemptEvaluation) -> tuple[int, int, int, int, int, str]:
    return (
        item.failed_verification_checks,
        item.failed_agent_reviews,
        item.failed_semantic_error_checks,
        item.failed_semantic_warning_checks,
        item.total_penalty,
        item.attempt_name,
    )


def _build_rationale(ordered: list[AttemptEvaluation]) -> str:
    winner = ordered[0]
    winner_tuple = (
        winner.failed_verification_checks,
        winner.failed_agent_reviews,
        winner.failed_semantic_error_checks,
        winner.failed_semantic_warning_checks,
    )
    if len(ordered) == 1:
        return (
            f"selected {winner.attempt_name} as the only attempt with failure tuple "
            f"(verification={winner_tuple[0]}, agent={winner_tuple[1]}, semantic_error={winner_tuple[2]}, semantic_warning={winner_tuple[3]})"
        )

    runner_up = ordered[1]
    runner_up_tuple = (
        runner_up.failed_verification_checks,
        runner_up.failed_agent_reviews,
        runner_up.failed_semantic_error_checks,
        runner_up.failed_semantic_warning_checks,
    )
    return (
        f"selected {winner.attempt_name} over {runner_up.attempt_name}; "
        f"winner tuple=(verification={winner_tuple[0]}, agent={winner_tuple[1]}, "
        f"semantic_error={winner_tuple[2]}, semantic_warning={winner_tuple[3]}) vs "
        f"runner_up tuple=(verification={runner_up_tuple[0]}, agent={runner_up_tuple[1]}, "
        f"semantic_error={runner_up_tuple[2]}, semantic_warning={runner_up_tuple[3]})"
    )


def select_best_attempt(*evaluations: AttemptEvaluation) -> AttemptSelection:
    if not evaluations:
        raise ValueError("at least one attempt evaluation is required")

    ordered = sorted(evaluations, key=_attempt_sort_key)
    winner = ordered[0]
    has_retry_attempt = any(item.attempt_name == "retry" for item in ordered)
    rationale = _build_rationale(list(ordered))
    return AttemptSelection(
        selected_attempt=winner.attempt_name,
        rationale=rationale,
        candidate_count=len(ordered),
        has_retry_attempt=has_retry_attempt,
        candidates=list(ordered),
    )


def attempt_selection_to_dict(selection: AttemptSelection) -> dict[str, Any]:
    return asdict(selection)


def attempt_selection_plan_to_dict(plan: AttemptSelectionPlan) -> dict[str, Any]:
    return asdict(plan)
