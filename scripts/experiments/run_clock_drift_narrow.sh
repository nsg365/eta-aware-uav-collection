#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Running narrow-window clock drift experiment (2s window)..."

python3 -m experiments.run_experiment \
    configs/test_clock_drift_narrow.toml \
    -j 1 \
    --results results/phase1_tests

echo "Narrow-window clock drift experiment completed."
