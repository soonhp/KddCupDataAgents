from __future__ import annotations

import argparse
import csv
import json
import signal
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from data_agent_baseline.config import load_app_config
from data_agent_baseline.run.runner import create_run_output_dir, run_single_task

from runner.agent_review import agent_review_report_to_dict, run_agent_review
from runner.failure_taxonomy import (
    classify_task_failure,
    failure_rollup_to_dict,
    failure_taxonomy_to_dict,
    rollup_failure_taxonomy,
)
from runner.repair_executor import execute_repair_plan, repair_execution_report_to_dict
from runner.repair_planner import build_repair_plan, repair_plan_to_dict
from runner.semantic_review import semantic_review_report_to_dict, run_semantic_review
from runner.task_intelligence import (
    decide_route,
    normalize_prediction_csv,
    profile_task_context,
    profile_to_dict,
    route_to_dict,
)
from runner.verification import infer_output_contract, report_to_dict, run_dual_verification


@dataclass(slots=True)
class TaskExecutionSummary:
    task_id: str
    succeeded: bool
    failure_reason: str | None
    elapsed_seconds: float | None
    prediction_path: str
    trace_path: str


def _write_run_summary(
    *,
    path: Path,
    run_id: str | None,
    input_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    summaries: list[TaskExecutionSummary],
    failure_taxonomies: list,
    interrupted: bool,
) -> None:
    failure_rollup = rollup_failure_taxonomy(failure_taxonomies)
    summary_payload = {
        "run_id": run_id,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "logs_dir": str(logs_dir),
        "task_count": len(summaries),
        "succeeded_task_count": sum(1 for item in summaries if item.succeeded),
        "tasks": [asdict(item) for item in summaries],
        "failure_taxonomy": [failure_taxonomy_to_dict(item) for item in failure_taxonomies],
        "failure_rollup": failure_rollup_to_dict(failure_rollup),
        "interrupted": interrupted,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _discover_task_ids(input_dir: Path) -> list[str]:
    task_ids: list[str] = []
    for child in sorted(input_dir.iterdir()):
        if not child.is_dir():
            continue
        if not child.name.startswith("task_"):
            continue
        if not (child / "task.json").exists():
            continue
        task_ids.append(child.name)
    return task_ids


def _write_fallback_prediction_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["answer"])
        writer.writerow([""])


def _load_elapsed_seconds(trace_path: Path) -> float | None:
    if not trace_path.exists():
        return None
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    elapsed = trace.get("e2e_elapsed_seconds")
    if isinstance(elapsed, (int, float)):
        return float(elapsed)
    return None


def _build_starter_config(
    *,
    input_dir: Path,
    artifact_dir: Path,
    model_name: str,
    api_base: str,
    api_key: str,
    max_workers: int,
    task_timeout_seconds: int,
) -> Path:
    config_payload = {
        "dataset": {"root_path": str(input_dir)},
        "agent": {
            "model": model_name,
            "api_base": api_base,
            "api_key": api_key,
            "max_steps": 16,
            "temperature": 0.0,
        },
        "run": {
            "output_dir": str(artifact_dir),
            "max_workers": max_workers,
            "task_timeout_seconds": task_timeout_seconds,
        },
    }
    config_path = artifact_dir / "starter_runtime_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config_payload, allow_unicode=True), encoding="utf-8")
    return config_path


