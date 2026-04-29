from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.agent_review import run_agent_review
from runner.repair_executor import execute_repair_plan
from runner.repair_planner import build_repair_plan
from runner.retry_executor import build_retry_decision
from runner.semantic_review import run_semantic_review
from runner.task_intelligence import decide_route, profile_task_context
from runner.verification import infer_output_contract, run_dual_verification


def _write_task(task_dir: Path, *, question: str = "", extra: dict | None = None) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_dir.name, "difficulty": "medium", "question": question}
    if extra:
        payload.update(extra)
    (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")


class RetryExecutorTests(unittest.TestCase):
    def test_retry_decision_not_needed_after_clean_safe_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_retry_clean"
            _write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("result\n42\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_retry_clean", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_retry_clean",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_retry_clean",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            plan = build_repair_plan(
                task_id="task_retry_clean",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            execution = execute_repair_plan(repair_plan=plan, prediction_path=prediction, output_contract=contract)
            repaired_verification = run_dual_verification("task_retry_clean", prediction, contract)
            repaired_semantic = run_semantic_review(
                task_id="task_retry_clean",
                task_profile=profile,
                route_decision=route,
                verification_report=repaired_verification,
                prediction_path=prediction,
            )
            repaired_agent = run_agent_review(
                task_id="task_retry_clean",
                task_profile=profile,
                route_decision=route,
                verification_report=repaired_verification,
            )
            repaired_plan = build_repair_plan(
                task_id="task_retry_clean",
                route_decision=route,
                verification_report=repaired_verification,
                semantic_review_report=repaired_semantic,
                agent_review_report=repaired_agent,
            )

            decision = build_retry_decision(
                task_id="task_retry_clean",
                route_decision=route,
                repair_plan=repaired_plan,
                repair_execution_report=execution,
            )
            self.assertFalse(decision.should_retry)
            self.assertEqual(decision.instructions, [])

    def test_retry_decision_captures_unresolved_numeric_recompute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_retry_numeric"
            _write_task(task_dir, question="Compute the average revenue", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("revenue\n10\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\nnot available\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_retry_numeric", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_retry_numeric",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_retry_numeric",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            plan = build_repair_plan(
                task_id="task_retry_numeric",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            execution = execute_repair_plan(repair_plan=plan, prediction_path=prediction, output_contract=contract)
            decision = build_retry_decision(
                task_id="task_retry_numeric",
                route_decision=route,
                repair_plan=plan,
                repair_execution_report=execution,
            )
            self.assertTrue(decision.should_retry)
            self.assertTrue(any(item.focus == "numeric_recompute" for item in decision.instructions))


if __name__ == "__main__":
    unittest.main()
