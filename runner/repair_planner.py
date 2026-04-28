from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runner.agent_review import AgentReviewReport
from runner.semantic_review import SemanticReviewReport
from runner.verification import VerificationReport


@dataclass(slots=True)
class RepairAction:
    priority: int
    action_type: str
    owner_agent: str
    detail: str
    blocking: bool


@dataclass(slots=True)
class RepairPlan:
    task_id: str
    should_repair: bool
    actions: list[RepairAction]
    summary: str


def _action(priority: int, action_type: str, owner_agent: str, detail: str, blocking: bool) -> RepairAction:
    return RepairAction(
        priority=priority,
        action_type=action_type,
        owner_agent=owner_agent,
        detail=detail,
        blocking=blocking,
    )


def _get_attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _failed_verification_checks(report: VerificationReport) -> list[str]:
    return [check.name for check in report.checks if not check.passed]


def _failed_agent_comments(report: AgentReviewReport) -> list[tuple[str, str]]:
    return [(comment.agent, comment.detail) for comment in report.comments if not comment.passed]


def _failed_semantic_checks(report: SemanticReviewReport) -> list[tuple[str, str, str]]:
    return [(check.name, check.severity, check.detail) for check in report.checks if not check.passed]


def build_repair_plan(
    *,
    task_id: str,
    route_decision: Any,
    verification_report: VerificationReport,
    semantic_review_report: SemanticReviewReport,
    agent_review_report: AgentReviewReport,
) -> RepairPlan:
    """Create an ordered deterministic repair plan from reviewer outputs.

    The plan is intentionally executable as instructions for a next solver pass.
    It does not mutate predictions by itself.
    """

    actions: list[RepairAction] = []
    route = str(_get_attr_or_key(route_decision, "route", "unknown"))
    recommended_tools = list(_get_attr_or_key(route_decision, "recommended_tools", []) or [])
    risk_flags = list(_get_attr_or_key(route_decision, "risk_flags", []) or [])

    failed_verification = _failed_verification_checks(verification_report)
    if failed_verification:
        actions.append(
            _action(
                10,
                "fix_output_contract",
                "Verifier Agent",
                "Fix prediction.csv before further semantic checks. Failed checks: " + ", ".join(failed_verification),
                True,
            )
        )

    for agent, detail in _failed_agent_comments(agent_review_report):
        owner = agent or "PM Agent"
        action_type = "resolve_agent_review_failure"
        if owner == "Answer Contract Agent":
            action_type = "fix_task_contract"
        elif owner == "Planner Agent":
            action_type = "replan_route"
        elif owner == "Data Profiling Agent":
            action_type = "refresh_schema_memory"
        elif owner == "PM Agent":
            action_type = "resolve_task_packaging_risk"
        actions.append(_action(20, action_type, owner, detail, owner != "PM Agent"))

    for check_name, severity, detail in _failed_semantic_checks(semantic_review_report):
        if check_name == "numeric_intent_check":
            actions.append(
                _action(
                    30,
                    "recompute_numeric_answer",
                    "Python Analyst Agent" if "python" in recommended_tools else "SQL Analyst Agent",
                    f"{detail}. Recompute numeric evidence using route={route} and tools={recommended_tools}",
                    severity == "error",
                )
            )
        elif check_name == "comparative_answer_shape_check":
            actions.append(
                _action(
                    31,
                    "regenerate_tabular_comparison",
                    "Python Analyst Agent",
                    f"{detail}. Produce a non-empty grouped/comparative prediction table.",
                    severity == "error",
                )
            )
        elif check_name == "document_grounding_check":
            actions.append(
                _action(
                    32,
                    "restore_document_grounding",
                    "Doc Reasoning Agent",
                    f"{detail}. Re-inspect task context and cite/reason from available document or flag packaging issue.",
                    severity == "error",
                )
            )
        elif check_name == "hybrid_route_tool_check":
            actions.append(
                _action(
                    33,
                    "expand_hybrid_tool_plan",
                    "Planner Agent",
                    f"{detail}. Add both retrieval/profiling and compute tools for next pass.",
                    severity == "error",
                )
            )
        elif check_name == "verification_gate":
            continue
        else:
            actions.append(_action(39, "inspect_semantic_warning", "Verifier Agent", detail, severity == "error"))

    for recommendation in semantic_review_report.repair_recommendations:
        actions.append(_action(40, "apply_semantic_recommendation", "Verifier Agent", recommendation, False))

    if risk_flags:
        actions.append(
            _action(
                50,
                "review_route_risk_flags",
                "PM Agent",
                "Route risk flags: " + ", ".join(risk_flags),
                False,
            )
        )

    actions = sorted(actions, key=lambda item: (item.priority, item.action_type, item.detail))
    # De-duplicate same owner/action/detail while preserving sorted order.
    deduped: list[RepairAction] = []
    seen: set[tuple[str, str, str]] = set()
    for item in actions:
        key = (item.owner_agent, item.action_type, item.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    should_repair = bool(deduped)
    blocking_count = sum(1 for item in deduped if item.blocking)
    summary = (
        f"repair required: {len(deduped)} actions ({blocking_count} blocking)"
        if should_repair
        else "no repair required"
    )
    return RepairPlan(task_id=task_id, should_repair=should_repair, actions=deduped, summary=summary)


def repair_plan_to_dict(plan: RepairPlan) -> dict:
    return asdict(plan)
