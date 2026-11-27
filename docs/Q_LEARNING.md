# Tabular Q-learning baseline (Bouhamed et al., 2020)

This adds a discretized tabular Q-learning baseline alongside PPO and the existing masked
Double-DQN. It reuses the same Gymnasium/ns-3 bridge, observation, action mask, reward and
held-out evaluation environment.

## Paper mapping

Bouhamed et al., “A UAV-Assisted Data Collection for Wireless Sensor Networks: Autonomous
Navigation and Scheduling”, IEEE Access, 2020, Section III-C (especially pp. 9–10,
Eqs. 18–22), use tabular off-policy Q-learning for selecting the next sensing node. Their
state contains service location, time slot and discretized UAV battery; actions select a
sensor or the charging station. Reward accounts for arrival, waiting, remaining data-window
time, priority and charging/battery considerations.

Our adaptation:
- **Action:** same valid next-cluster slot accepted by `WsnUavEnv.step`; there is no charging
action because the current simulator has no UAV recharging dynamics.
- **State:** compact discretization of observable mission time, UAV position, nearest-cluster
estimated buffer, observed CH energy, time since contact, promise slack, missed meetings,
never-contacted fraction, ETA lateness quantile and cluster count.
- **Reward:** exactly the project's `WsnUavEnv` reward, including collection, UAV energy,
missed meetings, CH Wi-Fi energy, optional risk and shaping.
- **Update:** `Q(s,a) += alpha * (r + gamma^(dt/t0) * max_a' Q(s',a') - Q(s,a))`.
- **Exploration:** epsilon-greedy; invalid/current/padded slots are always masked.

This is a method-level adaptation, not a literal reproduction: the source paper's sensor
acquisition windows and UAV recharging are not represented identically in our simulator.
We preserve our project's semi-MDP timing through `gamma ** (dt / t0)`.

## Train

```bash
python3 -m routing.q_learning configs/phase3_ppo.toml --variant A4 --episodes 10
python3 -m routing.q_learning configs/phase3_ppo.toml --variant A4 --episodes 500
```

Output: `models/phase3_qlearning/A4_qlearning.json` (sparse Q-table + metadata) and
`models/phase3_qlearning/A4_train.csv` (episode return, decisions, epsilon).

## Evaluate

Add this to `configs/phase3_eval.toml`:

```toml
[[variant]]
name = "qlearning_A4"
routing = "ppo"
model = "models/phase3_qlearning/A4_qlearning.json"
```

Then run the normal experiment runner. The corresponding integration change to
`routing/evaluate.py` is supplied separately in this patch bundle; see `evaluate_patch.py`.

Keep the same simulator stress, topology, reward variant and held-out seeds as the PPO
comparison. Report visited Q-state count and note state-discretization error.
