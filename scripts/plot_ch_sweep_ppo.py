#!/usr/bin/env python3
"""CH-count sweep plots with the Phase 3 PPO models added.

Same plots as scripts/plot_ch_sweep.py (its helpers and styling are copied here so the two
scripts can change independently), plus a fourth one:
UAV energy per delivered reading. Reads results/phase3_ch_sweep_*/runs.csv, made by
configs/phase3_ch_sweep_*.toml.

Usage:
  python3 scripts/plot_ch_sweep_ppo.py
  python3 scripts/plot_ch_sweep_ppo.py --results results --out results/phase3_ch_sweep_plots
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

REPO = Path(__file__).resolve().parents[1]

# A1 and A2 match the tour almost exactly, so only A3, A4 and A4P are drawn (all five are in
# the printed table).
VARIANTS: list[tuple[str, str, str, str]] = [
    ("tour",              "Tour (classical)",         "#2563eb", "o"),  # blue
    ("nearest_feasible",  "Nearest Feasible",         "#16a34a", "s"),  # green
    ("data_greedy",       "Data Greedy",              "#dc2626", "^"),  # red
    ("energy_data_score", "Energy-Data Score",        "#9333ea", "D"),  # purple
    ("ppo_A3",  "PPO A3 (adaptive window)", "#f59e0b", "v"),  # amber
    ("ppo_A4",  "PPO A4 (full reward)",     "#0f172a", "P"),  # near black
    ("ppo_A4P", "PPO A4P",                  "#64748b", "X"),  # slate
]


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


PPO_TABLE = ["tour", "ppo_A1", "ppo_A2", "ppo_A3", "ppo_A4", "ppo_A4P"]


def load_runs(results_root: Path, suffix: str = "") -> pd.DataFrame:
    frames = []
    for d in sorted(results_root.glob(f"phase3_ch_sweep_[0-9][0-9]{suffix}")):
        if not (d / "runs.csv").exists():
            continue
        df = pd.read_csv(d / "runs.csv")
        df["_target"] = int(d.name.split("_")[3])
        frames.append(df)
    if not frames:
        sys.exit(f"ERROR: no phase3_ch_sweep_*/runs.csv under {results_root}")
    df = add_derived_columns(pd.concat(frames, ignore_index=True))
    # UAV energy per delivered reading, in joules (total UAV energy is nearly flat because the
    # UAV flies or hovers for the whole run, so this shows the cost of each reading instead).
    df["uav_J_per_reading"] = df["uav_total_energy_kJ"] * 1000.0 / df["data.delivered"]
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=REPO / "results")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--suffix", default="",
                    help='results folder suffix, e.g. "_std" for the older std-1 m/s speed noise runs')
    a = ap.parse_args()
    out_dir = a.out or a.results / f"phase3_ch_sweep{a.suffix}_plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_runs(a.results, a.suffix)

    print(f"{'Variant':<20} {'Target':>6} {'Median #CH':>10} {'PDR%':>7} {'PDR - tour':>11}")
    tour = df[df.variant == "tour"].set_index(["_target", "run.seed"])["pdr_pct"]
    for (v, t), g in df[df.variant.isin(PPO_TABLE)].groupby(["variant", "_target"]):
        diff = g.set_index(["_target", "run.seed"])["pdr_pct"] - tour
        print(f"{v:<20} {t:>6} {g['run.num_clusters'].median():>10.1f} "
              f"{g['pdr_pct'].mean():>7.2f} {diff.mean():>+11.2f}")

    keys = {v[0] for v in VARIANTS}
    df = df[df.variant.isin(keys)]
    metrics = [
        ("pdr_pct",             "PDR vs Number of Cluster Heads", "PDR (%)"),
        ("uav_total_energy_kJ", "UAV Energy vs Number of Cluster Heads", "UAV total energy (kJ)"),
        ("ch_total_energy_J",   "CH Total Energy vs Number of Cluster Heads", "CH total energy (J)"),
        ("uav_J_per_reading",   "UAV Energy per Delivered Reading", "UAV energy per reading (J)"),
    ]
    for col, title, ylabel in metrics:
        fig, ax = plt.subplots(figsize=(8, 5))
        plot_metric(ax, compute_stats(df, col), title, ylabel)
        fig.tight_layout()
        fig.savefig(out_dir / f"{col}.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    for ax, (col, title, ylabel) in zip(axes.flat, metrics):
        plot_metric(ax, compute_stats(df, col), title, ylabel)
    fig.suptitle("CH-Count Sweep with PPO\n"
                 "1000 sensors · Gaussian hotspot · UAV speed uniform 9–11 m/s · 10 seeds each · error bars = ±1 SD",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_dir / "ch_sweep_ppo_combined.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlots saved to: {out_dir}")


if __name__ == "__main__":
    main()
