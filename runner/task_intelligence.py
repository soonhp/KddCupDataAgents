from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class TaskContextProfile:
    task_id: str
    csv_files: list[str]
    db_files: list[str]
    json_files: list[str]
    doc_files: list[str]
    knowledge_files: list[str]


@dataclass(slots=True)
class RouteDecision:
    route: str
    scores: dict[str, int]
    reasons: list[str]


def _list_relative_paths(paths: list[Path], base: Path) -> list[str]:
    return sorted(str(path.relative_to(base)) for path in paths)


def profile_task_context(task_dir: Path) -> TaskContextProfile:
    context_dir = task_dir / "context"
    if not context_dir.exists():
        return TaskContextProfile(
            task_id=task_dir.name,
            csv_files=[],
            db_files=[],
            json_files=[],
            doc_files=[],
            knowledge_files=[],
        )

    csv_files: list[Path] = []
    db_files: list[Path] = []
    json_files: list[Path] = []
    doc_files: list[Path] = []
    knowledge_files: list[Path] = []

    for path in context_dir.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        name = path.name.lower()
        if suffix == ".csv":
            csv_files.append(path)
        elif suffix in {".sqlite", ".db", ".duckdb"}:
            db_files.append(path)
        elif suffix == ".json":
            json_files.append(path)
        elif suffix in {".md", ".txt", ".pdf", ".docx"}:
            doc_files.append(path)

        if name == "knowledge.md":
            knowledge_files.append(path)

    return TaskContextProfile(
        task_id=task_dir.name,
        csv_files=_list_relative_paths(csv_files, task_dir),
        db_files=_list_relative_paths(db_files, task_dir),
        json_files=_list_relative_paths(json_files, task_dir),
        doc_files=_list_relative_paths(doc_files, task_dir),
        knowledge_files=_list_relative_paths(knowledge_files, task_dir),
    )


def decide_route(profile: TaskContextProfile) -> RouteDecision:
    scores = {
        "sql_first": 0,
        "python_first": 0,
        "document_first": 0,
    }
    reasons: list[str] = []

    if profile.db_files:
        scores["sql_first"] += 3
        reasons.append(f"db files detected ({len(profile.db_files)})")

    if profile.csv_files:
        scores["python_first"] += 2
        reasons.append(f"csv files detected ({len(profile.csv_files)})")

    if profile.json_files:
        scores["python_first"] += 1
        reasons.append(f"json files detected ({len(profile.json_files)})")

    if profile.doc_files:
        scores["document_first"] += 2
        reasons.append(f"doc files detected ({len(profile.doc_files)})")

    if profile.knowledge_files:
        scores["document_first"] += 2
        reasons.append("knowledge.md detected")

    route = max(scores, key=lambda key: scores[key])
    if all(value == 0 for value in scores.values()):
        route = "python_first"
        reasons.append("empty context fallback")

    return RouteDecision(route=route, scores=scores, reasons=reasons)


def normalize_prediction_csv(prediction_path: Path) -> None:
    null_tokens = {"null", "none", "nan", "na", "n/a"}

    if not prediction_path.exists() or prediction_path.stat().st_size == 0:
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text("answer\n\n", encoding="utf-8")
        return

    with prediction_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        rows = [["answer"], [""]]

    header = rows[0] or ["answer"]
    width = max(len(header), *(len(row) for row in rows[1:]), 1)

    def _normalize_cell(value: str) -> str:
        stripped = value.strip()
        if stripped.lower() in null_tokens:
            return ""
        return stripped

    normalized_rows: list[list[str]] = []
    normalized_header = header + [""] * (width - len(header))
    normalized_rows.append(normalized_header)

    for row in rows[1:]:
        padded = row + [""] * (width - len(row))
        normalized_rows.append([_normalize_cell(cell) for cell in padded])

    with prediction_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(normalized_rows)


def profile_to_dict(profile: TaskContextProfile) -> dict:
    return asdict(profile)


def route_to_dict(route: RouteDecision) -> dict:
    return asdict(route)
