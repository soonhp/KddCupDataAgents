from __future__ import annotations

import unittest

from runner.attempt_selector import (
    AttemptEvaluation,
    build_attempt_selection_plan,
    select_best_attempt,
)


class ThreeWayAttemptSelectionTests(unittest.TestCase):
    def test_attempt_selection_records_retry_candidate_presence(self) -> None:
        original = AttemptEvaluation(
            attempt_name="original",
            failed_verification_checks=2,
            failed_agent_reviews=1,
            failed_semantic_checks=1,
            total_penalty=211,
        )
        post_repair = AttemptEvaluation(
            attempt_name="post_repair",
            failed_verification_checks=1,
            failed_agent_reviews=0,
            failed_semantic_checks=1,
            total_penalty=101,
        )
        retry = AttemptEvaluation(
            attempt_name="retry",
            failed_verification_checks=0,
            failed_agent_reviews=0,
            failed_semantic_checks=1,
            total_penalty=1,
        )

        selection = select_best_attempt(original, post_repair, retry)
        self.assertEqual(selection.selected_attempt, "retry")
        self.assertTrue(selection.has_retry_attempt)
        self.assertEqual(selection.candidate_count, 3)

    def test_attempt_selection_plan_points_to_retry_prediction(self) -> None:
        plan = build_attempt_selection_plan(
            retry_attempt_prediction_path="/output/task_1/prediction.retry.csv"
        )
        self.assertEqual(plan.expected_retry_attempt_name, "retry")
        self.assertTrue(plan.compare_with_existing_attempts)
        self.assertIn("prediction.retry.csv", plan.retry_attempt_prediction_path)


if __name__ == "__main__":
    unittest.main()
