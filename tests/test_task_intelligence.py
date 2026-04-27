from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runner.task_intelligence import decide_route, normalize_prediction_csv, profile_task_context
from runner.verification import run_dual_verification


class TaskIntelligenceTests(unittest.TestCase):
    def test_profile_route_and_normalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "task_1"
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "doc").mkdir(parents=True)
            (task_dir / "context" / "csv" / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (task_dir / "context" / "knowledge.md").write_text("# knowledge", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)

            self.assertTrue(profile.csv_files)
            self.assertTrue(profile.knowledge_files)
            self.assertIn(route.route, {"python_first", "document_first"})

            prediction = root / "prediction.csv"
            prediction.write_text("answer\nNULL\n", encoding="utf-8")
            normalize_prediction_csv(prediction)
            with prediction.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1][0], "")

    def test_dual_verification_flags_bad_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n\n\n\n", encoding="utf-8")
            report = run_dual_verification("task_1", prediction)
            self.assertFalse(report.all_passed)


if __name__ == "__main__":
    unittest.main()
