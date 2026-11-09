import argparse
import pandas as pd
import numpy as np


def analyze_eta(csv_paths):
    # Read and combine visits from all supplied CSV files
    frames = []

    for path in csv_paths:
        df = pd.read_csv(path)
        df = df[
            (df["promised_eta_s"] >= 0) &
            (df["stops_since_promise"] >= 0)
        ].copy()

        if not df.empty:
            df["source"] = path
            frames.append(df)

    if not frames:
        print("No promised visits found.")
        return

    df = pd.concat(frames, ignore_index=True)

    # Calculate signed ETA error
    df["eta_error_s"] = df["arrive_s"] - df["promised_eta_s"]

    # Count early arrivals as zero lateness
    df["positive_lateness_s"] = df["eta_error_s"].clip(lower=0)

    percentiles = [0.80, 0.90, 0.95, 0.99]

    print("\nCOMBINED ETA ANALYSIS")
    print("-" * 65)
    print(f"CSV files analyzed: {len(frames)}")
    print(f"Total promised visits: {len(df)}")
    print(f"Early arrivals: {(df['eta_error_s'] < 0).sum()}")
    print(f"Late arrivals: {(df['eta_error_s'] > 0).sum()}")

    print("\nPositive lateness quantiles (seconds)")
    print("-" * 65)

    errors = df["positive_lateness_s"].to_numpy()

    for p in percentiles:
        value = np.quantile(errors, p)
        print(f"  P{int(p * 100)}: {value:.3f} s")

    print("\nPositive lateness grouped by stops since promise")
    print("-" * 65)

    for stops, group in df.groupby("stops_since_promise"):
        errors = group["positive_lateness_s"].to_numpy()

        print(f"\nStops: {stops} (n={len(errors)})")

        for p in percentiles:
            value = np.quantile(errors, p)
            print(f"  P{int(p * 100)}: {value:.3f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze positive ETA lateness across multiple seeds"
    )

    parser.add_argument(
        "csv_paths",
        nargs="+",
        help="One or more visits.csv files"
    )

    args = parser.parse_args()
    analyze_eta(args.csv_paths)
