
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results_phase4" / "ppo_learning_curves"
FIGURES = OUTPUT / "figures"

FIGURES.mkdir(parents=True, exist_ok=True)

MODEL_GROUPS = {
    "Main PPO variants": {
        "A1": ROOT / "models/phase3_ppo/A1_ppo-scoring_ws_train.monitor.csv",
        "A2": ROOT / "models/phase3_ppo/A2_ppo-scoring_ws_train.monitor.csv",
        "A3": ROOT / "models/phase3_ppo/A3_ppo-scoring_ws_train.monitor.csv",
        "A4": ROOT / "models/phase3_ppo/A4_ppo-scoring_ws_train.monitor.csv",
        "A4P": ROOT / "models/phase3_fixes/C_ppo-scoring_ws_train.monitor.csv",
    },
    "Phase 3 fix variants": {
        "Fix A": ROOT / "models/phase3_fixes/A_ppo-scoring_ws_train.monitor.csv",
        "Fix B": ROOT / "models/phase3_fixes/B_ppo-scoring_ws_train.monitor.csv",
        "A4P (Fix C)": ROOT / "models/phase3_fixes/C_ppo-scoring_ws_train.monitor.csv",
        "Fix D": ROOT / "models/phase3_fixes/D_ppo-scoring_ws_train.monitor.csv",
    },
}

summary_rows = []

for group_name, models in MODEL_GROUPS.items():
    fig, ax = plt.subplots(figsize=(11, 6))

    for label, path in models.items():
        if not path.exists():
            print(f"WARNING: Missing {path}")
            continue

        df = pd.read_csv(path, skiprows=1)

        if not {"r", "l"}.issubset(df.columns):
            print(f"WARNING: Unexpected columns in {path}")
            continue

        episodes = range(1, len(df) + 1)
        rolling = df["r"].rolling(window=25, min_periods=1).mean()

        # Raw episode rewards, shown faintly.
        ax.plot(
            episodes,
            df["r"],
            alpha=0.15,
            linewidth=0.7,
        )

        # Smoothed reward trend.
        ax.plot(
            episodes,
            rolling,
            linewidth=2,
            label=label,
        )

        summary_rows.append({
            "group": group_name,
            "model": label,
            "episodes": len(df),
            "mean_episode_reward": df["r"].mean(),
            "std_episode_reward": df["r"].std(),
            "mean_episode_length": df["l"].mean(),
            "final_25_episode_reward": df["r"].tail(25).mean(),
        })

    ax.set_title(f"PPO Training Reward - {group_name}")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Episode Reward")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()

    filename = (
        "main_ppo_reward.png"
        if group_name == "Main PPO variants"
        else "phase3_fixes_reward.png"
    )
    fig.savefig(FIGURES / filename, dpi=300)
    plt.close(fig)

# Supplementary episode-length figure for the main PPO variants.
fig, ax = plt.subplots(figsize=(11, 6))

for label, path in MODEL_GROUPS["Main PPO variants"].items():
    if not path.exists():
        continue

    df = pd.read_csv(path, skiprows=1)
    rolling = df["l"].rolling(window=25, min_periods=1).mean()

    ax.plot(
        range(1, len(df) + 1),
        rolling,
        linewidth=2,
        label=label,
    )

ax.set_title("PPO Training Episode Length")
ax.set_xlabel("Episode")
ax.set_ylabel("Episode Length (steps)")
ax.grid(True, alpha=0.25)
ax.legend()
fig.tight_layout()
fig.savefig(FIGURES / "main_ppo_episode_length.png", dpi=300)
plt.close(fig)

summary = pd.DataFrame(summary_rows)
summary.to_csv(OUTPUT / "training_summary.csv", index=False)

print("\nPPO learning-curve generation complete.")
print(f"Figures: {FIGURES}")
print(f"Summary: {OUTPUT / 'training_summary.csv'}")
print("\nTraining summary:")
print(summary.round(3).to_string(index=False))
