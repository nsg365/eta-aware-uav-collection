import csv
import statistics
from pathlib import Path

ROOT = Path("results/phase2_routing_multiseed")
rows = []

for visits_file in sorted(ROOT.glob("n*/s*/**/visits.csv")):
    run_dir = visits_file.parent
    seed = run_dir.parent.name
    policy = run_dir.name

    cluster_file = run_dir / "per_cluster.csv"

    with visits_file.open(newline="") as f:
        visits = list(csv.DictReader(f))

    with cluster_file.open(newline="") as f:
        clusters = list(csv.DictReader(f))

    total_clusters = len(clusters)

    successfully_contacted = {
        int(row["cluster_id"])
        for row in visits
        if float(row["contact_s"]) >= 0
    }

    contacted_count = len(successfully_contacted)
    coverage = 100.0 * contacted_count / total_clusters

    rows.append({
        "seed": seed,
        "policy": policy,
        "total_clusters": total_clusters,
        "clusters_contacted": contacted_count,
        "coverage_percent": round(coverage, 4),
    })

if not rows:
    raise RuntimeError(f"No visits.csv files found under {ROOT}")

output_dir = ROOT

with (output_dir / "cluster_coverage_by_run.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

policies = sorted({row["policy"] for row in rows})
summary = []

for policy in policies:
    values = [
        row["coverage_percent"]
        for row in rows
        if row["policy"] == policy
    ]

    summary.append({
        "policy": policy,
        "runs": len(values),
        "mean_coverage_percent": round(statistics.mean(values), 4),
        "std_coverage_percent": round(
            statistics.stdev(values), 4
        ) if len(values) > 1 else 0.0,
    })

with (output_dir / "cluster_coverage_summary.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=summary[0].keys())
    writer.writeheader()
    writer.writerows(summary)

print("\nCluster coverage by policy (mean ± sample std):")
for row in summary:
    print(
        f"{row['policy']:20s} "
        f"{row['mean_coverage_percent']:.2f}% "
        f"± {row['std_coverage_percent']:.2f}% "
        f"({row['runs']} runs)"
    )

print("\nSaved:")
print(output_dir / "cluster_coverage_by_run.csv")
print(output_dir / "cluster_coverage_summary.csv")
