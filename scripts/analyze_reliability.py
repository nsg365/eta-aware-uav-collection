import pandas as pd

path = "results/reliability_test/runs.csv"
df = pd.read_csv(path)

df["promotion_rate"] = (
    df["reliability.backup_promotions"]
    / df["reliability.primary_failures"]
    * 100
)

print("\nPer-seed reliability:")
print(
    df[[
        "run.seed",
        "reliability.primary_failures",
        "reliability.backup_promotions",
        "promotion_rate",
    ]].to_string(index=False)
)

failures = df["reliability.primary_failures"].sum()
promotions = df["reliability.backup_promotions"].sum()

print("\nOverall summary")
print(f"Total primary failures: {failures}")
print(f"Total backup promotions: {promotions}")
print(f"Unsuccessful promotions: {failures - promotions}")
print(f"Overall promotion success rate: {promotions / failures * 100:.2f}%")
print(f"Mean promotion rate across seeds: {df['promotion_rate'].mean():.2f}%")
print(f"Std. deviation across seeds: {df['promotion_rate'].std():.2f}%")
