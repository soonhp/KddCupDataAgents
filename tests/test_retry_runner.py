from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from runner.retry_runner import run_retry_attempt
from runner.task_intelligence import decide_route, profile_task_context
from runner.verification import infer_output_contract


class RetryRunnerTests(unittest.TestCase):
    def _write_task(self, task_dir: Path, *, question: str = "", extra: dict | None = None) -> None:
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": task_dir.name, "difficulty": "medium", "question": question}
        if extra:
            payload.update(extra)
        (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_run_retry_attempt_produces_retry_prediction_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "task_1"
            self._write_task(task_dir, question="Return a CSV with columns: answer", extra={"expected_columns": ["answer"]})
            (task_dir / "context" / "csv").mkdir(parents=True)
            (task_dir / "context" / "csv" / "data.csv").write_text("x\n1\n", encoding="utf-8")

            retry_task_dir = root / "retry_input" / "task_1"
            retry_task_dir.mkdir(parents=True)
            (retry_task_dir / "task.json").write_text((task_dir / "task.json").read_text(encoding="utf-8"), encoding="utf-8")
            (retry_task_dir / "context").mkdir(parents=True)
            (retry_task_dir / "context" / "retry_instructions.md").write_text("# Retry Instructions\n- Fix the answer\n", encoding="utf-8")

            task_output_dir = root / "output" / "task_1"
            artifact_root = root / "artifacts"
            task_profile = profile_task_context(task_dir)
            route_decision = decide_route(task_profile)
            output_contract = infer_output_contract(task_dir)

            built_inputs: dict[str, str] = {}

            def fake_builder(**kwargs):
                built_inputs["input_dir"] = str(kwargs["input_dir"])
                built_inputs["artifact_dir"] = str(kwargs["artifact_dir"])
                config_path = root / "retry_runtime.yaml"
                config_path.write_text("run:\n  output_dir: {}\n".format(root / "retry_run"), encoding="utf-8")
                return config_path

            def fake_loader(_path: Path):
                return SimpleNamespace(run=SimpleNamespace(output_dir=str(root / "retry_run")))

            def fake_run_output_dir_creator(output_dir: str, run_id: str | None = None):
                run_output_dir = Path(output_dir)
                run_output_dir.mkdir(parents=True, exist_ok=True)
                return None, run_output_dir

            def fake_task_runner(*, task_id: str, config, run_output_dir: Path):
                prediction_path = run_output_dir / task_id / "prediction.csv"
                prediction_path.parent.mkdir(parents=True, exist_ok=True)
                prediction_path.write_text("answer\n42\n", encoding="utf-8")
                trace_path = run_output_dir / task_id / "trace.json"
                trace_path.write_text("{}", encoding="utf-8")
                return SimpleNamespace(
                    prediction_csv_path=prediction_path,
                    trace_path=trace_path,
                    succeeded=True,
                    failure_reason=None,
                )

            result = run_retry_attempt(
                task_id="task_1",
                retry_task_dir=retry_task_dir,
                task_output_dir=task_output_dir,
                artifact_root=artifact_root,
                model_name="test-model",
                api_base="http://localhost",
                api_key="dummy",
                task_timeout_seconds=60,
                run_id="run-1",
                task_profile=task_profile,
                route_decision=route_decision,
                output_contract=output_contract,
                starter_config_builder=fake_builder,
                config_loader=fake_loader,
                run_output_dir_creator=fake_run_output_dir_creator,
                task_runner=fake_task_runner,
            )

            self.assertTrue(result.attempted)
            self.assertEqual(Path(result.prediction_path).read_text(encoding="utf-8"), "answer\n42\n")
            self.assertIsNotNone(result.verification_report)
            self.assertTrue(result.verification_report.all_passed)
            self.assertIsNotNone(result.semantic_review_report)
            self.assertIsNotNone(result.agent_review_report)
            self.assertIsNotNone(result.attempt_evaluation)
            self.assertEqual(result.attempt_evaluation.attempt_name, "retry")
            self.assertEqual(built_inputs["input_dir"], str(retry_task_dir))


if __name__ == "__main__":
    unittest.main()
