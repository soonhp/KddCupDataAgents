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
    total_penalty: int


@dataclass(slots=True)
class AttemptSelection:
    selected_attempt: str
    rationale: str
    candidates: list[AttemptEvaluation]


def _failed_verification_count(report: VerificationReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


def _failed_agent_count(report: AgentReviewReport) -> int:
    return sum(1 for comment in report.comments if not comment.passed)


def _failed_semantic_count(report: SemanticReviewReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


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
    total_penalty = (failed_verification_checks * 100) + (failed_agent_reviews * 10) + failed_semantic_checks
    return AttemptEvaluation(
        attempt_name=attempt_name,
        failed_verification_checks=failed_verification_checks,
        failed_agent_reviews=failed_agent_reviews,
        failed_semantic_checks=failed_semantic_checks,
        total_penalty=total_penalty,
    )


def select_best_attempt(*evaluations: AttemptEvaluation) -> AttemptSelection:
    if not evaluations:
        raise ValueError("at least one attempt evaluation is required")

    ordered = sorted(
        evaluations,
        key=lambda item: (
            item.failed_verification_checks,
            item.failed_agent_reviews,
            item.failed_semantic_checks,
            item.total_penalty,
            item.attempt_name,
        ),
    )
    winner = ordered[0]
    rationale = (
        f"selected {winner.attempt_name} with failure tuple "
        f"({winner.failed_verification_checks}, {winner.failed_agent_reviews}, {winner.failed_semantic_checks})"
    )
    return AttemptSelection(selected_attempt=winner.attempt_name, rationale=rationale, candidates=list(ordered))


def attempt_selection_to_dict(selection: AttemptSelection) -> dict[str, Any]:
    return asdict(selection)
