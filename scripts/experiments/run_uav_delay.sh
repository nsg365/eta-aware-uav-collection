#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Running UAV delay experiment..."

python3 -m experiments.run_experiment \
    configs/test_uav_delay.toml \
    -j 1 \
    --results results/phase1_tests

echo "UAV delay experiment completed."
