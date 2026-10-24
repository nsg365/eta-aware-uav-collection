"""Aggregate runs.csv into mean and 95% confidence intervals per (network size, variant).

CI: mean +/- t_{0.975, n-1} * s / sqrt(n) over seeds (Student t; seeds are independent runs).
Censored lifetimes (no death within the horizon) are reported as the fraction censored, not
averaged as if they were observed deaths.

Usage:  python3 -m analysis.aggregate results/<experiment>/runs.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

METRICS = [
    "data.pdr",
    "data.overflow_ratio",
    "energy.primary_ch_mean_J",
    "energy.sensor_mean_J",
    "energy.jain_cluster_residual",
    "wake.ch_wifi_awake_fraction",
    "wake.meeting_success_rate",
    "wake.mean_window_listen_s",
    "eta.mean_signed_error_s",
    "uav.distance_m",
    "uav.hover_time_s",
    "uav.failed_contacts",
    "lifetime.first_node_death_s",
    "run.wall_time_s",
]
CENSOR = {"lifetime.first_node_death_s": "lifetime.first_node_death_censored"}


def mean_ci(x: pd.Series) -> tuple[float, float, int]:
    x = pd.to_numeric(x, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(x)
    if n == 0:
        return np.nan, np.nan, 0
    if n == 1:
        return float(x[0]), np.nan, 1
    half = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return float(x.mean()), float(half), n


def summarise(runs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (n, variant), g in runs.groupby(["run.num_sensors", "variant"]):
        row = {"num_sensors": n, "variant": variant, "runs": len(g)}
        for m in METRICS:
            if m not in g:
                continue
            mean, half, k = mean_ci(g[m])
            row[f"{m}.mean"] = mean
            row[f"{m}.ci95"] = half
            if m in CENSOR and CENSOR[m] in g:
                row[f"{m}.censored_frac"] = g[CENSOR[m]].astype(str).str.lower().eq("true").mean()
        rows.append(row)
    return pd.DataFrame(rows)


def to_markdown(summary: pd.DataFrame, metrics: list[str]) -> str:
    head = "| N | variant | " + " | ".join(m.split(".", 1)[1] for m in metrics) + " |"
    sep = "|---|---|" + "---|" * len(metrics)
    lines = [head, sep]
    for _, r in summary.iterrows():
        cells = []
        for m in metrics:
            mean, half = r.get(f"{m}.mean", np.nan), r.get(f"{m}.ci95", np.nan)
            cell = "-" if pd.isna(mean) else f"{mean:.3g}" + ("" if pd.isna(half) else f" ± {half:.2g}")
            if f"{m}.censored_frac" in r and r[f"{m}.censored_frac"] > 0:
                cell += f" ({r[f'{m}.censored_frac']:.0%} cens.)"
            cells.append(cell)
        lines.append(f"| {r['num_sensors']} | {r['variant']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", type=Path)
    a = ap.parse_args()
    runs = pd.read_csv(a.runs)
    summary = summarise(runs)
    out = a.runs.with_name("summary.csv")
    summary.to_csv(out, index=False)
    table = to_markdown(summary, ["data.pdr", "energy.primary_ch_mean_J", "wake.ch_wifi_awake_fraction",
                                  "wake.meeting_success_rate", "uav.hover_time_s",
                                  "lifetime.first_node_death_s"])
    a.runs.with_name("summary.md").write_text(table + "\n")
    print(table)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
