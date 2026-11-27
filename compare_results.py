
import pandas as pd
import numpy as np
from scipy.stats import wilcoxon

q_path = "results/phase3_qlearning_A4_eval/runs_reconstructed.csv"
p_path = "results/phase3_ppo_A4_eval/runs.csv"

q = pd.read_csv(q_path)
p = pd.read_csv(p_path)

# Identify the common seed column
candidates = ["seed_cfg.seed", "run.seed", "seed"]

seed_col = next(
    (c for c in candidates if c in q.columns and c in p.columns),
    None
)

if seed_col is None:
    print("Q-learning columns:", q.columns.tolist())
    print("PPO columns:", p.columns.tolist())
    raise ValueError("Could not identify a common seed column.")

# Metrics to compare
metrics = {
    "PDR": ("data.pdr", "higher"),
    "Delivered packets": ("data.delivered", "higher"),
    "Sensor energy (J)": ("energy.sensor_total_J", "lower"),
    "Promise violations": ("reliability.promise_violations", "lower"),
    "Late fraction": ("eta.late_beyond_window_frac", "lower"),
    "Meeting success": ("wake.meeting_success_rate", "higher"),
    "Inference time (ms)": ("policy.inference_ms_mean", "lower"),
    "Policy return": ("policy.return", "higher"),
}

# Match the same evaluation seeds
merged = q.merge(
    p,
    on=seed_col,
    suffixes=("_ql", "_ppo"),
    validate="one_to_one"
).sort_values(seed_col)

print("Matched evaluation seeds:", merged[seed_col].tolist())

results = []

for name, (col, direction) in metrics.items():
    q_values = merged[f"{col}_ql"].astype(float)
    p_values = merged[f"{col}_ppo"].astype(float)

    differences = p_values - q_values

    if np.allclose(differences, 0):
        p_value = 1.0
    else:
        p_value = wilcoxon(
            p_values,
            q_values,
            alternative="two-sided",
            method="auto"
        ).pvalue

    results.append({
        "Metric": name,
        "QL mean": q_values.mean(),
        "QL std": q_values.std(),
        "PPO mean": p_values.mean(),
        "PPO std": p_values.std(),
        "Mean paired difference (PPO - QL)": differences.mean(),
        "Median paired difference": differences.median(),
        "p-value": p_value,
        "Direction": direction,
    })

result_df = pd.DataFrame(results)

# Benjamini-Hochberg multiple-testing correction
pvals = result_df["p-value"].to_numpy()
n = len(pvals)
order = np.argsort(pvals)

adjusted = np.empty(n)
ranked = pvals[order] * n / np.arange(1, n + 1)
ranked = np.minimum.accumulate(ranked[::-1])[::-1]
adjusted[order] = np.minimum(ranked, 1.0)

result_df["Adjusted p-value"] = adjusted

print("\nPAIRED COMPARISON")
print(result_df.to_string(index=False))

output_path = "results/ppo_vs_qlearning_statistics.csv"
result_df.to_csv(output_path, index=False)

print(f"\nSaved results to: {output_path}")
