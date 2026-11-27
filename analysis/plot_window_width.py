
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t

ROOT = Path(__file__).resolve().parents[1]

INPUT = ROOT / "results_phase4/window_width/runs.csv"
OUTPUT = ROOT / "results_phase4/window_width/figures"

WIDTHS = {
    "w5": 10,
    "w10": 20,
    "w20": 40,
    "w30": 60,
    "w40": 80,
}

METRICS = {
    "wake.meeting_success_rate": (
        "Meeting Success Rate",
        "Meeting success rate",
        "window_width_meeting_success.png",
    ),
    "wake.scheduled_window_energy_J": (
        "Scheduled-Window Listening Energy",
        "Scheduled-window energy (J)",
        "window_width_energy.png",
    ),
}


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = values.mean()

    if n < 2:
        return mean, 0.0

    margin = t.ppf(0.975, n - 1) * values.std(ddof=1) / np.sqrt(n)
    return mean, margin


def main():
    df = pd.read_csv(INPUT)

    required = [
        "variant",
        "run.seed",
        "run.num_sensors",
        *METRICS.keys(),
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df["window_width_s"] = df["variant"].map(WIDTHS)

    if df["window_width_s"].isna().any():
        raise ValueError("Unexpected variant found.")

    OUTPUT.mkdir(parents=True, exist_ok=True)

    sizes = sorted(df["run.num_sensors"].unique())

    for metric, (title, ylabel, filename) in METRICS.items():
        fig, ax = plt.subplots(figsize=(9, 6))

        for size in sizes:
            subset = df[df["run.num_sensors"] == size]

            means = []
            errors = []

            for variant, width in sorted(
                WIDTHS.items(), key=lambda item: item[1]
            ):
                values = subset.loc[
                    subset["variant"] == variant, metric
                ].dropna().to_numpy()

                mean, ci = mean_ci(values)
                means.append(mean)
                errors.append(ci)

            x = sorted(WIDTHS.values())

            ax.errorbar(
                x,
                means,
                yerr=errors,
                marker="o",
                capsize=4,
                label=f"N={size}",
            )

        ax.set_title(title)
        ax.set_xlabel("Total wake-window width (seconds)")
        ax.set_ylabel(ylabel)
        ax.set_xticks(sorted(WIDTHS.values()))
        ax.grid(alpha=0.3)
        ax.legend(title="Network size")

        if metric == "wake.meeting_success_rate":
            ax.set_ylim(0.95, 1.005)

        fig.tight_layout()

        path = OUTPUT / filename
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)

        print(f"Saved: {path}")

    print("\nWindow-width figures generated successfully.")


if __name__ == "__main__":
    main()
