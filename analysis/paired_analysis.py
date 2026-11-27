
"""
Paired statistical analysis for Phase 3 evaluation results.

Uses matched seeds and shared topologies.
Calculates paired differences, 95% Student-t confidence
intervals, paired t-tests, and Holm-adjusted p-values.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

INPUT = Path("results_phase4/phase3_eval/runs.csv")
OUTPUT = Path("results_phase4/phase3_eval/paired_summary.csv")

METRICS = {
    "data.pdr": "higher_is_better",
    "energy.primary_ch_mean_J": "lower_is_better",
    "wake.meeting_success_rate": "higher_is_better",
    "uav.hover_time_s": "lower_is_better",
}

COMPARISONS = [
    ("ppo_A4", "tour_adaptive"),
    ("ppo_A4", "tour_fixed"),
    ("tour_adaptive", "tour_fixed"),
    ("ppo_A1", "ppo_A2"),
    ("ppo_A2", "ppo_A3"),
    ("ppo_A3", "ppo_A4"),
]


# --------------------------------------------------
# 2. Load and validate data
# --------------------------------------------------

def load_and_validate():

    if not INPUT.exists():
        raise FileNotFoundError(f"Results file not found: {INPUT}")

    df = pd.read_csv(INPUT)

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

    # Verify shared topology for each seed
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
        raise ValueError("Inconsistent simulation durations found.")

    variants = set(df["variant"])

    for first, second in COMPARISONS:
        if first not in variants or second not in variants:
            raise ValueError(
                f"Missing comparison variant: {first} or {second}"
            )

    print("Data validation passed!")
    print(f"Total runs: {len(df)}")
    print(f"Variants: {df['variant'].nunique()}")
    print(f"Seeds: {df['run.seed'].nunique()}")

    return df


# --------------------------------------------------
# 3. Paired statistical comparison
# --------------------------------------------------

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

    # Keep only seeds with valid values in both variants
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

    # Unadjusted 95% Student-t confidence interval
    sem = stats.sem(differences)
    critical_t = stats.t.ppf(0.975, df=n - 1)
    margin = critical_t * sem

    ci_lower = mean_diff - margin
    ci_upper = mean_diff + margin

    # Two-sided paired t-test
    test = stats.ttest_rel(values_a, values_b)
    p_value = float(test.pvalue)

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
        "ci95_lower": ci_lower,
        "ci95_upper": ci_upper,
        "p_value": p_value,
    }


# --------------------------------------------------
# 4. Holm multiple-comparison correction
# --------------------------------------------------

def holm_correction(results):

    adjusted = results.copy()

    p_values = adjusted["p_value"].to_numpy()
    m = len(p_values)

    # Sort p-values from smallest to largest
    order = np.argsort(p_values)
    sorted_p = p_values[order]

    # Holm step-down adjusted p-values
    multipliers = m - np.arange(m)

    sorted_adjusted = np.maximum.accumulate(
        multipliers * sorted_p
    )

    sorted_adjusted = np.minimum(sorted_adjusted, 1.0)

    # Restore original row order
    adjusted_p = np.empty(m)
    adjusted_p[order] = sorted_adjusted

    adjusted["holm_adjusted_p"] = adjusted_p

    return adjusted


# --------------------------------------------------
# 5. Interpret results
# --------------------------------------------------

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


# --------------------------------------------------
# 6. Run all comparisons
# --------------------------------------------------

def run_analysis(df):

    rows = []

    for first, second in COMPARISONS:

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

    # Apply Holm correction across all 24 tests
    results = holm_correction(results)

    results = interpret_results(results)

    return results


# --------------------------------------------------
# 7. Save results
# --------------------------------------------------

def main():

    df = load_and_validate()

    results = run_analysis(df)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    results.to_csv(OUTPUT, index=False)

    columns = [
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

    print("\n" + "=" * 90)
    print("PAIRED ANALYSIS WITH HOLM CORRECTION")
    print("=" * 90)

    print(results[columns].to_string(index=False))

    print(f"\nSaved results to: {OUTPUT}")


if __name__ == "__main__":
    main()
