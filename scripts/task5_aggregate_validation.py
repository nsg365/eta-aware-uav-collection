import json
from pathlib import Path

root = Path("results/task5_failover_validation")
files = sorted(root.rglob("metrics.json"))

keys = [
    "primary_failures",
    "backup_promotions",
    "failures_no_backup",
    "failures_backup_dead",
    "lost_during_failover",
    "retry_attempts",
    "promise_violations",
    "retry_exhaustions",
    "rebootstrap_count",
]

totals = {key: 0 for key in keys}

print(f"Found {len(files)} metrics files\n")

for path in files:
    with open(path) as f:
        r = json.load(f)["reliability"]

    seed = next((p for p in path.parts if p.startswith("s")), "?")
    print(f"{seed}:")
    for key in keys:
        value = r.get(key, "MISSING")
        print(f"  {key}: {value}")
        if isinstance(value, (int, float)):
            totals[key] += value

    print(f"  latest_failover_time_s: {r.get('latest_failover_time_s')}")
    print()

print("=" * 45)
print("TOTALS ACROSS RUNS")
for key, value in totals.items():
    print(f"{key}: {value}")
