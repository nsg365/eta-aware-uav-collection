
import pandas as pd

q = pd.read_csv(
    "results/phase3_qlearning_A4_eval/runs_reconstructed.csv"
)
p = pd.read_csv(
    "results/phase3_ppo_A4_eval/runs.csv"
)

metrics = [
    "data.pdr",
    "data.delivered",
    "energy.sensor_total_J",
    "reliability.promise_violations",
    "eta.late_beyond_window_frac",
    "wake.meeting_success_rate",
]

# Match both algorithms by evaluation seed
merged = q.merge(
    p,
    on="run.seed",
    suffixes=("_ql", "_ppo"),
    validate="one_to_one"
).sort_values("run.seed")

print("Matched seeds:", merged["run.seed"].tolist())

for metric in metrics:
    print(f"\n{'=' * 15} {metric} {'=' * 15}")
    print(
        merged[
            [
                "run.seed",
                f"{metric}_ql",
                f"{metric}_ppo",
            ]
        ].to_string(index=False)
    )
