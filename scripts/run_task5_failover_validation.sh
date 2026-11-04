#!/usr/bin/env bash
set -euo pipefail

CONFIG="configs/task5_failover_validation.toml"

echo "Starting Task 5 failover validation..."
python3 -m experiments.run_experiment "$CONFIG"

echo "Results: results/task5_failover_validation/"
