#!/usr/bin/env bash
set -euo pipefail

python -m runner.evaluation_runner \
  --input /input \
  --output /output \
  --logs /logs
