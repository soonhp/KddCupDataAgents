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
    risk_flags = list(_get_attr_or_key(route_decision, "risk_flags", []) or [])

    applied_count = repair_execution_report.applied_count
    unresolved_steps = [step for step in repair_execution_report.steps if step.status in {"planned", "skipped"}]
    instructions: list[RetryInstruction] = []

    for index, step in enumerate(unresolved_steps, start=1):
        focus = "verification"
        if step.action_type == "recompute_numeric_answer":
            focus = "numeric_recompute"
        elif step.action_type == "regenerate_tabular_comparison":
            focus = "tabular_regeneration"
        elif step.action_type == "restore_document_grounding":
            focus = "document_grounding"
        elif step.action_type == "expand_hybrid_tool_plan":
            focus = "hybrid_tooling"
        elif step.action_type in {"fix_output_contract", "fix_task_contract"}:
            focus = "output_contract"

        detail = f"route={route}; tools={recommended_tools}; action={step.action_type}; {step.detail}"
        instructions.append(_instruction(index * 10, step.owner_agent, focus, detail))

    if risk_flags:
        instructions.append(
            _instruction(
                90,
                "PM Agent",
                "route_risk_review",
                "Route risk flags remain for retry orchestration: " + ", ".join(risk_flags),
            )
        )

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
