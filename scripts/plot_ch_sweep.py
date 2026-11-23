#!/usr/bin/env python3
"""Plot PDR, UAV energy, and CH energy vs number of cluster heads.

Reads results from the CH-count sweep experiments (produced by run_ch_sweep.py).
Generates three publication-quality plots, one per metric.

Expected results layout:
  results/ch_sweep_target_05/runs.csv
  results/ch_sweep_target_10/runs.csv
  results/ch_sweep_target_15/runs.csv
  results/ch_sweep_target_20/runs.csv

Metrics plotted:
  1. PDR (%) vs number of cluster heads
  2. UAV total energy (kJ) vs number of cluster heads
     = flight_energy_J_est + hover_energy_J_est
  3. CH total energy (J) vs number of cluster heads
     = primary_ch_mean_J × run.num_clusters   (total energy across all CHs)

Usage:
  python3 scripts/plot_ch_sweep.py
  python3 scripts/plot_ch_sweep.py --results results --out results/ch_sweep_plots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Routing variants: (runs.csv column value, display label, colour, marker)
# ---------------------------------------------------------------------------
VARIANTS: list[tuple[str, str, str, str]] = [
    ("tour",              "Tour (classical)",     "#2563eb", "o"),   # blue
    ("nearest_feasible",  "Nearest Feasible",     "#16a34a", "s"),   # green
    ("data_greedy",       "Data Greedy",          "#dc2626", "^"),   # red
    ("energy_data_score", "Energy-Data Score",    "#9333ea", "D"),   # purple
]

VARIANT_KEYS = {v[0] for v in VARIANTS}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_runs(results_root: Path) -> pd.DataFrame:
    """Load and concatenate runs.csv from all ch_sweep_target_* directories."""
    dirs = sorted(results_root.glob("ch_sweep_target_*"))
    if not dirs:
        sys.exit(
            f"ERROR: No ch_sweep_target_* directories found under {results_root}.\n"
            "Run experiments first:\n"
            "  python3 scripts/run_ch_sweep.py --targets 5 10 15 20"
        )

    frames: list[pd.DataFrame] = []
    for d in dirs:
        csv_path = d / "runs.csv"
        if not csv_path.exists():
            print(f"WARNING: {csv_path} not found, skipping.", file=sys.stderr)
            continue
        df = pd.read_csv(csv_path)
        # Tag with the target label extracted from directory name, e.g. "05" → 5
        label = d.name.replace("ch_sweep_target_", "")
        df["_target"] = int(label)
        frames.append(df)

    if not frames:
        sys.exit("ERROR: No runs.csv files could be loaded.")

    return pd.concat(frames, ignore_index=True)


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add computed metric columns used for plotting."""
    # UAV total energy in kJ
    df["uav_total_energy_kJ"] = (
        df["uav.flight_energy_J_est"] + df["uav.hover_energy_J_est"]
    ) / 1_000.0

    # CH total energy in J  =  mean CH energy × number of clusters
    df["ch_total_energy_J"] = (
        df["energy.primary_ch_mean_J"] * df["run.num_clusters"]
    )

    # PDR as percentage
    df["pdr_pct"] = df["data.pdr"] * 100.0

    return df


# ---------------------------------------------------------------------------
# Per-group statistics
# ---------------------------------------------------------------------------

