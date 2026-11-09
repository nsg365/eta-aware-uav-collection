import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

input_path = "results_eta_energy/eta_multiseed/runs.csv"
output_dir = Path("results_eta_energy/eta_multiseed")
plot_path = "docs/figures/eta_quantile_energy_vs_meeting_success.png"

df = pd.read_csv(input_path)

required = [
    "run.seed",
    "variant",
    "wake.scheduled_window_energy_J",
    "wake.meeting_success_rate",
]

missing = [col for col in required if col not in df.columns]
if missing:
    raise ValueError(f"Missing columns: {missing}")

df["meeting_success_pct"] = df["wake.meeting_success_rate"] * 100

summary = (
    df.groupby("variant")
    .agg(
        runs=("run.seed", "count"),
        energy_mean_J=("wake.scheduled_window_energy_J", "mean"),
        energy_std_J=("wake.scheduled_window_energy_J", "std"),
        meeting_mean_pct=("meeting_success_pct", "mean"),
        meeting_std_pct=("meeting_success_pct", "std"),
    )
    .reindex(["p80", "p90", "p95", "p99"])
    .reset_index()
)

if summary["runs"].isna().any() or (summary["runs"] != 10).any():
    raise ValueError("Expected exactly 10 runs for each quantile.")

output_dir.mkdir(parents=True, exist_ok=True)
Path("docs/figures").mkdir(parents=True, exist_ok=True)

summary.to_csv(output_dir / "quantile_summary.csv", index=False)

fig, ax = plt.subplots(figsize=(9, 6))

ax.errorbar(
    summary["meeting_mean_pct"],
    summary["energy_mean_J"],
    xerr=summary["meeting_std_pct"],
    yerr=summary["energy_std_J"],
    fmt="o",
    markersize=8,
    capsize=5,
)

for _, row in summary.iterrows():
    ax.annotate(
        row["variant"].upper(),
        (row["meeting_mean_pct"], row["energy_mean_J"]),
        xytext=(8, 8),
        textcoords="offset points",
    )

ax.set_title("ETA Quantile: Listening Energy vs Meeting Success")
ax.set_xlabel("Meeting Success (%)")
ax.set_ylabel("Scheduled-Window Listening Energy (J)")
ax.grid(True, alpha=0.3)

fig.tight_layout()
fig.savefig(plot_path, dpi=300, bbox_inches="tight")
plt.close(fig)

print("\nETA QUANTILE SUMMARY")
print(summary.round(3).to_string(index=False))
print(f"\nSummary: {output_dir / 'quantile_summary.csv'}")
print(f"Plot: {plot_path}")
