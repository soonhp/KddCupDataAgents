from __future__ import annotations

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from runner.scoring import normalize_cell, score_prediction_roots, score_task


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


class ScoringTests(unittest.TestCase):
    def test_normalize_cell_matches_public_rules(self) -> None:
        self.assertEqual(normalize_cell("NULL"), "")
        self.assertEqual(normalize_cell("0.005"), "0.01")
        self.assertEqual(normalize_cell("4200000"), "4200000.00")
        self.assertEqual(normalize_cell("2024-3-1"), "2024-03-01")
        self.assertEqual(normalize_cell("2024-03-01T01:00:00+09:00"), "2024-02-29T16:00:00Z")
        self.assertEqual(normalize_cell(" East Asia "), "East Asia")

    def test_score_ignores_headers_column_order_and_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold = root / "gold.csv"
            prediction = root / "prediction.csv"
            _write_csv(gold, [["name", "amount"], ["alice", "1"], ["bob", "2"]])
            _write_csv(prediction, [["x", "y"], ["2.00", "bob"], ["1.00", "alice"]])

            result = score_task(task_id="task_1", prediction_path=prediction, gold_path=gold)

            self.assertEqual(result.score, 1.0)
            self.assertEqual(result.matched_columns, 2)
            self.assertEqual(result.extra_columns, 0)

    def test_score_penalizes_extra_columns_with_configurable_lambda(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold = root / "gold.csv"
            prediction = root / "prediction.csv"
            _write_csv(gold, [["answer"], ["42"]])
            _write_csv(prediction, [["answer", "extra"], ["42.00", "noise"]])

            result = score_task(
                task_id="task_1",
                prediction_path=prediction,
                gold_path=gold,
                lambda_penalty=Decimal("0.2"),
            )

            self.assertEqual(result.matched_columns, 1)
            self.assertEqual(result.predicted_columns, 2)
            self.assertAlmostEqual(result.score, 0.9)

    def test_score_roots_average_missing_predictions_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_root = root / "gold"
            prediction_root = root / "pred"
            _write_csv(gold_root / "task_1" / "gold.csv", [["answer"], ["42"]])
            _write_csv(gold_root / "task_2" / "gold.csv", [["answer"], ["ok"]])
            _write_csv(prediction_root / "task_1" / "prediction.csv", [["answer"], ["42.0"]])

            summary = score_prediction_roots(prediction_root=prediction_root, gold_root=gold_root)

            self.assertEqual(summary.task_count, 2)
            self.assertEqual(summary.missing_prediction_count, 1)
            self.assertEqual(summary.total_score, 0.5)


if __name__ == "__main__":
    unittest.main()
