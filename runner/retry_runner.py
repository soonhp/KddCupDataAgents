from __future__ import annotations

import csv
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from data_agent_baseline.config import load_app_config
from data_agent_baseline.run.runner import create_run_output_dir, run_single_task

from runner.agent_review import AgentReviewReport, run_agent_review
from runner.attempt_selector import AttemptEvaluation, build_attempt_evaluation
from runner.semantic_review import SemanticReviewReport, run_semantic_review
from runner.task_intelligence import normalize_prediction_csv
from runner.verification import OutputContract, VerificationReport, run_dual_verification


@dataclass(slots=True)
class RetryAttemptResult:
    attempted: bool
    prediction_path: str | None
    trace_path: str | None
    verification_report: VerificationReport | None
    semantic_review_report: SemanticReviewReport | None
    agent_review_report: AgentReviewReport | None
    attempt_evaluation: AttemptEvaluation | None


def _write_fallback_prediction_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["answer"])
        writer.writerow([""])


def run_retry_attempt(
    *,
    task_id: str,
    retry_task_dir: Path,
    task_output_dir: Path,
    artifact_root: Path,
    model_name: str,
    api_base: str,
    api_key: str,
    task_timeout_seconds: int,
    run_id: str | None,
    task_profile: Any,
    route_decision: Any,
    output_contract: OutputContract | None,
    starter_config_builder: Callable[..., Path],
    config_loader: Callable[[Path], Any] = load_app_config,
    run_output_dir_creator: Callable[..., tuple[Any, Path]] = create_run_output_dir,
    task_runner: Callable[..., Any] = run_single_task,
) -> RetryAttemptResult:
    retry_config_path = starter_config_builder(
        input_dir=retry_task_dir,
        artifact_dir=artifact_root,
        model_name=model_name,
        api_base=api_base,
        api_key=api_key,
        max_workers=1,
        task_timeout_seconds=task_timeout_seconds,
    )
    retry_config = config_loader(retry_config_path)
    _, retry_run_output_dir = run_output_dir_creator(retry_config.run.output_dir, run_id=run_id)
    retry_artifact = task_runner(task_id=task_id, config=retry_config, run_output_dir=retry_run_output_dir)

    retry_prediction_path = task_output_dir / "prediction.retry.csv"
    if retry_artifact.prediction_csv_path is not None and retry_artifact.prediction_csv_path.exists():
        shutil.copy2(retry_artifact.prediction_csv_path, retry_prediction_path)
    else:
        _write_fallback_prediction_csv(retry_prediction_path)

    normalize_prediction_csv(retry_prediction_path)
    retry_verification_report = run_dual_verification(task_id, retry_prediction_path, output_contract=output_contract)
    retry_semantic_review_report = run_semantic_review(
        task_id=task_id,
        task_profile=task_profile,
        route_decision=route_decision,
        verification_report=retry_verification_report,
        prediction_path=retry_prediction_path,
    )
    retry_agent_review_report = run_agent_review(
        task_id=task_id,
        task_profile=task_profile,
        route_decision=route_decision,
        verification_report=retry_verification_report,
    )
    retry_attempt_evaluation = build_attempt_evaluation(
        attempt_name="retry",
        verification_report=retry_verification_report,
        semantic_review_report=retry_semantic_review_report,
        agent_review_report=retry_agent_review_report,
    )

    return RetryAttemptResult(
        attempted=True,
        prediction_path=str(retry_prediction_path),
        trace_path=str(retry_artifact.trace_path) if retry_artifact.trace_path else None,
        verification_report=retry_verification_report,
        semantic_review_report=retry_semantic_review_report,
        agent_review_report=retry_agent_review_report,
        attempt_evaluation=retry_attempt_evaluation,
    )


def retry_attempt_result_to_dict(result: RetryAttemptResult) -> dict[str, Any]:
    return asdict(result)
