#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Running clock drift experiment (5s window)..."

python3 -m experiments.run_experiment \
    configs/test_clock_drift.toml \
    -j 1 \
    --results results/phase1_tests

echo "Clock drift experiment completed."
