from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.agent_review import run_agent_review
from runner.repair_planner import build_repair_plan
from runner.retry_orchestrator import build_retry_decision, compare_attempts, prepare_retry_artifacts
from runner.semantic_review import run_semantic_review
from runner.task_intelligence import decide_route, profile_task_context
from runner.verification import infer_output_contract, run_dual_verification


def _write_task(task_dir: Path, *, question: str = "", extra: dict | None = None) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_dir.name, "difficulty": "medium", "question": question}
    if extra:
        payload.update(extra)
    (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")


class RetryOrchestratorTests(unittest.TestCase):
    def test_retry_decision_is_false_for_clean_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_retry_clean"
            _write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n42\n", encoding="utf-8")

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
            repair_plan = build_repair_plan(
                task_id="task_retry_clean",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )

            retry_decision = build_retry_decision(
                repair_plan=repair_plan,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            self.assertFalse(retry_decision.should_retry)
            self.assertEqual(retry_decision.max_retry_count, 0)

    def test_retry_decision_collects_retryable_actions_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_retry_needed"
            _write_task(task_dir, question="Compute the average revenue", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("revenue\n10\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("wrong_header\nnot available\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_retry_needed", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_retry_needed",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_retry_needed",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            repair_plan = build_repair_plan(
                task_id="task_retry_needed",
                route_decision=route,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )

            retry_decision = build_retry_decision(
                repair_plan=repair_plan,
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            self.assertTrue(retry_decision.should_retry)
            self.assertTrue(retry_decision.retry_instructions)

            retry_root = Path(tmp) / "retry_root"
            artifacts = prepare_retry_artifacts(
                task_dir=task_dir,
                retry_root=retry_root,
                repair_plan=repair_plan,
                retry_decision=retry_decision,
            )
            self.assertTrue(artifacts.retry_task_dir.exists())
            self.assertTrue(artifacts.retry_note_path.exists())
            self.assertTrue(artifacts.retry_plan_path.exists())
            self.assertIn("Retry Instructions", artifacts.retry_note_path.read_text(encoding="utf-8"))

    def test_compare_attempts_prefers_lower_failure_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_retry_compare"
            _write_task(task_dir, question="Compute the average revenue", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("revenue\n10\n", encoding="utf-8")

            original_prediction = Path(tmp) / "prediction.original.csv"
            original_prediction.write_text("wrong_header\nnot available\n", encoding="utf-8")
            retry_prediction = Path(tmp) / "prediction.retry.csv"
            retry_prediction.write_text("answer\n10\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)

            original_verification = run_dual_verification("task_retry_compare", original_prediction, contract)
            original_semantic = run_semantic_review(
                task_id="task_retry_compare",
                task_profile=profile,
                route_decision=route,
                verification_report=original_verification,
                prediction_path=original_prediction,
            )
            original_agent = run_agent_review(
                task_id="task_retry_compare",
                task_profile=profile,
                route_decision=route,
                verification_report=original_verification,
            )

            retry_verification = run_dual_verification("task_retry_compare", retry_prediction, contract)
            retry_semantic = run_semantic_review(
                task_id="task_retry_compare",
                task_profile=profile,
                route_decision=route,
                verification_report=retry_verification,
                prediction_path=retry_prediction,
            )
            retry_agent = run_agent_review(
                task_id="task_retry_compare",
                task_profile=profile,
                route_decision=route,
                verification_report=retry_verification,
            )

            comparison = compare_attempts(
                original_verification_report=original_verification,
                retried_verification_report=retry_verification,
                original_semantic_review_report=original_semantic,
                retried_semantic_review_report=retry_semantic,
                original_agent_review_report=original_agent,
                retried_agent_review_report=retry_agent,
            )
            self.assertEqual(comparison.selected_attempt, "retry")


if __name__ == "__main__":
    unittest.main()
