#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

python3 - <<'PY'
import pandas as pd

files = {
    "5s_window": "results/phase1_tests/uav_delay_test/runs.csv",
    "2s_window": "results/phase1_tests/clock_drift_narrow_test/runs.csv",
}

cols = [
    "variant",
    "seed_cfg",
    "wake.windows_scheduled",
    "wake.windows_met",
    "wake.windows_missed",
    "wake.missed_window_fraction",
    "wake.mean_window_listen_s",
    "wake.ch_wifi_awake_fraction",
    "eta.mae_s",
    "eta.late_beyond_window_frac",
]

for name, path in files.items():
    df = pd.read_csv(path)
    df = df[df["variant"].isin(["no_clock_drift", "clock_drift_5s"])]

    print(f"\n{'='*75}")
    print(name)
    print("="*75)
    print(df[cols].to_string(index=False))
PY
