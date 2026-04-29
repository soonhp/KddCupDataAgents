from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runner.repair_executor import RepairExecutionReport
from runner.repair_planner import RepairPlan

MAX_RETRY_ATTEMPTS = 1


@dataclass(slots=True)
class RetryInstruction:
    priority: int
    owner_agent: str
    focus: str
    detail: str


@dataclass(slots=True)
class RetryDecision:
    task_id: str
    should_retry: bool
    max_retry_attempts: int
    rationale: str
    instructions: list[RetryInstruction]


def _instruction(priority: int, owner_agent: str, focus: str, detail: str) -> RetryInstruction:
    return RetryInstruction(priority=priority, owner_agent=owner_agent, focus=focus, detail=detail)


def _get_attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _focus_for_action(action_type: str) -> str:
    if action_type == "recompute_numeric_answer":
        return "numeric_recompute"
    if action_type == "regenerate_tabular_comparison":
        return "tabular_regeneration"
    if action_type == "restore_document_grounding":
        return "document_grounding"
    if action_type == "expand_hybrid_tool_plan":
        return "hybrid_tooling"
    if action_type in {"fix_output_contract", "fix_task_contract"}:
        return "output_contract"
    return "verification"


def build_retry_decision(
    *,
    task_id: str,
    route_decision: Any,
    repair_plan: RepairPlan,
    repair_execution_report: RepairExecutionReport,
) -> RetryDecision:
    """Create a deterministic retry decision for a next solver pass.

    This executor does not call the model again directly. It converts unresolved
    repair actions into an ordered retry brief so a later orchestration layer can
    trigger a controlled second pass.
    """

    route = str(_get_attr_or_key(route_decision, "route", "unknown"))
    recommended_tools = list(_get_attr_or_key(route_decision, "recommended_tools", []) or [])
    applied_count = repair_execution_report.applied_count

    instructions: list[RetryInstruction] = []
    latest_actions = list(_get_attr_or_key(repair_plan, "actions", []) or [])
    for action in latest_actions:
        action_type = str(_get_attr_or_key(action, "action_type", "verification"))
        owner_agent = str(_get_attr_or_key(action, "owner_agent", "Verifier Agent"))
        priority = int(_get_attr_or_key(action, "priority", 100))
        detail = str(_get_attr_or_key(action, "detail", ""))
        blocking = bool(_get_attr_or_key(action, "blocking", False))
        focus = _focus_for_action(action_type)
        retry_detail = (
            f"route={route}; tools={recommended_tools}; action={action_type}; blocking={blocking}; {detail}"
        )
        instructions.append(_instruction(priority, owner_agent, focus, retry_detail))

    instructions = sorted(instructions, key=lambda item: (item.priority, item.owner_agent, item.focus, item.detail))
    deduped: list[RetryInstruction] = []
    seen: set[tuple[str, str, str]] = set()
    for item in instructions:
        key = (item.owner_agent, item.focus, item.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    should_retry = bool(deduped)
    if should_retry:
        rationale = (
            f"retry recommended: {len(deduped)} unresolved instructions after {applied_count} safe repair(s)"
        )
    else:
        rationale = f"no retry recommended after {applied_count} safe repair(s)"

    return RetryDecision(
        task_id=task_id,
        should_retry=should_retry,
        max_retry_attempts=MAX_RETRY_ATTEMPTS if should_retry else 0,
        rationale=rationale,
        instructions=deduped,
    )


def retry_decision_to_dict(decision: RetryDecision) -> dict[str, Any]:
    return asdict(decision)
