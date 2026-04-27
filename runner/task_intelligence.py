from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SQL_SIGNALS = {
    "join",
    "group",
    "count",
    "sum",
    "average",
    "avg",
    "top",
    "rank",
    "filter",
    "where",
    "by",
    "per",
    "compare",
    "aggregate",
    "total",
}
PYTHON_SIGNALS = {
    "correlation",
    "trend",
    "time series",
    "forecast",
    "regression",
    "distribution",
    "variance",
    "median",
    "normalize",
    "calculate",
    "compute",
    "standard deviation",
    "std",
    "rolling",
}
DOCUMENT_SIGNALS = {
    "according to",
    "policy",
    "definition",
    "define",
    "rule",
    "manual",
    "guideline",
    "explain",
    "extract from document",
    "document",
    "based on the text",
}
MAX_SCHEMA_FILES_PER_TYPE = 20
MAX_PREVIEW_CHARS = 500
MAX_JSON_KEYS = 30
MAX_SQLITE_TABLES = 30
MAX_COLUMNS_PER_TABLE = 50


@dataclass(slots=True)
class TaskMetadata:
    task_id: str
    difficulty: str | None
    question: str
    missing_task_json: bool
    malformed_task_json: bool


@dataclass(slots=True)
class QuestionSignals:
    sql: list[str]
    python: list[str]
    document: list[str]


@dataclass(slots=True)
class TaskContextProfile:
    task_id: str
    csv_files: list[str]
    db_files: list[str]
    json_files: list[str]
    doc_files: list[str]
    knowledge_files: list[str]
    question: str = ""
    difficulty: str | None = None
    estimated_context_size_bytes: int = 0
    file_counts: dict[str, int] | None = None
    question_signals: dict[str, list[str]] | None = None
    schema_hints: dict[str, Any] | None = None
    risk_flags: list[str] | None = None


@dataclass(slots=True)
class RouteDecision:
    route: str
    scores: dict[str, int]
    reasons: list[str]
    recommended_tools: list[str]
    risk_flags: list[str]


def _list_relative_paths(paths: list[Path], base: Path) -> list[str]:
    return sorted(str(path.relative_to(base)) for path in paths)


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _find_signals(question: str, signals: set[str]) -> list[str]:
    normalized = _normalize_text(question)
    matched: list[str] = []
    for signal in sorted(signals):
        pattern = r"\b" + re.escape(signal.lower()) + r"\b"
        if " " in signal:
            if signal.lower() in normalized:
                matched.append(signal)
        elif re.search(pattern, normalized):
            matched.append(signal)
    return matched


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def infer_question_signals(question: str) -> QuestionSignals:
    return QuestionSignals(
        sql=_find_signals(question, SQL_SIGNALS),
        python=_find_signals(question, PYTHON_SIGNALS),
        document=_find_signals(question, DOCUMENT_SIGNALS),
    )


def question_signals_to_dict(signals: QuestionSignals) -> dict[str, list[str]]:
    return asdict(signals)


