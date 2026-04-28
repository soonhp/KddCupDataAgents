from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runner.repair_planner import RepairPlan
from runner.verification import OutputContract


@dataclass(slots=True)
class RepairExecutionStep:
    action_type: str
    owner_agent: str
    status: str
    detail: str


@dataclass(slots=True)
class RepairExecutionReport:
    task_id: str
    applied_count: int
    skipped_count: int
    planned_count: int
    steps: list[RepairExecutionStep]


def _step(action_type: str, owner_agent: str, status: str, detail: str) -> RepairExecutionStep:
    return RepairExecutionStep(action_type=action_type, owner_agent=owner_agent, status=status, detail=detail)


def _read_rows(path: Path) -> list[list[str]] | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _write_rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _normalize_columns(columns: list[str]) -> list[str]:
    return [str(column).strip() for column in columns if str(column).strip()]


def _apply_header_repair(
    *,
    prediction_path: Path,
    output_contract: OutputContract | None,
    action_type: str,
    owner_agent: str,
) -> RepairExecutionStep:
    if output_contract is None or not output_contract.expected_columns:
        return _step(action_type, owner_agent, "skipped", "no expected columns available for safe header repair")

    rows = _read_rows(prediction_path)
    if rows is None:
        return _step(action_type, owner_agent, "skipped", "prediction.csv could not be parsed for safe header repair")
    if not rows:
        return _step(action_type, owner_agent, "skipped", "prediction.csv has no rows; refusing to invent answer content")

    expected = _normalize_columns(output_contract.expected_columns)
    if not expected:
        return _step(action_type, owner_agent, "skipped", "expected columns normalize to empty list")

    current_width = len(rows[0]) if rows[0] else 0
    if current_width != len(expected):
        return _step(
            action_type,
            owner_agent,
            "skipped",
            f"header width mismatch; current_width={current_width}, expected_width={len(expected)}",
        )

    current_header = [cell.strip() for cell in rows[0]]
    if current_header == expected:
        return _step(action_type, owner_agent, "planned", "header already matches expected contract")

    rows[0] = expected
    _write_rows(prediction_path, rows)
    return _step(action_type, owner_agent, "applied", f"renamed header from {current_header} to {expected}")


def execute_repair_plan(
    *,
    repair_plan: RepairPlan,
    prediction_path: Path,
    output_contract: OutputContract | None,
) -> RepairExecutionReport:
    """Execute deterministic, safe subset of repair actions.

    The executor never fabricates answer values. It only performs mechanically safe
    repairs such as header renaming when the task contract provides an expected
    schema with the same width. Computational/semantic repairs are emitted as
    planned next-pass instructions.
    """

    steps: list[RepairExecutionStep] = []
    for action in repair_plan.actions:
        if action.action_type in {"fix_output_contract", "fix_task_contract"}:
            steps.append(
                _apply_header_repair(
                    prediction_path=prediction_path,
                    output_contract=output_contract,
                    action_type=action.action_type,
                    owner_agent=action.owner_agent,
                )
            )
        elif action.action_type in {
            "recompute_numeric_answer",
            "regenerate_tabular_comparison",
            "restore_document_grounding",
            "expand_hybrid_tool_plan",
            "apply_semantic_recommendation",
        }:
            steps.append(_step(action.action_type, action.owner_agent, "planned", action.detail))
        else:
            steps.append(_step(action.action_type, action.owner_agent, "planned", action.detail))

    applied_count = sum(1 for item in steps if item.status == "applied")
    skipped_count = sum(1 for item in steps if item.status == "skipped")
    planned_count = sum(1 for item in steps if item.status == "planned")
    return RepairExecutionReport(
        task_id=repair_plan.task_id,
        applied_count=applied_count,
        skipped_count=skipped_count,
        planned_count=planned_count,
        steps=steps,
    )


def repair_execution_report_to_dict(report: RepairExecutionReport) -> dict[str, Any]:
    return asdict(report)
