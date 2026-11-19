
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats


EXPERIMENTS = [
    "phase4_uav_delay",
    "phase4_ch_failure",
    "phase4_clock_drift",
]

METRICS = [
    "data.pdr",
    "energy.primary_ch_mean_J",
    "wake.ch_wifi_awake_fraction",
    "wake.meeting_success_rate",
    "uav.hover_time_s",
]


def holm_adjust(p_values):
    """Holm-Bonferroni adjusted p-values."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m)
    running_max = 0.0

    for rank, idx in enumerate(order):
        value = min(1.0, (m - rank) * p[idx])
        running_max = max(running_max, value)
        adjusted[idx] = running_max

    return adjusted


def analyze_experiment(experiment):
    directory = Path("results_phase4") / experiment
    input_file = directory / "runs.csv"
    output_file = directory / "paired_summary.csv"

    df = pd.read_csv(input_file)

    required = {
        "variant",
        "run.seed",
        "run.topology_dir",
        *METRICS,
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{experiment}: missing columns {sorted(missing)}")

    if df.duplicated(["variant", "run.seed"]).any():
        raise ValueError(f"{experiment}: duplicate variant/seed rows")

    variants = list(df["variant"].drop_duplicates())

    if len(variants) < 2:
        raise ValueError(f"{experiment}: fewer than two variants")

    # Every variant must use the same seeds and topology for each seed.
    topology = df.pivot(
        index="run.seed",
        columns="variant",
        values="run.topology_dir",
    )

    if topology.isna().any().any():
        raise ValueError(f"{experiment}: incomplete seed/variant pairing")

    if not topology.nunique(axis=1).eq(1).all():
        raise ValueError(
            f"{experiment}: variants do not share topology per seed"
        )

    seed_sets = [
        set(df.loc[df.variant == v, "run.seed"])
        for v in variants
    ]

    if not all(s == seed_sets[0] for s in seed_sets):
        raise ValueError(f"{experiment}: unmatched seed sets")

    records = []

    for metric in METRICS:
        if df[metric].isna().any():
            raise ValueError(f"{experiment}: missing values in {metric}")

        wide = df.pivot(
            index="run.seed",
            columns="variant",
            values=metric,
        )

        for a, b in combinations(variants, 2):
            differences = (wide[a] - wide[b]).dropna()
            n = len(differences)

            if n < 2:
                raise ValueError(
                    f"{experiment}: insufficient pairs for {a} vs {b}"
                )

            mean_diff = differences.mean()
            sd = differences.std(ddof=1)
            se = stats.sem(differences)
            critical = stats.t.ppf(0.975, n - 1)

            if sd == 0:
                p_value = 1.0 if mean_diff == 0 else 0.0
            else:
                p_value = stats.ttest_1samp(
                    differences, popmean=0
                ).pvalue

            records.append({
                "experiment": experiment,
                "metric": metric,
                "variant_a": a,
                "variant_b": b,
                "n_pairs": n,
                "mean_difference_a_minus_b": mean_diff,
                "ci95_lower": mean_diff - critical * se,
                "ci95_upper": mean_diff + critical * se,
                "p_value": p_value,
            })

    result = pd.DataFrame(records)

    # Correct across all metric/pair comparisons within this experiment.
    result["p_holm"] = holm_adjust(result["p_value"].to_numpy())
    result["significant_holm_0.05"] = result["p_holm"] < 0.05

    result.to_csv(output_file, index=False)

    print(f"\n{experiment}")
    print(f"  Variants: {len(variants)}")
    print(f"  Seeds per variant: {len(seed_sets[0])}")
    print(f"  Paired tests: {len(result)}")
    print(f"  Significant after Holm: "
          f"{result['significant_holm_0.05'].sum()}")
    print(f"  Saved: {output_file}")


def main():
    for experiment in EXPERIMENTS:
        analyze_experiment(experiment)


if __name__ == "__main__":
    main()
