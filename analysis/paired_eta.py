
"""
Paired statistical analysis for ETA quantile experiments.

Uses matched seeds and shared topologies.
Calculates paired differences, 95% Student-t confidence
intervals, paired t-tests, and Holm-adjusted p-values.
"""

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


METRICS = {
    "data.pdr": "higher_is_better",
    "energy.primary_ch_mean_J": "lower_is_better",
    "wake.meeting_success_rate": "higher_is_better",
    "uav.hover_time_s": "lower_is_better",
}


def load_and_validate(input_path):
    if not input_path.exists():
        raise FileNotFoundError(f"Results file not found: {input_path}")

    df = pd.read_csv(input_path)

    required = {
        "variant",
        "run.seed",
        "run.topology_dir",
        "run.sim_time_s",
        *METRICS.keys(),
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    if df.duplicated(["variant", "run.seed"]).any():
        raise ValueError("Duplicate variant-seed combinations found.")

    variants = sorted(df["variant"].unique())

    if len(variants) < 2:
        raise ValueError("At least two variants are required.")

    # Verify that variants share the same topology for each seed.
    for seed, group in df.groupby("run.seed"):
        paths = {
            str(Path(path).resolve())
            for path in group["run.topology_dir"].dropna()
        }

        if len(paths) != 1:
            raise ValueError(
                f"Seed {seed} has inconsistent topology directories."
            )

    if df["run.sim_time_s"].nunique() != 1:
        raise ValueError("Inconsistent simulation durations.")

    print("Data validation passed!")
    print(f"Total runs: {len(df)}")
    print(f"Variants: {len(variants)}")
    print(f"Seeds: {df['run.seed'].nunique()}")
    print(f"Comparisons: {len(list(combinations(variants, 2)))}")

    return df, variants


def paired_comparison(df, first, second, metric, direction):
    a = df[df["variant"] == first].set_index("run.seed")
    b = df[df["variant"] == second].set_index("run.seed")

    common_seeds = sorted(set(a.index) & set(b.index))

    values_a = pd.to_numeric(
        a.loc[common_seeds, metric], errors="coerce"
    )

    values_b = pd.to_numeric(
        b.loc[common_seeds, metric], errors="coerce"
    )

    # Retain only seeds with valid values in both variants.
    valid = values_a.notna() & values_b.notna()

    values_a = values_a[valid]
    values_b = values_b[valid]

    differences = values_a - values_b
    n = len(differences)

    if n < 2:
        raise ValueError(
            f"Not enough valid pairs for {first} vs {second}, {metric}"
        )

    mean_diff = differences.mean()
    sd_diff = differences.std(ddof=1)

    # Unadjusted 95% Student-t confidence interval.
    sem = stats.sem(differences)
    critical_t = stats.t.ppf(0.975, df=n - 1)
    margin = critical_t * sem

    # Two-sided paired t-test.
    test = stats.ttest_rel(values_a, values_b)

    return {
        "variant_1": first,
        "variant_2": second,
        "metric": metric,
        "direction": direction,
        "n_pairs": n,
        "mean_variant_1": values_a.mean(),
        "mean_variant_2": values_b.mean(),
        "mean_paired_difference": mean_diff,
        "sd_paired_difference": sd_diff,
        "ci95_lower": mean_diff - margin,
        "ci95_upper": mean_diff + margin,
        "p_value": float(test.pvalue),
    }


def holm_correction(results):
    results = results.copy()

    p_values = results["p_value"].to_numpy()
    m = len(p_values)

    # Holm step-down adjusted p-values.
    order = np.argsort(p_values)
    sorted_p = p_values[order]

    multipliers = m - np.arange(m)

    sorted_adjusted = np.maximum.accumulate(
        multipliers * sorted_p
    )

    sorted_adjusted = np.minimum(sorted_adjusted, 1.0)

    adjusted_p = np.empty(m)
    adjusted_p[order] = sorted_adjusted

    results["holm_adjusted_p"] = adjusted_p

    return results


def interpret_results(results):
    conclusions = []

    for _, row in results.iterrows():
        significant = row["holm_adjusted_p"] < 0.05
        difference = row["mean_paired_difference"]

        if not significant:
            conclusion = "No significant difference after Holm correction"

        elif row["direction"] == "higher_is_better":
            conclusion = (
                "First variant better"
                if difference > 0
                else "Second variant better"
            )

        else:
            conclusion = (
                "First variant better"
                if difference < 0
                else "Second variant better"
            )

        conclusions.append(conclusion)

    results["conclusion"] = conclusions

    return results


def run_analysis(df, variants):
    rows = []

    comparisons = list(combinations(variants, 2))

    for first, second in comparisons:
        print(f"\nComparing {first} vs {second}")

        for metric, direction in METRICS.items():
            result = paired_comparison(
                df,
                first,
                second,
                metric,
                direction,
            )

            rows.append(result)

    results = pd.DataFrame(rows)

    # Apply Holm correction across all comparisons and metrics.
    results = holm_correction(results)
    results = interpret_results(results)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Paired analysis of ETA quantile experiments."
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Path to experiment runs.csv",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (defaults to paired_summary.csv beside input).",
    )

    args = parser.parse_args()

    output = args.output or args.input.with_name("paired_summary.csv")

    df, variants = load_and_validate(args.input)

    results = run_analysis(df, variants)

    output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(output, index=False)

    print("\n" + "=" * 90)
    print("PAIRED ANALYSIS WITH HOLM CORRECTION")
    print("=" * 90)

    display_columns = [
        "variant_1",
        "variant_2",
        "metric",
        "mean_paired_difference",
        "ci95_lower",
        "ci95_upper",
        "p_value",
        "holm_adjusted_p",
        "conclusion",
    ]

    print(results[display_columns].to_string(index=False))

    print(f"\nSaved results to: {output}")


if __name__ == "__main__":
    main()
