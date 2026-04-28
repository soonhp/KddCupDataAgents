from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from runner.agent_review import run_agent_review
from runner.repair_executor import execute_repair_plan
from runner.repair_planner import build_repair_plan
from runner.semantic_review import run_semantic_review
from runner.task_intelligence import decide_route, profile_task_context
from runner.verification import infer_output_contract, run_dual_verification


def _write_task(task_dir: Path, *, question: str = "", extra: dict | None = None) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_dir.name, "difficulty": "medium", "question": question}
    if extra:
        payload.update(extra)
    (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


class RepairExecutorTests(unittest.TestCase):
    def test_repair_executor_renames_matching_width_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_repair_executor_header"
            _write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("result\n42\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_repair_executor_header", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_repair_executor_header",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_repair_executor_header",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            plan = build_repair_plan(
                task_id="task_repair_executor_header",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            execution = execute_repair_plan(repair_plan=plan, prediction_path=prediction, output_contract=contract)
            self.assertGreaterEqual(execution.applied_count, 1)
            self.assertEqual(_read_rows(prediction)[0], ["answer"])

    def test_repair_executor_skips_header_repair_when_width_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_repair_executor_skip"
            _write_task(task_dir, question="Return a CSV with columns: name, value", extra={"expected_columns": ["name", "value"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("name\nalice\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_repair_executor_skip", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_repair_executor_skip",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_repair_executor_skip",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            plan = build_repair_plan(
                task_id="task_repair_executor_skip",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            execution = execute_repair_plan(repair_plan=plan, prediction_path=prediction, output_contract=contract)
            self.assertGreaterEqual(execution.skipped_count, 1)
            self.assertEqual(_read_rows(prediction)[0], ["name"])


if __name__ == "__main__":
    unittest.main()
