
"""
Generate ETA quantile experiment figures directly from runs.csv.

Outputs:
1. PDR vs ETA quantile
2. Primary CH energy vs ETA quantile
3. Meeting success vs ETA quantile
4. UAV hover time vs ETA quantile
5. Combined four-metric comparison
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats


METRICS = {
    "data.pdr": {
        "title": "Packet Delivery Ratio",
        "ylabel": "PDR",
        "filename": "eta_pdr.png",
    },
    "energy.primary_ch_mean_J": {
        "title": "Primary CH Mean Energy",
        "ylabel": "Energy (J)",
        "filename": "eta_primary_ch_energy.png",
    },
    "wake.meeting_success_rate": {
        "title": "UAV Meeting Success Rate",
        "ylabel": "Meeting success rate",
        "filename": "eta_meeting_success.png",
    },
    "uav.hover_time_s": {
        "title": "UAV Hover Time",
        "ylabel": "Hover time (s)",
        "filename": "eta_hover_time.png",
    },
}

ORDER = ["p80", "p90", "p95", "p99"]


def mean_ci(values):
    values = pd.to_numeric(values, errors="coerce").dropna()
    n = len(values)

    if n == 0:
        return np.nan, np.nan, np.nan

    mean = values.mean()

    if n < 2:
        return mean, np.nan, np.nan

    sem = stats.sem(values)
    margin = stats.t.ppf(0.975, n - 1) * sem

    return mean, mean - margin, mean + margin


def load_data(path):
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)

    required = {"variant", "run.seed", *METRICS.keys()}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df = df[df["variant"].isin(ORDER)].copy()

    if set(df["variant"].unique()) != set(ORDER):
        raise ValueError("Expected p80, p90, p95 and p99 variants.")

    return df


def plot_metric(df, metric, info, output_dir):
    means = []
    lower_errors = []
    upper_errors = []

    for variant in ORDER:
        values = df.loc[df["variant"] == variant, metric]
        mean, low, high = mean_ci(values)

        means.append(mean)
        lower_errors.append(mean - low if np.isfinite(low) else 0)
        upper_errors.append(high - mean if np.isfinite(high) else 0)

    x = np.arange(len(ORDER))

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.errorbar(
        x,
        means,
        yerr=[lower_errors, upper_errors],
        marker="o",
        capsize=5,
        linewidth=2,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(ORDER)
    ax.set_xlabel("ETA quantile")
    ax.set_ylabel(info["ylabel"])
    ax.set_title(info["title"])
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_dir / info["filename"], dpi=300)
    plt.close(fig)


def plot_combined(df, output_dir):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    axes = axes.flatten()

    x = np.arange(len(ORDER))

    for ax, (metric, info) in zip(axes, METRICS.items()):
        means = []
        lower_errors = []
        upper_errors = []

        for variant in ORDER:
            values = df.loc[df["variant"] == variant, metric]
            mean, low, high = mean_ci(values)

            means.append(mean)
            lower_errors.append(mean - low if np.isfinite(low) else 0)
            upper_errors.append(high - mean if np.isfinite(high) else 0)

        ax.errorbar(
            x,
            means,
            yerr=[lower_errors, upper_errors],
            marker="o",
            capsize=4,
            linewidth=1.8,
        )

        ax.set_xticks(x)
        ax.set_xticklabels(ORDER)
        ax.set_xlabel("ETA quantile")
        ax.set_ylabel(info["ylabel"])
        ax.set_title(info["title"])
        ax.grid(True, alpha=0.3)

    fig.suptitle("ETA Quantile Comparison (Mean ± 95% CI)", fontsize=14)
    fig.tight_layout()
    fig.savefig(
        output_dir / "eta_combined_metrics.png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    output_dir = args.output or args.input.parent / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_data(args.input)

    print(f"Loaded {len(df)} runs.")
    print(f"Output directory: {output_dir}")

    for metric, info in METRICS.items():
        plot_metric(df, metric, info, output_dir)
        print(f"Generated: {info['filename']}")

    plot_combined(df, output_dir)
    print("Generated: eta_combined_metrics.png")

    print("\nAll ETA figures generated successfully.")


if __name__ == "__main__":
    main()