def load_task_metadata(task_dir: Path) -> TaskMetadata:
    task_json = task_dir / "task.json"
    if not task_json.exists():
        return TaskMetadata(
            task_id=task_dir.name,
            difficulty=None,
            question="",
            missing_task_json=True,
            malformed_task_json=False,
        )

    try:
        payload: dict[str, Any] = json.loads(task_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TaskMetadata(
            task_id=task_dir.name,
            difficulty=None,
            question="",
            missing_task_json=False,
            malformed_task_json=True,
        )

    raw_task_id = payload.get("task_id")
    raw_difficulty = payload.get("difficulty")
    raw_question = payload.get("question")

    return TaskMetadata(
        task_id=str(raw_task_id) if raw_task_id not in (None, "") else task_dir.name,
        difficulty=str(raw_difficulty) if raw_difficulty not in (None, "") else None,
        question=str(raw_question) if raw_question not in (None, "") else "",
        missing_task_json=False,
        malformed_task_json=False,
    )


def _inspect_csv_file(path: Path, base: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": _safe_relative(path, base),
        "size_bytes": _safe_file_size(path),
        "columns": [],
        "sample_row_count": 0,
        "error": None,
    }
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            info["columns"] = [str(column).strip() for column in header]
            sample_rows = [row for _, row in zip(range(5), reader)]
            info["sample_row_count"] = len(sample_rows)
    except Exception as exc:  # pragma: no cover - defensive profiling path
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


def _inspect_json_file(path: Path, base: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": _safe_relative(path, base),
        "size_bytes": _safe_file_size(path),
        "top_level_type": None,
        "top_level_keys": [],
        "sample_item_keys": [],
        "error": None,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        info["top_level_type"] = type(payload).__name__
        if isinstance(payload, dict):
            info["top_level_keys"] = [str(key) for key in list(payload.keys())[:MAX_JSON_KEYS]]
        elif isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                info["sample_item_keys"] = [str(key) for key in list(first.keys())[:MAX_JSON_KEYS]]
    except Exception as exc:  # pragma: no cover - defensive profiling path
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


def _inspect_sqlite_file(path: Path, base: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": _safe_relative(path, base),
        "size_bytes": _safe_file_size(path),
        "tables": [],
        "error": None,
    }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (table_name,) in table_rows[:MAX_SQLITE_TABLES]:
                columns = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                info["tables"].append(
                    {
                        "name": table_name,
                        "columns": [
                            {"name": column[1], "type": column[2]} for column in columns[:MAX_COLUMNS_PER_TABLE]
                        ],
                    }
                )
    except Exception as exc:  # pragma: no cover - defensive profiling path
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


def _inspect_doc_file(path: Path, base: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": _safe_relative(path, base),
        "size_bytes": _safe_file_size(path),
        "suffix": path.suffix.lower(),
        "preview": "",
        "error": None,
    }
    if path.suffix.lower() not in {".md", ".txt"}:
        return info
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        info["preview"] = _normalize_text(text)[:MAX_PREVIEW_CHARS]
    except Exception as exc:  # pragma: no cover - defensive profiling path
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


def build_schema_hints(
    *,
    task_dir: Path,
    csv_files: list[Path],
    db_files: list[Path],
    json_files: list[Path],
    doc_files: list[Path],
) -> dict[str, Any]:
    return {
        "csv": [_inspect_csv_file(path, task_dir) for path in sorted(csv_files)[:MAX_SCHEMA_FILES_PER_TYPE]],
        "db": [_inspect_sqlite_file(path, task_dir) for path in sorted(db_files)[:MAX_SCHEMA_FILES_PER_TYPE]],
        "json": [_inspect_json_file(path, task_dir) for path in sorted(json_files)[:MAX_SCHEMA_FILES_PER_TYPE]],
        "doc": [_inspect_doc_file(path, task_dir) for path in sorted(doc_files)[:MAX_SCHEMA_FILES_PER_TYPE]],
    }


def _empty_schema_hints() -> dict[str, Any]:
    return {"csv": [], "db": [], "json": [], "doc": []}


def profile_task_context(task_dir: Path) -> TaskContextProfile:
    metadata = load_task_metadata(task_dir)
    context_dir = task_dir / "context"
    risk_flags: list[str] = []
    if metadata.missing_task_json:
        risk_flags.append("missing_task_json")
    if metadata.malformed_task_json:
        risk_flags.append("malformed_task_json")
    if not metadata.question:
        risk_flags.append("missing_question")

    if not context_dir.exists():
        risk_flags.append("missing_context_dir")
        signals = infer_question_signals(metadata.question)
        return TaskContextProfile(
            task_id=metadata.task_id,
            csv_files=[],
            db_files=[],
            json_files=[],
            doc_files=[],
            knowledge_files=[],
            question=metadata.question,
            difficulty=metadata.difficulty,
            estimated_context_size_bytes=0,
            file_counts={"csv": 0, "db": 0, "json": 0, "doc": 0, "knowledge": 0},
            question_signals=question_signals_to_dict(signals),
            schema_hints=_empty_schema_hints(),
            risk_flags=risk_flags,
        )

    csv_files: list[Path] = []
    db_files: list[Path] = []
    json_files: list[Path] = []
    doc_files: list[Path] = []
    knowledge_files: list[Path] = []
    estimated_context_size_bytes = 0

    for path in context_dir.rglob("*"):
        if not path.is_file():
            continue
        estimated_context_size_bytes += _safe_file_size(path)
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

    if not any([csv_files, db_files, json_files, doc_files, knowledge_files]):
        risk_flags.append("empty_context")

    signals = infer_question_signals(metadata.question)
    file_counts = {
        "csv": len(csv_files),
        "db": len(db_files),
        "json": len(json_files),
        "doc": len(doc_files),
        "knowledge": len(knowledge_files),
    }

    return TaskContextProfile(
        task_id=metadata.task_id,
        csv_files=_list_relative_paths(csv_files, task_dir),
        db_files=_list_relative_paths(db_files, task_dir),
        json_files=_list_relative_paths(json_files, task_dir),
        doc_files=_list_relative_paths(doc_files, task_dir),
        knowledge_files=_list_relative_paths(knowledge_files, task_dir),
        question=metadata.question,
        difficulty=metadata.difficulty,
        estimated_context_size_bytes=estimated_context_size_bytes,
        file_counts=file_counts,
        question_signals=question_signals_to_dict(signals),
        schema_hints=build_schema_hints(
            task_dir=task_dir,
            csv_files=csv_files,
            db_files=db_files,
            json_files=json_files,
            doc_files=doc_files,
        ),
        risk_flags=risk_flags,
    )


def _signals(profile: TaskContextProfile, key: str) -> list[str]:
    if not profile.question_signals:
        return []
    values = profile.question_signals.get(key, [])
    return list(values) if isinstance(values, list) else []


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def decide_route(profile: TaskContextProfile) -> RouteDecision:
    scores = {
        "sql_first": 0,
        "python_first": 0,
        "document_first": 0,
        "hybrid_sql_python": 0,
        "hybrid_doc_table": 0,
    }
    reasons: list[str] = []
    recommended_tools: list[str] = []
    risk_flags = list(profile.risk_flags or [])

    sql_signals = _signals(profile, "sql")
    python_signals = _signals(profile, "python")
    document_signals = _signals(profile, "document")

    if profile.db_files:
        scores["sql_first"] += 4
        scores["hybrid_sql_python"] += 2
        recommended_tools.append("sqlite")
        reasons.append(f"db files detected ({len(profile.db_files)})")

    if profile.csv_files:
        scores["python_first"] += 3
        scores["hybrid_sql_python"] += 1
        recommended_tools.extend(["pandas", "python"])
        reasons.append(f"csv files detected ({len(profile.csv_files)})")

    if profile.json_files:
        scores["python_first"] += 2
        recommended_tools.append("python_json")
        reasons.append(f"json files detected ({len(profile.json_files)})")

    if profile.doc_files:
        scores["document_first"] += 3
        scores["hybrid_doc_table"] += 2
        recommended_tools.append("document_reader")
        reasons.append(f"doc files detected ({len(profile.doc_files)})")

    if profile.knowledge_files:
        scores["document_first"] += 3
        scores["hybrid_doc_table"] += 2
        reasons.append("knowledge.md detected")

    if sql_signals:
        scores["sql_first"] += 2 + len(sql_signals)
        scores["hybrid_sql_python"] += len(sql_signals)
        reasons.append(f"sql signals detected: {', '.join(sql_signals)}")

    if python_signals:
        scores["python_first"] += 2 + len(python_signals)
        scores["hybrid_sql_python"] += len(python_signals)
        reasons.append(f"python signals detected: {', '.join(python_signals)}")

    if document_signals:
        scores["document_first"] += 2 + len(document_signals)
        scores["hybrid_doc_table"] += len(document_signals)
        reasons.append(f"document signals detected: {', '.join(document_signals)}")

    has_table_context = bool(profile.db_files or profile.csv_files or profile.json_files)
    has_document_context = bool(profile.doc_files or profile.knowledge_files)

    if profile.db_files and profile.csv_files:
        scores["hybrid_sql_python"] += 3
        reasons.append("db and csv context both present")

    if has_document_context and has_table_context:
        scores["hybrid_doc_table"] += 3
        reasons.append("document and table context both present")

    if profile.db_files and python_signals:
        scores["hybrid_sql_python"] += 3
        reasons.append("db context requires python/statistical signal handling")

    if has_document_context and sql_signals:
        scores["hybrid_doc_table"] += 2
        reasons.append("document context with table-style question signals")

    if not has_table_context and not has_document_context:
        scores["python_first"] += 1
        risk_flags.append("no_supported_context_files")
        reasons.append("empty context fallback")

    if profile.difficulty and profile.difficulty.lower() in {"hard", "advanced", "expert"}:
        risk_flags.append("high_difficulty")
        reasons.append(f"difficulty={profile.difficulty}")

    route = max(scores, key=lambda key: scores[key])
    if all(value == 0 for value in scores.values()):
        route = "python_first"
        reasons.append("zero-score fallback")
        risk_flags.append("zero_score_route")

    return RouteDecision(
        route=route,
        scores=scores,
        reasons=_unique(reasons),
        recommended_tools=_unique(recommended_tools),
        risk_flags=_unique(risk_flags),
    )


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
