from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


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


def run_dual_verification(task_id: str, prediction_path: Path) -> VerificationReport:
    checks: list[VerificationCheck] = []

    if not prediction_path.exists():
        checks.append(VerificationCheck(name="contract_check", passed=False, detail="prediction.csv missing"))
        return VerificationReport(task_id=task_id, all_passed=False, checks=checks)

    with prediction_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    # Contract check: header exists and each row has same column count.
    if not rows or not rows[0]:
        checks.append(VerificationCheck(name="contract_check", passed=False, detail="header missing"))
    else:
        width = len(rows[0])
        inconsistent = [index for index, row in enumerate(rows[1:], start=2) if len(row) != width]
        if inconsistent:
            checks.append(
                VerificationCheck(
                    name="contract_check",
                    passed=False,
                    detail=f"inconsistent column width at rows {inconsistent[:5]}",
                )
            )
        else:
            checks.append(VerificationCheck(name="contract_check", passed=True, detail="header/width consistent"))

    # Sanity check: avoid all-empty output and duplicate row explosion.
    data_rows = rows[1:] if rows else []
    if not data_rows:
        checks.append(VerificationCheck(name="sanity_check", passed=False, detail="no data rows"))
    else:
        empty_row_count = 0
        for row in data_rows:
            if all(not cell.strip() for cell in row):
                empty_row_count += 1

        empty_ratio = empty_row_count / len(data_rows)
        unique_ratio = len({tuple(row) for row in data_rows}) / len(data_rows)

        if empty_ratio > 0.95:
            checks.append(
                VerificationCheck(
                    name="sanity_check",
                    passed=False,
                    detail=f"too many empty rows ({empty_ratio:.2%})",
                )
            )
        elif unique_ratio < 0.05 and len(data_rows) >= 20:
            checks.append(
                VerificationCheck(
                    name="sanity_check",
                    passed=False,
                    detail=f"too many duplicates (unique ratio {unique_ratio:.2%})",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    name="sanity_check",
                    passed=True,
                    detail=f"empty ratio {empty_ratio:.2%}, unique ratio {unique_ratio:.2%}",
                )
            )

    return VerificationReport(task_id=task_id, all_passed=all(check.passed for check in checks), checks=checks)


def report_to_dict(report: VerificationReport) -> dict:
    return asdict(report)
