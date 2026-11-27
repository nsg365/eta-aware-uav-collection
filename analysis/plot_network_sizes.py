
"""
Plot network-size scaling results using consolidated runs.csv files.

Combines N=60/150 from network_sizes and N=100 from phase3_eval.
All figures are generated from raw per-run metrics.
"""

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats


METRICS = {
    "data.pdr": ("Packet Delivery Ratio", "PDR", "network_pdr.png"),
    "energy.primary_ch_mean_J": (
        "Primary CH Mean Energy", "Energy (J)", "network_energy.png"
    ),
    "wake.meeting_success_rate": (
        "UAV Meeting Success Rate", "Meeting success rate",
        "network_meeting_success.png"
    ),
    "uav.hover_time_s": (
        "UAV Hover Time", "Hover time (s)", "network_hover_time.png"
    ),
}

VARIANT_ORDER = [
    "tour_fixed",
    "tour_adaptive",
    "nearest_feasible",
    "data_greedy",
    "energy_data_score",
    "ppo_A1",
    "ppo_A2",
    "ppo_A3",
    "ppo_A4",
    "ppo_A4P",
]


def load_data(network_file, phase3_file):
    network = pd.read_csv(network_file)
    phase3 = pd.read_csv(phase3_file)

    df = pd.concat([network, phase3], ignore_index=True)

    required = {
        "variant",
        "run.seed",
        "run.num_sensors",
        *METRICS.keys(),
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df["N"] = pd.to_numeric(df["run.num_sensors"])
    return df


def mean_ci(values):
    values = pd.to_numeric(values, errors="coerce").dropna()
    n = len(values)

    if n == 0:
        return None

    mean = values.mean()

    if n < 2:
        return mean, 0.0, 0.0

    margin = stats.t.ppf(0.975, n - 1) * stats.sem(values)
    return mean, margin, n


def plot_metric(df, metric, info, output_dir):
    fig, ax = plt.subplots(figsize=(10, 6))

    for variant in VARIANT_ORDER:
        subset = df[df["variant"] == variant]
        if subset.empty:
            continue

        sizes = []
        means = []
        errors = []

        for n in [60, 100, 150]:
            values = subset.loc[subset["N"] == n, metric]
            result = mean_ci(values)

            if result is None:
                continue

            mean, margin, count = result
            sizes.append(n)
            means.append(mean)
            errors.append(margin)

        if sizes:
            ax.errorbar(
                sizes,
                means,
                yerr=errors,
                marker="o",
                capsize=3,
                linewidth=1.5,
                label=variant,
            )

    ax.set_title(info[0])
    ax.set_xlabel("Number of sensor nodes (N)")
    ax.set_ylabel(info[1])
    ax.set_xticks([60, 100, 150])
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)

    fig.tight_layout()
    fig.savefig(output_dir / info[2], dpi=300)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--network",
        type=Path,
        default=Path("results_phase4/network_sizes/runs.csv"),
    )
    parser.add_argument(
        "--phase3",
        type=Path,
        default=Path("results_phase4/phase3_eval/runs.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results_phase4/network_sizes/figures"),
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    df = load_data(args.network, args.phase3)

    print(f"Loaded {len(df)} runs.")
    print("Network sizes:", sorted(df["N"].unique()))
    print("Variants:", df["variant"].nunique())

    for metric, info in METRICS.items():
        plot_metric(df, metric, info, args.output)
        print(f"Generated {info[2]}")

    print(f"\nFigures saved in: {args.output}")


if __name__ == "__main__":
    main()
