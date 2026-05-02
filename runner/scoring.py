from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

NULL_TOKENS = {"", "null", "none", "nan", "nat", "<na>"}
TWO_PLACES = Decimal("0.01")


@dataclass(slots=True)
class TaskScore:
    task_id: str
    score: float
    matched_columns: int
    gold_columns: int
    predicted_columns: int
    extra_columns: int
    recall: float
    penalty: float
    prediction_path: str
    gold_path: str
    prediction_exists: bool
    error: str | None = None


@dataclass(slots=True)
class ScoreSummary:
    total_score: float
    task_count: int
    missing_prediction_count: int
    lambda_penalty: float
    tasks: list[TaskScore]


def _normalize_numeric(value: str) -> str | None:
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return None
    if not decimal.is_finite():
        return ""
    return str(decimal.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def _normalize_date(value: str) -> str | None:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _normalize_datetime(value: str) -> str | None:
    if "T" not in value and " " not in value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.isoformat()
    utc_value = parsed.astimezone(timezone.utc)
    return utc_value.isoformat().replace("+00:00", "Z")


def normalize_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    stripped = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    if stripped.lower() in NULL_TOKENS:
        return ""

    numeric = _normalize_numeric(stripped)
    if numeric is not None:
        return numeric

    date_value = _normalize_date(stripped)
    if date_value is not None:
        return date_value

    datetime_value = _normalize_datetime(stripped)
    if datetime_value is not None:
        return datetime_value

    return stripped


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def _column_signatures(path: Path) -> tuple[Counter[tuple[str, ...]], int]:
    rows = _read_csv_rows(path)
    if not rows:
        return Counter(), 0

    width = len(rows[0])
    if width == 0:
        return Counter(), 0

    columns: list[list[str]] = [[] for _ in range(width)]
    for row in rows[1:]:
        normalized_row = list(row[:width])
        if len(normalized_row) < width:
            normalized_row.extend([""] * (width - len(normalized_row)))
        for index, cell in enumerate(normalized_row):
            columns[index].append(normalize_cell(cell))

    signatures = Counter(tuple(sorted(column)) for column in columns)
    return signatures, width


def score_task(
    *,
    task_id: str,
    prediction_path: Path,
    gold_path: Path,
    lambda_penalty: Decimal = Decimal("0"),
) -> TaskScore:
    if not gold_path.exists():
        return TaskScore(
            task_id=task_id,
            score=0.0,
            matched_columns=0,
            gold_columns=0,
            predicted_columns=0,
            extra_columns=0,
            recall=0.0,
            penalty=0.0,
            prediction_path=str(prediction_path),
            gold_path=str(gold_path),
            prediction_exists=prediction_path.exists(),
            error="gold.csv missing",
        )

    gold_signatures, gold_columns = _column_signatures(gold_path)
    if not prediction_path.exists():
        return TaskScore(
            task_id=task_id,
            score=0.0,
            matched_columns=0,
            gold_columns=gold_columns,
            predicted_columns=0,
            extra_columns=0,
            recall=0.0,
            penalty=0.0,
            prediction_path=str(prediction_path),
            gold_path=str(gold_path),
            prediction_exists=False,
            error="prediction.csv missing",
        )

    try:
        prediction_signatures, predicted_columns = _column_signatures(prediction_path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return TaskScore(
            task_id=task_id,
            score=0.0,
            matched_columns=0,
            gold_columns=gold_columns,
            predicted_columns=0,
            extra_columns=0,
            recall=0.0,
            penalty=0.0,
            prediction_path=str(prediction_path),
            gold_path=str(gold_path),
            prediction_exists=True,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    matched_columns = sum(
        min(prediction_signatures[signature], gold_signatures[signature])
        for signature in prediction_signatures
    )
    extra_columns = max(predicted_columns - matched_columns, 0)
    recall = Decimal(matched_columns) / Decimal(gold_columns) if gold_columns else Decimal("0")
    penalty = (
        lambda_penalty * (Decimal(extra_columns) / Decimal(predicted_columns))
        if predicted_columns
        else Decimal("0")
    )
    score = max(Decimal("0"), recall - penalty)

    return TaskScore(
        task_id=task_id,
        score=float(score),
        matched_columns=matched_columns,
        gold_columns=gold_columns,
        predicted_columns=predicted_columns,
        extra_columns=extra_columns,
        recall=float(recall),
        penalty=float(penalty),
        prediction_path=str(prediction_path),
        gold_path=str(gold_path),
        prediction_exists=True,
    )


def score_prediction_roots(
    *,
    prediction_root: Path,
    gold_root: Path,
    lambda_penalty: Decimal = Decimal("0"),
) -> ScoreSummary:
    tasks: list[TaskScore] = []
    for task_dir in sorted(gold_root.iterdir()):
        if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
            continue
        gold_path = task_dir / "gold.csv"
        if not gold_path.exists():
            continue
        prediction_path = prediction_root / task_dir.name / "prediction.csv"
        tasks.append(
            score_task(
                task_id=task_dir.name,
                prediction_path=prediction_path,
                gold_path=gold_path,
                lambda_penalty=lambda_penalty,
            )
        )

    total_score = sum(task.score for task in tasks) / len(tasks) if tasks else 0.0
    return ScoreSummary(
        total_score=total_score,
        task_count=len(tasks),
        missing_prediction_count=sum(1 for task in tasks if not task.prediction_exists),
        lambda_penalty=float(lambda_penalty),
        tasks=tasks,
    )


def summary_to_dict(summary: ScoreSummary) -> dict[str, Any]:
    return asdict(summary)


def write_summary_json(summary: ScoreSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary_to_dict(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_task_scores_csv(summary: ScoreSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "task_id",
        "score",
        "matched_columns",
        "gold_columns",
        "predicted_columns",
        "extra_columns",
        "recall",
        "penalty",
        "prediction_exists",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for task in summary.tasks:
            row = asdict(task)
            writer.writerow({field: row[field] for field in fields})
