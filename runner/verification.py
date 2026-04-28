from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_DATA_ROWS = 1_000_000
MAX_CELL_CHARS = 20_000
MAX_HEADER_CHARS = 512
SUSPICIOUS_ERROR_TOKENS = (
    "traceback",
    "exception",
    "error:",
    "api key",
    "authentication",
    "permission denied",
    "stack trace",
)
CONTRACT_COLUMN_KEYS = (
    "expected_columns",
    "output_columns",
    "columns",
    "headers",
    "prediction_columns",
)
CONTRACT_SCHEMA_KEYS = (
    "output_schema",
    "answer_schema",
    "prediction_schema",
    "schema",
)


@dataclass(slots=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class OutputContract:
    expected_columns: list[str]
    min_rows: int | None
    max_rows: int | None
    exact_columns: bool
    source: str


@dataclass(slots=True)
class VerificationReport:
    task_id: str
    all_passed: bool
    checks: list[VerificationCheck]
    output_contract: OutputContract | None = None


def _fail(name: str, detail: str) -> VerificationCheck:
    return VerificationCheck(name=name, passed=False, detail=detail)


def _pass(name: str, detail: str) -> VerificationCheck:
    return VerificationCheck(name=name, passed=True, detail=detail)


def _normalize_column_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _dedupe_columns(columns: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for column in columns:
        normalized = _normalize_column_name(str(column))
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(normalized)
    return output


def _extract_columns_from_schema_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Supports strings such as "answer", "name, score", or "columns: name, score".
        cleaned = value.strip()
        if not cleaned:
            return []
        cleaned = re.sub(r"^(columns?|headers?|output)\s*[:=]\s*", "", cleaned, flags=re.IGNORECASE)
        if "," in cleaned:
            return _dedupe_columns(cleaned.split(","))
        return _dedupe_columns([cleaned])
    if isinstance(value, list):
        columns: list[str] = []
        for item in value:
            if isinstance(item, str):
                columns.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("column") or item.get("field")
                if name is not None:
                    columns.append(str(name))
        return _dedupe_columns(columns)
    if isinstance(value, dict):
        for key in CONTRACT_COLUMN_KEYS:
            if key in value:
                columns = _extract_columns_from_schema_value(value[key])
                if columns:
                    return columns
        properties = value.get("properties")
        if isinstance(properties, dict):
            return _dedupe_columns([str(key) for key in properties.keys()])
        fields = value.get("fields")
        if isinstance(fields, list):
            return _extract_columns_from_schema_value(fields)
    return []


def _extract_question_columns(question: str) -> list[str]:
    if not question:
        return []
    patterns = [
        r"columns?\s*(?:named|are|:)\s*([A-Za-z0-9_ ,\-/]+)",
        r"headers?\s*(?:named|are|:)\s*([A-Za-z0-9_ ,\-/]+)",
        r"output\s+fields?\s*(?:named|are|:)\s*([A-Za-z0-9_ ,\-/]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        raw = re.split(r"\s+(?:and|with|where|for|from)\s+", raw, maxsplit=1, flags=re.IGNORECASE)[0]
        columns = _dedupe_columns(raw.split(","))
        if columns:
            return columns
    return []


def infer_output_contract(task_dir: Path) -> OutputContract | None:
    task_json = task_dir / "task.json"
    if not task_json.exists():
        return None
    try:
        payload: dict[str, Any] = json.loads(task_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    expected_columns: list[str] = []
    source = ""
    for key in CONTRACT_COLUMN_KEYS:
        if key in payload:
            expected_columns = _extract_columns_from_schema_value(payload[key])
            source = f"task_json.{key}"
            if expected_columns:
                break
    if not expected_columns:
        for key in CONTRACT_SCHEMA_KEYS:
            if key in payload:
                expected_columns = _extract_columns_from_schema_value(payload[key])
                source = f"task_json.{key}"
                if expected_columns:
                    break
    if not expected_columns:
        expected_columns = _extract_question_columns(str(payload.get("question") or ""))
        source = "task_json.question" if expected_columns else ""

    min_rows = payload.get("min_rows") or payload.get("expected_min_rows")
    max_rows = payload.get("max_rows") or payload.get("expected_max_rows")
    exact_columns = bool(payload.get("exact_columns", True))

    normalized_min_rows = int(min_rows) if isinstance(min_rows, int) and min_rows >= 0 else None
    normalized_max_rows = int(max_rows) if isinstance(max_rows, int) and max_rows >= 0 else None

    if not expected_columns and normalized_min_rows is None and normalized_max_rows is None:
        return None
    return OutputContract(
        expected_columns=expected_columns,
        min_rows=normalized_min_rows,
        max_rows=normalized_max_rows,
        exact_columns=exact_columns,
        source=source or "task_json",
    )


def _read_csv_rows(prediction_path: Path) -> tuple[list[list[str]], VerificationCheck | None]:
    try:
        with prediction_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle)), None
    except UnicodeDecodeError as exc:
        return [], _fail("readability_check", f"prediction.csv is not valid UTF-8: {exc}")
    except csv.Error as exc:
        return [], _fail("readability_check", f"prediction.csv parse error: {exc}")
    except OSError as exc:
        return [], _fail("readability_check", f"prediction.csv read error: {exc}")


def _run_contract_check(rows: list[list[str]]) -> VerificationCheck:
    if not rows:
        return _fail("contract_check", "header missing")
    if not rows[0]:
        return _fail("contract_check", "header missing")

    header = [cell.strip() for cell in rows[0]]
    if not any(header):
        return _fail("contract_check", "header has no non-empty columns")

    duplicate_headers = sorted({cell for cell in header if cell and header.count(cell) > 1})
    if duplicate_headers:
        return _fail("contract_check", f"duplicate header names: {duplicate_headers[:5]}")

    too_long_headers = [cell for cell in header if len(cell) > MAX_HEADER_CHARS]
    if too_long_headers:
        return _fail("contract_check", f"header name too long at {len(too_long_headers)} columns")

    width = len(rows[0])
    inconsistent = [index for index, row in enumerate(rows[1:], start=2) if len(row) != width]
    if inconsistent:
        return _fail("contract_check", f"inconsistent column width at rows {inconsistent[:5]}")

    return _pass("contract_check", "header/width consistent")


def _run_task_contract_check(rows: list[list[str]], output_contract: OutputContract | None) -> VerificationCheck:
    if output_contract is None:
        return _pass("task_contract_check", "no task-specific output contract found")
    if not rows or not rows[0]:
        return _fail("task_contract_check", "cannot validate task contract without header")

    header = [_normalize_column_name(cell).lower() for cell in rows[0]]
    data_row_count = max(len(rows) - 1, 0)

    if output_contract.expected_columns:
        expected = [_normalize_column_name(cell).lower() for cell in output_contract.expected_columns]
        missing = [column for column in expected if column not in header]
        if missing:
            return _fail("task_contract_check", f"missing expected columns from {output_contract.source}: {missing}")
        if output_contract.exact_columns and header != expected:
            return _fail(
                "task_contract_check",
                f"header does not exactly match {output_contract.source}: expected {expected}, got {header}",
            )

    if output_contract.min_rows is not None and data_row_count < output_contract.min_rows:
        return _fail("task_contract_check", f"expected at least {output_contract.min_rows} rows, got {data_row_count}")
    if output_contract.max_rows is not None and data_row_count > output_contract.max_rows:
        return _fail("task_contract_check", f"expected at most {output_contract.max_rows} rows, got {data_row_count}")

    return _pass("task_contract_check", f"task-specific contract satisfied from {output_contract.source}")


def _run_sanity_check(rows: list[list[str]]) -> VerificationCheck:
    data_rows = rows[1:] if rows else []
    if not data_rows:
        return _fail("sanity_check", "no data rows")

    if len(data_rows) > MAX_DATA_ROWS:
        return _fail("sanity_check", f"too many data rows ({len(data_rows)})")

    empty_row_count = 0
    too_long_cells = 0
    suspicious_cells = 0
    for row in data_rows:
        if all(not cell.strip() for cell in row):
            empty_row_count += 1
        for cell in row:
            stripped = cell.strip()
            if len(stripped) > MAX_CELL_CHARS:
                too_long_cells += 1
            lowered = stripped.lower()
            if any(token in lowered for token in SUSPICIOUS_ERROR_TOKENS):
                suspicious_cells += 1

    empty_ratio = empty_row_count / len(data_rows)
    unique_ratio = len({tuple(row) for row in data_rows}) / len(data_rows)

    if empty_ratio > 0.95:
        return _fail("sanity_check", f"too many empty rows ({empty_ratio:.2%})")
    if unique_ratio < 0.05 and len(data_rows) >= 20:
        return _fail("sanity_check", f"too many duplicates (unique ratio {unique_ratio:.2%})")
    if too_long_cells:
        return _fail("sanity_check", f"cell length limit exceeded in {too_long_cells} cells")
    if suspicious_cells:
        return _fail("sanity_check", f"suspicious error-like text detected in {suspicious_cells} cells")

    return _pass("sanity_check", f"empty ratio {empty_ratio:.2%}, unique ratio {unique_ratio:.2%}")


def _run_shape_check(rows: list[list[str]]) -> VerificationCheck:
    if not rows or not rows[0]:
        return _fail("shape_check", "cannot inspect shape without header")

    width = len(rows[0])
    data_row_count = max(len(rows) - 1, 0)
    if width > 1000:
        return _fail("shape_check", f"too many columns ({width})")
    if data_row_count == 1 and width == 1 and rows[1][0].strip() == "":
        return _fail("shape_check", "single empty answer cell fallback output")
    return _pass("shape_check", f"{data_row_count} data rows, {width} columns")


def run_dual_verification(
    task_id: str,
    prediction_path: Path,
    output_contract: OutputContract | None = None,
) -> VerificationReport:
    checks: list[VerificationCheck] = []

    if not prediction_path.exists():
        checks.append(_fail("contract_check", "prediction.csv missing"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks, output_contract=output_contract)

    if prediction_path.stat().st_size == 0:
        checks.append(_fail("readability_check", "prediction.csv is empty"))
        checks.append(_fail("contract_check", "header missing"))
        checks.append(_fail("sanity_check", "no data rows"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks, output_contract=output_contract)

    rows, readability_error = _read_csv_rows(prediction_path)
    if readability_error is not None:
        checks.append(readability_error)
        checks.append(_fail("contract_check", "csv could not be parsed"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks, output_contract=output_contract)

    checks.append(_pass("readability_check", "prediction.csv parsed as UTF-8 CSV"))
    checks.append(_run_contract_check(rows))
    checks.append(_run_task_contract_check(rows, output_contract))
    checks.append(_run_sanity_check(rows))
    checks.append(_run_shape_check(rows))

    return VerificationReport(
        task_id=task_id,
        all_passed=all(check.passed for check in checks),
        checks=checks,
        output_contract=output_contract,
    )


def report_to_dict(report: VerificationReport) -> dict:
    return asdict(report)
