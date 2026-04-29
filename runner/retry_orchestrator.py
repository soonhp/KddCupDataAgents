from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runner.agent_review import AgentReviewReport
from runner.repair_planner import RepairPlan
from runner.semantic_review import SemanticReviewReport
from runner.verification import VerificationReport


@dataclass(slots=True)
class RetryDecision:
    should_retry: bool
    retry_reason: str
    max_retry_count: int
    retry_instructions: list[str]


@dataclass(slots=True)
class RetryComparison:
    selected_attempt: str
    rationale: str
    original_failed_verification_checks: int
    retried_failed_verification_checks: int
    original_failed_agent_reviews: int
    retried_failed_agent_reviews: int
    original_failed_semantic_checks: int
    retried_failed_semantic_checks: int


@dataclass(slots=True)
class RetryArtifacts:
    retry_task_dir: Path
    retry_note_path: Path
    retry_plan_path: Path


RETRYABLE_ACTIONS = {
    "recompute_numeric_answer",
    "regenerate_tabular_comparison",
    "restore_document_grounding",
    "expand_hybrid_tool_plan",
    "apply_semantic_recommendation",
    "replan_route",
    "refresh_schema_memory",
}


def _get_attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _failed_verification_count(report: VerificationReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


def _failed_agent_count(report: AgentReviewReport) -> int:
    return sum(1 for comment in report.comments if not comment.passed)


def _failed_semantic_count(report: SemanticReviewReport) -> int:
    return sum(1 for check in report.checks if not check.passed)


def build_retry_decision(
    *,
    repair_plan: RepairPlan,
    verification_report: VerificationReport,
    semantic_review_report: SemanticReviewReport,
    agent_review_report: AgentReviewReport,
) -> RetryDecision:
    retry_instructions: list[str] = []
    retryable_actions = [action for action in repair_plan.actions if action.action_type in RETRYABLE_ACTIONS]
    if retryable_actions:
        retry_instructions.extend(
            f"[{action.owner_agent}] {action.action_type}: {action.detail}" for action in retryable_actions
        )

    if not verification_report.all_passed:
        retry_instructions.append("Fix verification failures before trusting the next attempt.")
    if semantic_review_report.repair_recommendations:
        retry_instructions.extend(semantic_review_report.repair_recommendations)
    if not agent_review_report.all_passed:
        retry_instructions.append("Resolve failed subagent reviews in the next attempt.")

    should_retry = bool(retryable_actions) or (not verification_report.all_passed and bool(retry_instructions))
    retry_reason = (
        f"retryable actions detected ({len(retryable_actions)})"
        if retryable_actions
        else ("verification/agent review failures require one guided retry" if should_retry else "no retry required")
    )
    return RetryDecision(
        should_retry=should_retry,
        retry_reason=retry_reason,
        max_retry_count=1 if should_retry else 0,
        retry_instructions=retry_instructions,
    )


def prepare_retry_artifacts(
    *,
    task_dir: Path,
    retry_root: Path,
    repair_plan: RepairPlan,
    retry_decision: RetryDecision,
) -> RetryArtifacts:
    retry_task_dir = retry_root / task_dir.name
    if retry_task_dir.exists():
        shutil.rmtree(retry_task_dir)
    shutil.copytree(task_dir, retry_task_dir)

    context_dir = retry_task_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    retry_note_path = context_dir / "retry_instructions.md"
    retry_plan_path = context_dir / "retry_plan.json"

    note_lines = [
        "# Retry Instructions",
        "",
        f"Reason: {retry_decision.retry_reason}",
        "",
        "Follow these instructions for the next attempt:",
    ]
    if retry_decision.retry_instructions:
        note_lines.extend(f"- {instruction}" for instruction in retry_decision.retry_instructions)
    else:
        note_lines.append("- Re-run carefully with the original route and context.")
    retry_note_path.write_text("\n".join(note_lines) + "\n", encoding="utf-8")
    retry_plan_path.write_text(json.dumps(asdict(repair_plan), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return RetryArtifacts(
        retry_task_dir=retry_task_dir,
        retry_note_path=retry_note_path,
        retry_plan_path=retry_plan_path,
    )


def compare_attempts(
    *,
    original_verification_report: VerificationReport,
    retried_verification_report: VerificationReport,
    original_semantic_review_report: SemanticReviewReport,
    retried_semantic_review_report: SemanticReviewReport,
    original_agent_review_report: AgentReviewReport,
    retried_agent_review_report: AgentReviewReport,
) -> RetryComparison:
    original_tuple = (
        _failed_verification_count(original_verification_report),
        _failed_agent_count(original_agent_review_report),
        _failed_semantic_count(original_semantic_review_report),
    )
    retried_tuple = (
        _failed_verification_count(retried_verification_report),
        _failed_agent_count(retried_agent_review_report),
        _failed_semantic_count(retried_semantic_review_report),
    )
    if retried_tuple < original_tuple:
        selected_attempt = "retry"
        rationale = f"retry improved failure tuple from {original_tuple} to {retried_tuple}"
    else:
        selected_attempt = "original"
        rationale = f"retry did not improve failure tuple {original_tuple} -> {retried_tuple}"

    return RetryComparison(
        selected_attempt=selected_attempt,
        rationale=rationale,
        original_failed_verification_checks=original_tuple[0],
        retried_failed_verification_checks=retried_tuple[0],
        original_failed_agent_reviews=original_tuple[1],
        retried_failed_agent_reviews=retried_tuple[1],
        original_failed_semantic_checks=original_tuple[2],
        retried_failed_semantic_checks=retried_tuple[2],
    )


def retry_decision_to_dict(decision: RetryDecision) -> dict[str, Any]:
    return asdict(decision)


def retry_comparison_to_dict(comparison: RetryComparison) -> dict[str, Any]:
    return asdict(comparison)
