import pandas as pd
from pathlib import Path

ROOT = Path("results/phase1_tests/uav_delay_test/n60")

for seed in range(1, 6):
    baseline_path = ROOT / f"s{seed}" / "baseline" / "visits.csv"
    delayed_path = ROOT / f"s{seed}" / "all_legs_delayed" / "visits.csv"

    baseline = pd.read_csv(baseline_path)
    delayed = pd.read_csv(delayed_path)

    # Assign visit occurrence numbers within each cluster
    baseline["visit_num"] = baseline.groupby("cluster_id").cumcount()
    delayed["visit_num"] = delayed.groupby("cluster_id").cumcount()

    # Match corresponding visits
    merged = baseline.merge(
        delayed,
        on=["cluster_id", "visit_num"],
        suffixes=("_baseline", "_delayed"),
        how="outer",
        indicator=True
    )

    # Timing and delivery differences
    merged["arrival_diff_s"] = (
        merged["arrive_s_delayed"] - merged["arrive_s_baseline"]
    )

    merged["contact_duration_baseline"] = (
        merged["end_s_baseline"] - merged["contact_s_baseline"]
    )

    merged["contact_duration_delayed"] = (
        merged["end_s_delayed"] - merged["contact_s_delayed"]
    )

    merged["contact_duration_diff_s"] = (
        merged["contact_duration_delayed"]
        - merged["contact_duration_baseline"]
    )

    merged["readings_diff"] = (
        merged["readings_delayed"] - merged["readings_baseline"]
    )

    print(f"\n{'=' * 25} SEED {seed} {'=' * 25}")

    print("Visit match counts:")
    print(merged["_merge"].value_counts())

    matched = merged[merged["_merge"] == "both"]

    print("\nMatched visits:")
    print(matched[
        [
            "cluster_id",
            "visit_num",
            "arrive_s_baseline",
            "arrive_s_delayed",
            "arrival_diff_s",
            "contact_duration_baseline",
            "contact_duration_delayed",
            "contact_duration_diff_s",
            "readings_baseline",
            "readings_delayed",
            "readings_diff",
        ]
    ].to_string(index=False))

    print("\nSummary:")
    print("Matched visits:", len(matched))
    print("Mean arrival delay:", matched["arrival_diff_s"].mean())
    print("Mean contact duration difference:",
          matched["contact_duration_diff_s"].mean())
    print("Total readings difference:",
          matched["readings_diff"].sum())
    print("Visits with more readings in delayed:",
          (matched["readings_diff"] > 0).sum())
    print("Visits with fewer readings in delayed:",
          (matched["readings_diff"] < 0).sum())
    print("Visits with equal readings:",
          (matched["readings_diff"] == 0).sum())
