from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from runner.agent_review import run_agent_review
from runner.semantic_review import run_semantic_review
from runner.task_intelligence import decide_route, infer_question_signals, normalize_prediction_csv, profile_task_context
from runner.verification import infer_output_contract, run_dual_verification


def _write_task(
    task_dir: Path,
    *,
    question: str = "",
    difficulty: str = "medium",
    extra: dict | None = None,
) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task_dir.name, "difficulty": difficulty, "question": question}
    if extra:
        payload.update(extra)
    (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")


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

    def test_schema_hints_capture_csv_columns_json_keys_and_doc_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_schema"
            _write_task(task_dir, question="Calculate totals from context")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "json").mkdir(parents=True)
            (task_dir / "context" / "doc").mkdir(parents=True)
            (task_dir / "context" / "csv" / "sales.csv").write_text("product,revenue\na,10\n", encoding="utf-8")
            (task_dir / "context" / "json" / "meta.json").write_text(
                json.dumps({"region": "APAC", "currency": "USD"}),
                encoding="utf-8",
            )
            (task_dir / "context" / "doc" / "notes.md").write_text("# Notes\nUse net revenue.", encoding="utf-8")

            schema_hints = profile_task_context(task_dir).schema_hints
            self.assertIsNotNone(schema_hints)
            assert schema_hints is not None
            self.assertEqual(schema_hints["csv"][0]["columns"], ["product", "revenue"])
            self.assertIn("region", schema_hints["json"][0]["top_level_keys"])
            self.assertIn("net revenue", schema_hints["doc"][0]["preview"])

    def test_schema_hints_capture_sqlite_tables_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_sqlite_schema"
            _write_task(task_dir, question="Count orders by customer")
            db_dir = task_dir / "context" / "db"
            db_dir.mkdir(parents=True)
            db_path = db_dir / "orders.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE orders (order_id INTEGER, customer TEXT, amount REAL)")
                conn.commit()

            schema_hints = profile_task_context(task_dir).schema_hints
            self.assertIsNotNone(schema_hints)
            assert schema_hints is not None
            self.assertEqual(schema_hints["db"][0]["tables"][0]["name"], "orders")
            column_names = [column["name"] for column in schema_hints["db"][0]["tables"][0]["columns"]]
            self.assertEqual(column_names, ["order_id", "customer", "amount"])

    def test_missing_context_sets_empty_schema_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_empty_schema"
            _write_task(task_dir, question="")

            profile = profile_task_context(task_dir)
            self.assertEqual(profile.schema_hints, {"csv": [], "db": [], "json": [], "doc": []})

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

    def test_verification_rejects_duplicate_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer,answer\n1,2\n", encoding="utf-8")
            report = run_dual_verification("task_dup_header", prediction)
            self.assertFalse(report.all_passed)
            self.assertTrue(any(check.name == "contract_check" and not check.passed for check in report.checks))

    def test_verification_rejects_traceback_like_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\nTraceback: boom\n", encoding="utf-8")
            report = run_dual_verification("task_traceback", prediction)
            self.assertFalse(report.all_passed)
            self.assertTrue(any("suspicious" in check.detail for check in report.checks))

    def test_verification_rejects_single_empty_answer_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n\n", encoding="utf-8")
            report = run_dual_verification("task_empty_answer", prediction)
            self.assertFalse(report.all_passed)
            self.assertTrue(any(check.name == "shape_check" and not check.passed for check in report.checks))

    def test_verification_accepts_basic_non_empty_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n42\n", encoding="utf-8")
            report = run_dual_verification("task_valid", prediction)
            self.assertTrue(report.all_passed)

    def test_infer_output_contract_from_task_json_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_contract"
            _write_task(task_dir, extra={"expected_columns": ["name", "score"], "min_rows": 1, "max_rows": 2})
            contract = infer_output_contract(task_dir)
            self.assertIsNotNone(contract)
            assert contract is not None
            self.assertEqual(contract.expected_columns, ["name", "score"])
            self.assertEqual(contract.min_rows, 1)
            self.assertEqual(contract.max_rows, 2)

    def test_task_contract_accepts_matching_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_contract_ok"
            _write_task(task_dir, extra={"output_schema": {"columns": ["name", "score"]}})
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("name,score\nalice,10\n", encoding="utf-8")
            report = run_dual_verification("task_contract_ok", prediction, output_contract=infer_output_contract(task_dir))
            self.assertTrue(report.all_passed)
            self.assertIsNotNone(report.output_contract)

    def test_task_contract_rejects_missing_expected_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_contract_bad"
            _write_task(task_dir, extra={"expected_columns": ["name", "score"]})
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("name\nalice\n", encoding="utf-8")
            report = run_dual_verification("task_contract_bad", prediction, output_contract=infer_output_contract(task_dir))
            self.assertFalse(report.all_passed)
            self.assertTrue(any(check.name == "task_contract_check" and not check.passed for check in report.checks))

    def test_task_contract_can_be_inferred_from_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_contract_question"
            _write_task(task_dir, question="Return a CSV with columns: company, revenue")
            contract = infer_output_contract(task_dir)
            self.assertIsNotNone(contract)
            assert contract is not None
            self.assertEqual(contract.expected_columns, ["company", "revenue"])

    def test_agent_review_passes_clean_task_with_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_agent_ok"
            _write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n42\n", encoding="utf-8")
            verification = run_dual_verification("task_agent_ok", prediction, output_contract=infer_output_contract(task_dir))

            review = run_agent_review(
                task_id="task_agent_ok",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            self.assertTrue(review.all_passed)
            self.assertEqual({comment.agent for comment in review.comments}, {
                "PM Agent",
                "Planner Agent",
                "Data Profiling Agent",
                "Verifier Agent",
                "Answer Contract Agent",
            })

    def test_agent_review_flags_verifier_and_contract_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_agent_bad"
            _write_task(task_dir, question="Return a CSV with columns: name, score", extra={"expected_columns": ["name", "score"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("name\nalice\n", encoding="utf-8")
            verification = run_dual_verification("task_agent_bad", prediction, output_contract=infer_output_contract(task_dir))

            review = run_agent_review(
                task_id="task_agent_bad",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
            )
            self.assertFalse(review.all_passed)
            failed_agents = {comment.agent for comment in review.comments if not comment.passed}
            self.assertIn("Verifier Agent", failed_agents)
            self.assertIn("Answer Contract Agent", failed_agents)

    def test_semantic_review_passes_numeric_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_semantic_numeric"
            _write_task(task_dir, question="Calculate the total revenue")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "sales.csv").write_text("revenue\n10\n", encoding="utf-8")
            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\n42\n", encoding="utf-8")
            verification = run_dual_verification("task_semantic_numeric", prediction)

            review = run_semantic_review(
                task_id="task_semantic_numeric",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            self.assertTrue(review.all_passed)
            self.assertTrue(any(check.name == "numeric_intent_check" for check in review.checks))

    def test_semantic_review_recommends_repair_for_non_numeric_numeric_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_semantic_bad_numeric"
            _write_task(task_dir, question="Compute the average revenue")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "sales.csv").write_text("revenue\n10\n", encoding="utf-8")
            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\nnot available\n", encoding="utf-8")
            verification = run_dual_verification("task_semantic_bad_numeric", prediction)

            review = run_semantic_review(
                task_id="task_semantic_bad_numeric",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            self.assertTrue(review.all_passed)
            self.assertTrue(review.repair_recommendations)
            self.assertTrue(any(check.name == "numeric_intent_check" and not check.passed for check in review.checks))

    def test_semantic_review_flags_document_signal_without_document_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task_semantic_doc_missing"
            _write_task(task_dir, question="According to the policy, explain the definition")
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")
            profile = profile_task_context(task_dir)
            route = decide_route(profile)
            prediction = Path(tmp) / "prediction.csv"
            prediction.write_text("answer\nSome explanation\n", encoding="utf-8")
            verification = run_dual_verification("task_semantic_doc_missing", prediction)

            review = run_semantic_review(
                task_id="task_semantic_doc_missing",
                task_profile=profile,
                route_decision=route,
                verification_report=verification,
                prediction_path=prediction,
            )
            self.assertTrue(review.repair_recommendations)
            self.assertTrue(any(check.name == "document_grounding_check" and not check.passed for check in review.checks))


if __name__ == "__main__":
    unittest.main()
