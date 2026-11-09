#!/usr/bin/env bash
set -euo pipefail

cd ~/mlown/wsn-uav
source .venv/bin/activate

CONFIG="configs/reliability_lowrate_long.toml"

echo "Running extended low-rate reliability experiment..."
python3 -m experiments.run_experiment "$CONFIG"

echo "Experiment completed."
echo "Results: results/reliability_lowrate_long/"
