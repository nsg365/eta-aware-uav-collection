
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel, t

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "results_phase4/window_width/runs.csv"
OUTPUT = ROOT / "results_phase4/window_width/paired_summary.csv"

REFERENCE = "w10"
COMPARISONS = ["w5", "w20", "w30", "w40"]

METRICS = [
    "wake.meeting_success_rate",
    "wake.scheduled_window_energy_J",
]


def holm_adjust(p_values):
    p_values = np.asarray(p_values, dtype=float)
    adjusted = np.full(len(p_values), np.nan)

    valid = np.where(np.isfinite(p_values))[0]
    if len(valid) == 0:
        return adjusted

    order = valid[np.argsort(p_values[valid])]
    m = len(order)
    running_max = 0.0

    for rank, idx in enumerate(order):
        value = (m - rank) * p_values[idx]
        running_max = max(running_max, value)
        adjusted[idx] = min(running_max, 1.0)

    return adjusted


def main():
    df = pd.read_csv(INPUT)
    results = []

    for size in sorted(df["run.num_sensors"].unique()):
        subset = df[df["run.num_sensors"] == size]

        for metric in METRICS:
            reference = (
                subset[subset["variant"] == REFERENCE]
                [["run.seed", metric]]
                .rename(columns={metric: "reference"})
            )

            for variant in COMPARISONS:
                comparison = (
                    subset[subset["variant"] == variant]
                    [["run.seed", metric]]
                    .rename(columns={metric: "comparison"})
                )

                paired = reference.merge(
                    comparison, on="run.seed", validate="one_to_one"
                ).dropna()

                differences = (
                    paired["comparison"] - paired["reference"]
                ).to_numpy()

                n = len(differences)
                mean_diff = differences.mean()
                sd = differences.std(ddof=1) if n > 1 else np.nan

                if n > 1:
                    margin = (
                        t.ppf(0.975, n - 1)
                        * sd / np.sqrt(n)
                    )
                    ci_low = mean_diff - margin
                    ci_high = mean_diff + margin

                    if np.allclose(differences, 0):
                        p_value = 1.0
                    else:
                        p_value = ttest_rel(
                            paired["comparison"],
                            paired["reference"]
                        ).pvalue
                else:
                    ci_low = np.nan
                    ci_high = np.nan
                    p_value = np.nan

                results.append({
                    "num_sensors": size,
                    "metric": metric,
                    "reference": REFERENCE,
                    "variant": variant,
                    "n_pairs": n,
                    "mean_difference": mean_diff,
                    "ci95_low": ci_low,
                    "ci95_high": ci_high,
                    "p_value": p_value,
                })

    result_df = pd.DataFrame(results)

    # Correct for all comparisons across the two metrics
    # and three network sizes.
    result_df["holm_p_value"] = holm_adjust(
        result_df["p_value"].to_numpy()
    )

    result_df["significant_holm_0.05"] = (
        result_df["holm_p_value"] < 0.05
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(OUTPUT, index=False)

    print(result_df.round(6).to_string(index=False))
    print(f"\nSaved paired analysis: {OUTPUT}")


if __name__ == "__main__":
    main()
