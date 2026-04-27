from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from runner.task_intelligence import decide_route, infer_question_signals, normalize_prediction_csv, profile_task_context
from runner.verification import run_dual_verification


def _write_task(task_dir: Path, *, question: str = "", difficulty: str = "medium") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps({"task_id": task_dir.name, "difficulty": difficulty, "question": question}),
        encoding="utf-8",
    )


class TaskIntelligenceTests(unittest.TestCase):
    def test_profile_route_and_normalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "task_1"
            _write_task(task_dir, question="Calculate the total by category from the CSV table")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "doc").mkdir(parents=True)
            (task_dir / "context" / "csv" / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (task_dir / "context" / "knowledge.md").write_text("# knowledge", encoding="utf-8")

            profile = profile_task_context(task_dir)
            route = decide_route(profile)

            self.assertTrue(profile.csv_files)
            self.assertTrue(profile.knowledge_files)
            self.assertIn(route.route, {"python_first", "document_first", "hybrid_doc_table", "hybrid_sql_python"})
            self.assertIn("python", route.recommended_tools)

            prediction = root / "prediction.csv"
            prediction.write_text("answer\nNULL\n", encoding="utf-8")
            normalize_prediction_csv(prediction)
            with prediction.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1][0], "")

    def test_question_signal_extraction(self) -> None:
        signals = infer_question_signals(
            "According to the policy document, join the tables and calculate the median trend."
        )
        self.assertIn("join", signals.sql)
        self.assertIn("median", signals.python)
        self.assertIn("according to", signals.document)
        self.assertIn("policy", signals.document)

    def test_db_join_count_routes_to_sql_or_hybrid_sql_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_sql"
            _write_task(task_dir, question="Join the tables and count records by customer rank")
            (task_dir / "context" / "db").mkdir(parents=True)
            (task_dir / "context" / "db" / "data.sqlite").write_text("", encoding="utf-8")

            route = decide_route(profile_task_context(task_dir))
            self.assertIn(route.route, {"sql_first", "hybrid_sql_python"})
            self.assertIn("sqlite", route.recommended_tools)

    def test_db_with_statistical_signal_routes_to_hybrid_sql_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_hybrid_sql_python"
            _write_task(task_dir, question="Compute the correlation trend after filtering rows from the database")
            (task_dir / "context" / "db").mkdir(parents=True)
            (task_dir / "context" / "db" / "metrics.db").write_text("", encoding="utf-8")

            route = decide_route(profile_task_context(task_dir))
            self.assertEqual(route.route, "hybrid_sql_python")

    def test_csv_statistics_routes_to_python_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_python"
            _write_task(task_dir, question="Calculate the median variance and distribution from the CSV")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "metrics.csv").write_text("x\n1\n2\n", encoding="utf-8")

            route = decide_route(profile_task_context(task_dir))
            self.assertEqual(route.route, "python_first")

    def test_knowledge_policy_routes_to_document_or_hybrid_doc_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_doc"
            _write_task(task_dir, question="According to the policy, explain the definition used in the manual")
            (task_dir / "context").mkdir(parents=True)
            (task_dir / "context" / "knowledge.md").write_text("# Policy\nDefinition text", encoding="utf-8")

            route = decide_route(profile_task_context(task_dir))
            self.assertIn(route.route, {"document_first", "hybrid_doc_table"})
            self.assertIn("document_reader", route.recommended_tools)

    def test_doc_and_table_context_routes_to_hybrid_doc_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_doc_table"
            _write_task(task_dir, question="According to the guideline, compare totals by product")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "doc").mkdir(parents=True)
            (task_dir / "context" / "csv" / "sales.csv").write_text("p,v\na,1\n", encoding="utf-8")
            (task_dir / "context" / "doc" / "guideline.md").write_text("# Guideline", encoding="utf-8")

            route = decide_route(profile_task_context(task_dir))
            self.assertEqual(route.route, "hybrid_doc_table")

    def test_missing_context_sets_fallback_and_risk_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_empty"
            _write_task(task_dir, question="")

            route = decide_route(profile_task_context(task_dir))
            self.assertEqual(route.route, "python_first")
            self.assertIn("missing_context_dir", route.risk_flags)
            self.assertIn("missing_question", route.risk_flags)

    def test_missing_task_json_sets_risk_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_missing_json"
            (task_dir / "context").mkdir(parents=True)

            route = decide_route(profile_task_context(task_dir))
            self.assertEqual(route.route, "python_first")
            self.assertIn("missing_task_json", route.risk_flags)
            self.assertIn("no_supported_context_files", route.risk_flags)

    def test_dual_verification_flags_bad_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n\n\n\n", encoding="utf-8")
            report = run_dual_verification("task_1", prediction)
            self.assertFalse(report.all_passed)


if __name__ == "__main__":
    unittest.main()
