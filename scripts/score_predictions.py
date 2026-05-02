#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runner.scoring import (
    score_prediction_roots,
    summary_to_dict,
    write_summary_json,
    write_task_scores_csv,
)


def _decimal(value: str) -> Decimal:
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal value: {value}") from exc
    if decimal < 0:
        raise argparse.ArgumentTypeError("--lambda-penalty must be non-negative")
    return decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score DataAgent-Bench predictions against public gold files.")
    parser.add_argument("--prediction-root", required=True, type=Path, help="Root containing task_<id>/prediction.csv")
    parser.add_argument("--gold-root", required=True, type=Path, help="Root containing task_<id>/gold.csv")
    parser.add_argument(
        "--lambda-penalty",
        default=Decimal("0"),
        type=_decimal,
        help="Extra-column penalty weight. Official rules do not publish this value; default is 0.",
    )
    parser.add_argument("--json-output", type=Path, help="Optional path for a JSON score summary")
    parser.add_argument("--csv-output", type=Path, help="Optional path for per-task CSV scores")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = score_prediction_roots(
        prediction_root=args.prediction_root,
        gold_root=args.gold_root,
        lambda_penalty=args.lambda_penalty,
    )
    if args.json_output:
        write_summary_json(summary, args.json_output)
    if args.csv_output:
        write_task_scores_csv(summary, args.csv_output)
    print(json.dumps(summary_to_dict(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