def compute_stats(df: pd.DataFrame, metric_col: str) -> pd.DataFrame:
    """Return mean ± std of metric_col grouped by (variant, _target)."""
    rows = []
    for (variant, target), grp in df.groupby(["variant", "_target"]):
        vals = grp[metric_col].dropna()
        rows.append({
            "variant": variant,
            "target": target,
            # Use actual median num_clusters from the runs as x-axis value
            "num_clusters_median": grp["run.num_clusters"].median(),
            "num_clusters_mean": grp["run.num_clusters"].mean(),
            "mean": vals.mean(),
            "std": vals.std(ddof=1) if len(vals) > 1 else 0.0,
            "n": len(vals),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _style_ax(ax: plt.Axes, title: str, ylabel: str, x_ticks: list[float]) -> None:
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.set_xlabel("Number of cluster heads (median across seeds)", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_xticks(x_ticks)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.grid(axis="x", linestyle=":", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=10, framealpha=0.85, loc="best")


def plot_metric(
    ax: plt.Axes,
    stats: pd.DataFrame,
    title: str,
    ylabel: str,
    capsize: int = 4,
) -> None:
    x_ticks: list[float] = []

    for vkey, vlabel, color, marker in VARIANTS:
        sub = stats[stats["variant"] == vkey].sort_values("num_clusters_median")
        if sub.empty:
            continue

        xs = sub["num_clusters_median"].tolist()
        ys = sub["mean"].tolist()
        errs = sub["std"].tolist()
        x_ticks.extend(xs)

        ax.errorbar(
            xs, ys, yerr=errs,
            label=vlabel,
            color=color,
            marker=marker,
            markersize=7,
            linewidth=1.8,
            capsize=capsize,
            capthick=1.5,
            elinewidth=1.2,
            zorder=3,
        )
        # Subtle shaded band
        ax.fill_between(
            xs,
            [y - e for y, e in zip(ys, errs)],
            [y + e for y, e in zip(ys, errs)],
            color=color, alpha=0.10,
        )

    _style_ax(ax, title, ylabel, sorted(set(x_ticks)))


def make_plots(df: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = [
        ("pdr_pct",             "PDR vs Number of Cluster Heads",
         "PDR (%)"),
        ("uav_total_energy_kJ", "UAV Energy Consumption vs Number of Cluster Heads",
         "UAV total energy (kJ)"),
        ("ch_total_energy_J",   "CH Total Energy vs Number of Cluster Heads",
         "CH total energy (J)"),
    ]

    # Individual plots
    for col, title, ylabel in metrics:
        stats = compute_stats(df, col)
        fig, ax = plt.subplots(figsize=(8, 5))
        plot_metric(ax, stats, title, ylabel)
        fig.tight_layout()
        fname = col.replace(".", "_") + ".png"
        fig.savefig(out_dir / fname, dpi=200, bbox_inches="tight")
        print(f"Saved: {out_dir / fname}")
        plt.close(fig)

    # Combined 3-panel figure
    fig, axes = plt.subplots(1, 3, figsize=(21, 5.5))
    for ax, (col, title, ylabel) in zip(axes, metrics):
        stats = compute_stats(df, col)
        plot_metric(ax, stats, title, ylabel)
    fig.suptitle(
        "CH-Count Sweep: Routing Variants Comparison\n"
        "1000 sensors · Gaussian hotspot · 10 seeds each · error bars = ±1 SD",
        fontsize=13, fontweight="bold", y=1.01,
    )
    fig.tight_layout()
    combined_path = out_dir / "ch_sweep_combined.png"
    fig.savefig(combined_path, dpi=200, bbox_inches="tight")
    print(f"Saved: {combined_path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--results", type=Path, default=REPO / "results",
        help="Root results directory (default: results/)",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="Output directory for plots (default: results/ch_sweep_plots/)",
    )
    a = ap.parse_args()

    out_dir = a.out if a.out else a.results / "ch_sweep_plots"

    print(f"Loading results from: {a.results}")
    df = load_all_runs(a.results)
    df = add_derived_columns(df)

    # Filter to known variants only
    present = df["variant"].unique()
    unknown = set(present) - VARIANT_KEYS
    if unknown:
        print(f"Note: ignoring unexpected variant(s): {unknown}", file=sys.stderr)
    df = df[df["variant"].isin(VARIANT_KEYS)].copy()

    n_runs = len(df)
    targets = sorted(df["_target"].unique())
    print(f"Loaded {n_runs} rows across targets {targets}")

    # Quick summary table
    print()
    print(f"{'Variant':<22} {'Target':>7} {'Seeds':>6} {'Median #CH':>11} {'PDR%':>8}")
    print("-" * 60)
    for (v, t), g in df.groupby(["variant", "_target"]):
        print(f"{v:<22} {t:>7} {len(g):>6} "
              f"{g['run.num_clusters'].median():>11.1f} "
              f"{g['pdr_pct'].mean():>8.2f}")

    make_plots(df, out_dir)
    print(f"\nAll plots saved to: {out_dir}")


if __name__ == "__main__":
    main()
