import json
from pathlib import Path
import pandas as pd

root = Path("results/clock_drift_narrow_metrics_v3/n60")

fields = [
    "windows_scheduled",
    "windows_opened",
    "windows_met",
    "windows_missed",
    "discovery_contacts",
    "meeting_success_rate",
    "missed_window_fraction",
]

rows = []

for seed_dir in sorted(root.glob("s*"), key=lambda p: int(p.name[1:])):
    seed = int(seed_dir.name[1:])

    for variant in ["no_clock_drift", "clock_drift_5s"]:
        path = seed_dir / variant / "metrics.json"

        if not path.exists():
            print(f"Missing: {path}")
            continue

        with path.open() as f:
            metrics = json.load(f)

        row = {"seed": seed, "variant": variant}
        row.update({key: metrics["wake"].get(key) for key in fields})
        rows.append(row)

df = pd.DataFrame(rows)
print("\n=== Per-seed results ===")
print(df.to_string(index=False))

print("\n=== Mean across seeds ===")
print(
    df.groupby("variant")[fields]
    .mean()
    .round(4)
    .to_string()
)

out = Path("results/clock_drift_narrow_metrics_v3/clock_drift_wake_summary.csv")
df.to_csv(out, index=False)
print(f"\nSaved: {out}")

