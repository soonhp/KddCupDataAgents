from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

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


@dataclass(slots=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class VerificationReport:
    task_id: str
    all_passed: bool
    checks: list[VerificationCheck]


def _fail(name: str, detail: str) -> VerificationCheck:
    return VerificationCheck(name=name, passed=False, detail=detail)


def _pass(name: str, detail: str) -> VerificationCheck:
    return VerificationCheck(name=name, passed=True, detail=detail)


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


def run_dual_verification(task_id: str, prediction_path: Path) -> VerificationReport:
    checks: list[VerificationCheck] = []

    if not prediction_path.exists():
        checks.append(_fail("contract_check", "prediction.csv missing"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks)

    if prediction_path.stat().st_size == 0:
        checks.append(_fail("readability_check", "prediction.csv is empty"))
        checks.append(_fail("contract_check", "header missing"))
        checks.append(_fail("sanity_check", "no data rows"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks)

    rows, readability_error = _read_csv_rows(prediction_path)
    if readability_error is not None:
        checks.append(readability_error)
        checks.append(_fail("contract_check", "csv could not be parsed"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks)

    checks.append(_pass("readability_check", "prediction.csv parsed as UTF-8 CSV"))
    checks.append(_run_contract_check(rows))
    checks.append(_run_sanity_check(rows))
    checks.append(_run_shape_check(rows))

    return VerificationReport(task_id=task_id, all_passed=all(check.passed for check in checks), checks=checks)


def report_to_dict(report: VerificationReport) -> dict:
    return asdict(report)
