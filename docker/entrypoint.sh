#!/usr/bin/env bash
set -euo pipefail

mkdir -p /output /logs
: > /logs/runtime.log

python -m runner.evaluation_runner \
  --input /input \
  --output /output \
  --logs /logs \
  2>&1 | tee -a /logs/runtime.log
