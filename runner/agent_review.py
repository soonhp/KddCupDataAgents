from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runner.verification import VerificationReport


@dataclass(slots=True)
class AgentReviewComment:
    agent: str
    passed: bool
    severity: str
    detail: str


@dataclass(slots=True)
class AgentReviewReport:
    task_id: str
    all_passed: bool
    comments: list[AgentReviewComment]


def _comment(agent: str, passed: bool, severity: str, detail: str) -> AgentReviewComment:
    return AgentReviewComment(agent=agent, passed=passed, severity=severity, detail=detail)


def _get_attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _verification_failed_check_names(verification_report: VerificationReport) -> list[str]:
    return [check.name for check in verification_report.checks if not check.passed]


def run_agent_review(
    *,
    task_id: str,
    task_profile: Any,
    route_decision: Any,
    verification_report: VerificationReport,
) -> AgentReviewReport:
    """Run lightweight deterministic subagent reviews over one task execution.

    This does not call external services. It records independent review viewpoints
    in the task log so the runner has an auditable PM/Planner/Data/Verifier/
    Answer Contract review loop even in offline evaluation environments.
    """

    comments: list[AgentReviewComment] = []

    risk_flags = list(_get_attr_or_key(route_decision, "risk_flags", []) or [])
    route = _get_attr_or_key(route_decision, "route", "")
    reasons = list(_get_attr_or_key(route_decision, "reasons", []) or [])
    recommended_tools = list(_get_attr_or_key(route_decision, "recommended_tools", []) or [])
    file_counts = _get_attr_or_key(task_profile, "file_counts", None) or {}
    schema_hints = _get_attr_or_key(task_profile, "schema_hints", None) or {}

    hard_risks = {
        "missing_task_json",
        "malformed_task_json",
        "missing_question",
        "missing_context_dir",
        "empty_context",
        "no_supported_context_files",
        "zero_score_route",
    }
    present_hard_risks = [flag for flag in risk_flags if flag in hard_risks]
    comments.append(
        _comment(
            "PM Agent",
            passed=not present_hard_risks,
            severity="warning" if present_hard_risks else "info",
            detail=(
                "blocking risk flags detected: " + ", ".join(present_hard_risks)
                if present_hard_risks
                else "no blocking planning risk flags detected"
            ),
        )
    )

    comments.append(
        _comment(
            "Planner Agent",
            passed=bool(route and reasons),
            severity="error" if not route or not reasons else "info",
            detail=(
                f"route={route}; reasons={len(reasons)}; tools={recommended_tools}"
                if route and reasons
                else "route decision is missing route or reasons"
            ),
        )
    )

    supported_context_count = sum(int(file_counts.get(key, 0) or 0) for key in ["csv", "db", "json", "doc", "knowledge"])
    schema_hint_count = sum(len(value) for value in schema_hints.values() if isinstance(value, list))
    comments.append(
        _comment(
            "Data Profiling Agent",
            passed=supported_context_count == 0 or schema_hint_count > 0,
            severity="warning" if supported_context_count and schema_hint_count == 0 else "info",
            detail=f"supported_context_files={supported_context_count}; schema_hint_entries={schema_hint_count}",
        )
    )

    failed_checks = _verification_failed_check_names(verification_report)
    comments.append(
        _comment(
            "Verifier Agent",
            passed=verification_report.all_passed,
            severity="error" if failed_checks else "info",
            detail=(
                "failed verification checks: " + ", ".join(failed_checks)
                if failed_checks
                else "all verification checks passed"
            ),
        )
    )

    task_contract_checks = [check for check in verification_report.checks if check.name == "task_contract_check"]
    failing_task_contract_checks = [check for check in task_contract_checks if not check.passed]
    if not task_contract_checks:
        comments.append(
            _comment(
                "Answer Contract Agent",
                passed=False,
                severity="error",
                detail="task-specific output contract check did not run",
            )
        )
    else:
        comments.append(
            _comment(
                "Answer Contract Agent",
                passed=not failing_task_contract_checks,
                severity="error" if failing_task_contract_checks else "info",
                detail=(
                    failing_task_contract_checks[0].detail
                    if failing_task_contract_checks
                    else "task-specific output contract is satisfied or explicitly unavailable"
                ),
            )
        )

    all_passed = all(comment.passed for comment in comments)
    return AgentReviewReport(task_id=task_id, all_passed=all_passed, comments=comments)


def agent_review_report_to_dict(report: AgentReviewReport) -> dict:
    return asdict(report)
