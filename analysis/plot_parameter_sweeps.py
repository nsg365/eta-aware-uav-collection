
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats


EXPERIMENTS = {
    "phase4_uav_delay": {
        "title": "UAV Delay Probability",
        "variants": [
            ("delay_0", "0"),
            ("delay_01", "0.1"),
            ("delay_025", "0.25"),
            ("delay_05", "0.5"),
            ("delay_1", "1.0"),
        ],
        "x_label": "UAV delay probability",
    },
    "phase4_ch_failure": {
        "title": "Cluster Head Failure Rate",
        "variants": [
            ("ch_failure_0", "0"),
            ("ch_failure_baseline", "2.78e-5"),
            ("ch_failure_0001", "1e-4"),
            ("ch_failure_0005", "5e-4"),
            ("ch_failure_001", "1e-3"),
        ],
        "x_label": "CH failure hazard (per second)",
    },
    "phase4_clock_drift": {
        "title": "Clock Drift",
        "variants": [
            ("drift_0", "0"),
            ("drift_1", "1"),
            ("drift_2", "2"),
            ("drift_5", "5"),
            ("drift_10", "10"),
        ],
        "x_label": "Maximum clock drift (seconds)",
    },
}

METRICS = {
    "data.pdr": {
        "file": "pdr",
        "title": "Packet Delivery Ratio",
        "ylabel": "PDR (%)",
        "scale": 100,
    },
    "energy.primary_ch_mean_J": {
        "file": "primary_ch_energy",
        "title": "Mean Primary CH Energy",
        "ylabel": "Energy (J)",
        "scale": 1,
    },
    "wake.ch_wifi_awake_fraction": {
        "file": "awake_fraction",
        "title": "CH Wi-Fi Awake Fraction",
        "ylabel": "Awake time (%)",
        "scale": 100,
    },
    "wake.meeting_success_rate": {
        "file": "meeting_success",
        "title": "UAV Meeting Success Rate",
        "ylabel": "Meeting success (%)",
        "scale": 100,
    },
    "uav.hover_time_s": {
        "file": "hover_time",
        "title": "UAV Hover Time",
        "ylabel": "Hover time (seconds)",
        "scale": 1,
    },
}


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = values.mean()

    if n < 2:
        return mean, 0.0

    sem = stats.sem(values)
    margin = stats.t.ppf(0.975, n - 1) * sem

    return mean, margin


def plot_experiment(experiment, config):
    folder = Path("results_phase4") / experiment
    df = pd.read_csv(folder / "runs.csv")

    figures = folder / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    expected = [v for v, _ in config["variants"]]
    actual = set(df["variant"].unique())

    if set(expected) != actual:
        raise ValueError(
            f"{experiment}: variant mismatch. "
            f"Expected {expected}, found {sorted(actual)}"
        )

    for metric, settings in METRICS.items():
        means = []
        errors = []

        for variant, _ in config["variants"]:
            values = df.loc[
                df["variant"] == variant, metric
            ].dropna()

            if len(values) < 2:
                raise ValueError(
                    f"{experiment}/{variant}: insufficient data for {metric}"
                )

            mean, margin = mean_ci(values)
            means.append(mean * settings["scale"])
            errors.append(margin * settings["scale"])

        x = np.arange(len(expected))

        fig, ax = plt.subplots(figsize=(8, 5))

        ax.errorbar(
            x,
            means,
            yerr=errors,
            marker="o",
            capsize=5,
            linewidth=1.8,
        )

        ax.set_xticks(x)
        ax.set_xticklabels(
            [label for _, label in config["variants"]]
        )

        ax.set_xlabel(config["x_label"])
        ax.set_ylabel(settings["ylabel"])
        ax.set_title(
            f"{config['title']}: {settings['title']}"
        )

        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        output = figures / f"{settings['file']}.png"
        fig.savefig(output, dpi=200)
        plt.close(fig)

        print(f"Saved {output}")


def main():
    for experiment, config in EXPERIMENTS.items():
        print(f"\nPlotting {experiment}")
        plot_experiment(experiment, config)

    print("\nAll parameter-sweep figures generated.")


if __name__ == "__main__":
    main()
