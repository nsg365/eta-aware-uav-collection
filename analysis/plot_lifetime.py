import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    from scipy.stats import t as student_t
except ImportError:
    student_t = None


ROOT = Path(__file__).resolve().parents[1]

NETWORK_FILE = ROOT / "results_phase4/network_sizes/runs.csv"
PHASE3_FILE = ROOT / "results_phase4/phase3_eval/runs.csv"
OUTPUT_DIR = ROOT / "results_phase4/lifetime/figures"

REQUIRED_COLUMNS = [
    "variant",
    "run.seed",
    "run.num_sensors",
    "lifetime.first_node_death_s",
    "lifetime.first_node_death_censored",
    "lifetime.lifetime_x_s",
    "lifetime.lifetime_x_censored",
]


def load_data():
    frames = []

    for path in [NETWORK_FILE, PHASE3_FILE]:
        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")

        df = pd.read_csv(path)

        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} is missing columns: {missing}")

        frames.append(df[REQUIRED_COLUMNS].copy())

    df = pd.concat(frames, ignore_index=True)

    # Avoid accidentally counting the same run twice.
    key = ["run.num_sensors", "run.seed", "variant"]
    duplicates = df.duplicated(key, keep=False)

    if duplicates.any():
        raise ValueError(
            "Duplicate network-size/seed/variant runs found:\n"
            + df.loc[duplicates, key].to_string(index=False)
        )

    df["run.num_sensors"] = pd.to_numeric(
        df["run.num_sensors"], errors="raise"
    )
    df["run.seed"] = pd.to_numeric(df["run.seed"], errors="raise")

    for col in [
        "lifetime.first_node_death_s",
        "lifetime.lifetime_x_s",
    ]:
        df[col] = pd.to_numeric(df[col], errors="raise")

    for col in [
        "lifetime.first_node_death_censored",
        "lifetime.lifetime_x_censored",
    ]:
        df[col] = (
            df[col].astype(str).str.strip().str.lower().eq("true")
        )

    df = df.sort_values(
        ["run.num_sensors", "variant", "run.seed"]
    ).reset_index(drop=True)

    return df


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan, np.nan

    mean = values.mean()

    if len(values) == 1:
        return mean, 0.0

    se = values.std(ddof=1) / np.sqrt(len(values))

    if student_t is not None:
        critical = student_t.ppf(0.975, df=len(values) - 1)
    else:
        critical = 1.96

    return mean, critical * se


def plot_first_node_death(df):
    sizes = sorted(df["run.num_sensors"].unique())
    variants = sorted(df["variant"].unique())

    fig, axes = plt.subplots(
        1, len(sizes),
        figsize=(7 * len(sizes), 6),
        sharey=True
    )

    if len(sizes) == 1:
        axes = [axes]

    for ax, size in zip(axes, sizes):
        subset = df[df["run.num_sensors"] == size]

        means = []
        errors = []
        labels = []
        counts = []

        for variant in variants:
            group = subset[subset["variant"] == variant]

            observed = group.loc[
                ~group["lifetime.first_node_death_censored"],
                "lifetime.first_node_death_s"
            ]

            mean, ci = mean_ci(observed)

            means.append(mean)
            errors.append(ci)
            labels.append(variant)
            counts.append(len(observed))

        x = np.arange(len(variants))

        ax.errorbar(
            x,
            means,
            yerr=errors,
            fmt="o",
            capsize=4
        )

        ax.set_title(f"N = {int(size)} sensors")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=60, ha="right")
        ax.set_ylabel("First-node death time (seconds)")
        ax.grid(axis="y", alpha=0.3)

        for i, count in enumerate(counts):
            if count == 0:
                ax.annotate(
                    "No observed deaths",
                    (i, 0),
                    rotation=90,
                    ha="center"
                )

    fig.suptitle(
        "First-Node Death Time Across Network Sizes\n"
        "Mean with 95% confidence intervals",
        fontsize=14
    )
    fig.tight_layout()

    path = OUTPUT_DIR / "first_node_death.png"
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved: {path}")


def kaplan_meier(group):
    """
    Calculate a Kaplan-Meier survival estimate.

    lifetime_x_s contains the observed event time or the
    simulation horizon for right-censored observations.
    """

    durations = group["lifetime.lifetime_x_s"].to_numpy(dtype=float)

    events = (
        ~group["lifetime.lifetime_x_censored"].to_numpy(dtype=bool)
    )

    order = np.argsort(durations)
    durations = durations[order]
    events = events[order]

    unique_times = np.unique(durations)

    at_risk = len(durations)
    survival = 1.0

    times = [0.0]
    probabilities = [1.0]
    censor_times = []
    censor_probabilities = []

    for time in unique_times:
        at_time = durations == time

        deaths = int(np.sum(at_time & events))
        censored = int(np.sum(at_time & ~events))

        if deaths > 0 and at_risk > 0:
            survival *= (1.0 - deaths / at_risk)

        # Record the post-event survival probability.
        times.append(float(time))
        probabilities.append(survival)

        # Censor marks are placed at the survival level at that time.
        if censored > 0:
            censor_times.extend([float(time)] * censored)
            censor_probabilities.extend([survival] * censored)

        at_risk -= deaths + censored

    return (
        np.asarray(times),
        np.asarray(probabilities),
        np.asarray(censor_times),
        np.asarray(censor_probabilities),
    )


def plot_kaplan_meier(df):
    sizes = sorted(df["run.num_sensors"].unique())
    variants = sorted(df["variant"].unique())

    fig, axes = plt.subplots(
        1, len(sizes),
        figsize=(7 * len(sizes), 6),
        sharey=True
    )

    if len(sizes) == 1:
        axes = [axes]

    for ax, size in zip(axes, sizes):
        subset = df[df["run.num_sensors"] == size]

        for variant in variants:
            group = subset[subset["variant"] == variant]

            times, survival, censor_t, censor_s = kaplan_meier(group)

            ax.step(
                times,
                survival,
                where="post",
                label=variant
            )

            if len(censor_t):
                ax.scatter(
                    censor_t,
                    censor_s,
                    marker="+",
                    s=35
                )

        ax.set_title(f"N = {int(size)} sensors")
        ax.set_xlabel("Time until 10% sensor deaths (seconds)")
        ax.set_xlim(left=0)
        ax.set_ylim(0, 1.05)
        ax.grid(alpha=0.3)

    axes[0].set_ylabel("Probability of surviving beyond time t")

    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=5,
        bbox_to_anchor=(0.5, -0.04)
    )

    fig.suptitle(
        "Kaplan–Meier Curves: 10% Network Lifetime\n"
        "Crosses indicate right-censored observations",
        fontsize=14
    )

    fig.tight_layout(rect=[0, 0.12, 1, 0.93])

    path = OUTPUT_DIR / "lifetime_10pct_kaplan_meier.png"
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved: {path}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()

    print(f"Loaded {len(df)} runs")
    print("Network sizes:", sorted(df["run.num_sensors"].unique()))
    print("Variants:", sorted(df["variant"].unique()))

    print("\nCensoring summary:")
    print(
        df.groupby("run.num_sensors")[
            "lifetime.lifetime_x_censored"
        ].agg(["count", "sum"])
    )

    print("\nFirst-node death censoring:")
    print(
        df.groupby("run.num_sensors")[
            "lifetime.first_node_death_censored"
        ].agg(["count", "sum"])
    )

    plot_first_node_death(df)
    plot_kaplan_meier(df)

    print("\nLifetime figures generated successfully.")


if __name__ == "__main__":
    main()