def run_evaluation(
    *,
    input_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    model_name: str,
    api_base: str,
    api_key: str,
    max_workers: int,
    task_timeout_seconds: int,
    run_id: str | None,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    artifact_root = output_dir / "_artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    starter_config_path = _build_starter_config(
        input_dir=input_dir,
        artifact_dir=artifact_root,
        model_name=model_name,
        api_base=api_base,
        api_key=api_key,
        max_workers=max_workers,
        task_timeout_seconds=task_timeout_seconds,
    )
    config = load_app_config(starter_config_path)
    _, run_output_dir = create_run_output_dir(config.run.output_dir, run_id=run_id)

    task_ids = _discover_task_ids(input_dir)
    summaries: list[TaskExecutionSummary] = []
    failure_taxonomies: list = []
    run_summary_path = logs_dir / "run_summary.json"
    stop_requested = False

    def _handle_stop_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        signal_name = signal.Signals(signum).name
        (logs_dir / "runner.signal.log").write_text(
            f"{datetime.now(timezone.utc).isoformat()} received {signal_name}; "
            "runner will stop after current task.\n",
            encoding="utf-8",
        )

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)

    try:
        for task_id in task_ids:
            if stop_requested:
                break

            task_dir = input_dir / task_id
            task_profile = profile_task_context(task_dir)
            route_decision = decide_route(task_profile)
            output_contract = infer_output_contract(task_dir)

            artifact = run_single_task(task_id=task_id, config=config, run_output_dir=run_output_dir)

            task_output_dir = output_dir / task_id
            task_output_dir.mkdir(parents=True, exist_ok=True)
            prediction_path = task_output_dir / "prediction.csv"
            if artifact.prediction_csv_path is not None and artifact.prediction_csv_path.exists():
                shutil.copy2(artifact.prediction_csv_path, prediction_path)
            else:
                _write_fallback_prediction_csv(prediction_path)

            normalize_prediction_csv(prediction_path)
            verification_report = run_dual_verification(task_id, prediction_path, output_contract=output_contract)
            semantic_review_report = run_semantic_review(
                task_id=task_id,
                task_profile=task_profile,
                route_decision=route_decision,
                verification_report=verification_report,
                prediction_path=prediction_path,
            )
            agent_review_report = run_agent_review(
                task_id=task_id,
                task_profile=task_profile,
                route_decision=route_decision,
                verification_report=verification_report,
            )
            repair_plan = build_repair_plan(
                task_id=task_id,
                route_decision=route_decision,
                verification_report=verification_report,
                semantic_review_report=semantic_review_report,
                agent_review_report=agent_review_report,
            )
            repair_execution_report = execute_repair_plan(
                repair_plan=repair_plan,
                prediction_path=prediction_path,
                output_contract=output_contract,
            )
            if repair_execution_report.applied_count:
                normalize_prediction_csv(prediction_path)
                verification_report = run_dual_verification(task_id, prediction_path, output_contract=output_contract)
                semantic_review_report = run_semantic_review(
                    task_id=task_id,
                    task_profile=task_profile,
                    route_decision=route_decision,
                    verification_report=verification_report,
                    prediction_path=prediction_path,
                )
                agent_review_report = run_agent_review(
                    task_id=task_id,
                    task_profile=task_profile,
                    route_decision=route_decision,
                    verification_report=verification_report,
                )
                repair_plan = build_repair_plan(
                    task_id=task_id,
                    route_decision=route_decision,
                    verification_report=verification_report,
                    semantic_review_report=semantic_review_report,
                    agent_review_report=agent_review_report,
                )

            task_logs_dir = logs_dir / task_id
            task_logs_dir.mkdir(parents=True, exist_ok=True)

            trace_target_path = task_logs_dir / "trace.json"
            shutil.copy2(artifact.trace_path, trace_target_path)

            schema_memory_path = task_logs_dir / "schema_memory.json"
            schema_memory_path.write_text(
                json.dumps(profile_to_dict(task_profile), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            task_failure_taxonomy = classify_task_failure(
                task_id=task_id,
                succeeded=artifact.succeeded,
                failure_reason=artifact.failure_reason,
                verification_report=verification_report,
            )
            failure_taxonomies.append(task_failure_taxonomy)

            task_log_payload = {
                "task_id": task_id,
                "succeeded": artifact.succeeded,
                "failure_reason": artifact.failure_reason,
                "prediction_csv": str(prediction_path),
                "trace": str(trace_target_path),
                "schema_memory": str(schema_memory_path),
                "route_decision": route_to_dict(route_decision),
                "verification": report_to_dict(verification_report),
                "semantic_review": semantic_review_report_to_dict(semantic_review_report),
                "agent_review": agent_review_report_to_dict(agent_review_report),
                "repair_plan": repair_plan_to_dict(repair_plan),
                "repair_execution": repair_execution_report_to_dict(repair_execution_report),
                "failure_taxonomy": failure_taxonomy_to_dict(task_failure_taxonomy),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            (task_logs_dir / "task.log.json").write_text(
                json.dumps(task_log_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            summaries.append(
                TaskExecutionSummary(
                    task_id=task_id,
                    succeeded=artifact.succeeded,
                    failure_reason=artifact.failure_reason,
                    elapsed_seconds=_load_elapsed_seconds(trace_target_path),
                    prediction_path=str(prediction_path),
                    trace_path=str(trace_target_path),
                )
            )
            _write_run_summary(
                path=run_summary_path,
                run_id=run_id,
                input_dir=input_dir,
                output_dir=output_dir,
                logs_dir=logs_dir,
                summaries=summaries,
                failure_taxonomies=failure_taxonomies,
                interrupted=stop_requested,
            )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)

    _write_run_summary(
        path=run_summary_path,
        run_id=run_id,
        input_dir=input_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        summaries=summaries,
        failure_taxonomies=failure_taxonomies,
        interrupted=stop_requested,
    )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KDD DataAgent evaluation runner wrapper")
    parser.add_argument("--input", default="/input", type=Path, help="Input root containing task_<id> directories")
    parser.add_argument("--output", default="/output", type=Path, help="Output root for prediction files")
    parser.add_argument("--logs", default="/logs", type=Path, help="Logs root")
    parser.add_argument("--run-id", default=None, help="Optional run identifier")
    parser.add_argument("--max-workers", type=int, default=1, help="Task-level worker count")
    parser.add_argument("--task-timeout-seconds", type=int, default=900, help="Per-task timeout in seconds")
    parser.add_argument("--model-name", default=None, help="Model name (defaults to MODEL_NAME env)")
    parser.add_argument("--model-api-url", default=None, help="API base URL (defaults to MODEL_API_URL env)")
    parser.add_argument("--model-api-key", default=None, help="API key (defaults to MODEL_API_KEY env)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    import os

    model_name = args.model_name or os.environ.get("MODEL_NAME")
    api_base = args.model_api_url or os.environ.get("MODEL_API_URL")
    api_key = args.model_api_key or os.environ.get("MODEL_API_KEY")

    missing = [
        name
        for name, value in [("MODEL_NAME", model_name), ("MODEL_API_URL", api_base), ("MODEL_API_KEY", api_key)]
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required model settings: {', ' .join(missing)}")

    return run_evaluation(
        input_dir=args.input,
        output_dir=args.output,
        logs_dir=args.logs,
        model_name=model_name,
        api_base=api_base,
        api_key=api_key,
        max_workers=args.max_workers,
        task_timeout_seconds=args.task_timeout_seconds,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
