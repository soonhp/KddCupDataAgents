from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.agent_review import run_agent_review
from runner.attempt_selector import build_attempt_evaluation, select_best_attempt
from runner.semantic_review import run_semantic_review
from runner.task_intelligence import decide_route, profile_task_context
from runner.verification import infer_output_contract, run_dual_verification


def _write_task(task_dir: Path, *, question: str = "", extra: dict | None = None) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_dir.name, "difficulty": "medium", "question": question}
    if extra:
        payload.update(extra)
    (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")


class AttemptSelectorTests(unittest.TestCase):
    def test_build_attempt_evaluation_counts_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_attempt_eval"
            _write_task(task_dir, question="Compute the average revenue", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "sales.csv").write_text("revenue\n10\n", encoding="utf-8")
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("wrong_header\nnot available\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)
            verification = run_dual_verification("task_attempt_eval", prediction, contract)
            semantic = run_semantic_review(
                task_id="task_attempt_eval",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            agent = run_agent_review(
                task_id="task_attempt_eval",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )

            evaluation = build_attempt_evaluation(
                attempt_name="original",
                verification_report=verification,
                semantic_review_report=semantic,
                agent_review_report=agent,
            )
            self.assertGreater(evaluation.failed_verification_checks, 0)
            self.assertGreater(evaluation.total_penalty, 0)
            self.assertGreaterEqual(evaluation.failed_semantic_warning_checks, 0)

    def test_select_best_attempt_prefers_lower_failure_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_attempt_select"
            _write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")

            bad_prediction = Path(tmp) / "prediction.bad.csv"
            bad_prediction.write_text("wrong_header\nnot available\n", encoding="utf-8")
            good_prediction = Path(tmp) / "prediction.good.csv"
            good_prediction.write_text("answer\n42\n", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            contract = infer_output_contract(task_dir)

            bad_verification = run_dual_verification("task_attempt_select", bad_prediction, contract)
            bad_semantic = run_semantic_review(
                task_id="task_attempt_select",
                task_profile=profile,
                route_decision=route,
                verification_report=bad_verification,
                prediction_path=bad_prediction,
            )
            bad_agent = run_agent_review(
                task_id="task_attempt_select",
                task_profile=profile,
                route_decision=route,
                verification_report=bad_verification,
            )
            bad_eval = build_attempt_evaluation(
                attempt_name="original",
                verification_report=bad_verification,
                semantic_review_report=bad_semantic,
                agent_review_report=bad_agent,
            )

            good_verification = run_dual_verification("task_attempt_select", good_prediction, contract)
            good_semantic = run_semantic_review(
                task_id="task_attempt_select",
                task_profile=profile,
                route_decision=route,
                verification_report=good_verification,
                prediction_path=good_prediction,
            )
            good_agent = run_agent_review(
                task_id="task_attempt_select",
                task_profile=profile,
                route_decision=route,
                verification_report=good_verification,
            )
            good_eval = build_attempt_evaluation(
                attempt_name="post_repair",
                verification_report=good_verification,
                semantic_review_report=good_semantic,
                agent_review_report=good_agent,
            )

            selection = select_best_attempt(bad_eval, good_eval)
            self.assertEqual(selection.selected_attempt, "post_repair")
            self.assertEqual(selection.candidates[0].attempt_name, "post_repair")
            self.assertIn("winner tuple=", selection.rationale)

    def test_attempt_selection_prefers_fewer_semantic_errors_over_warnings(self) -> None:
        from runner.attempt_selector import AttemptEvaluation

        candidate_a = AttemptEvaluation(
            attempt_name="post_repair",
            failed_verification_checks=0,
            failed_agent_reviews=0,
            failed_semantic_checks=2,
            failed_semantic_error_checks=1,
            failed_semantic_warning_checks=1,
            total_penalty=11,
        )
        candidate_b = AttemptEvaluation(
            attempt_name="retry",
            failed_verification_checks=0,
            failed_agent_reviews=0,
            failed_semantic_checks=2,
            failed_semantic_error_checks=0,
            failed_semantic_warning_checks=2,
            total_penalty=2,
        )

        selection = select_best_attempt(candidate_a, candidate_b)
        self.assertEqual(selection.selected_attempt, "retry")
        self.assertIn("semantic_error=0", selection.rationale)


if __name__ == "__main__":
    unittest.main()
