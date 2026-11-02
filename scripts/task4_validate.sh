#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/mlown/wsn-uav"

echo "======================================"
echo "TASK 4: RELIABILITY VALIDATION"
echo "======================================"

echo
echo "[1/4] Building ns-3..."
bash scripts/task4_build.sh

echo
echo "[2/4] Running Python tests..."
python3 -m pytest -q

echo
echo "[3/4] Running reliability experiment..."
python3 -m experiments.run_experiment configs/reliability_test.toml

echo
echo "[4/4] Analyzing reliability metrics..."
python3 scripts/analyze_reliability.py

echo
echo "======================================"
echo "VALIDATION COMMANDS COMPLETED"
echo "======================================"
echo "Please inspect the experiment metrics and analysis output."
