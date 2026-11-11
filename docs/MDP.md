# Phase 3 MDP: PPO next-cluster selection

This is the learning problem solved by the PPO variants. The code is `routing/env.py`; the
ns-3 side is `ExternalPolicy` in `simulation/ns3/wsn-uav/routing-policy.h`. If one changes,
change the other and this file.

## 1. Decision epoch and episode

- One episode is one ns-3 mission of `simTime` = 7200 s on one network.
- The UAV first flies the fixed survey lap (proposal Algorithm 1). This bootstraps the
  belief and hands every reachable CH its first promise. PPO takes no decisions during the lap.
- After that, PPO decides every time a visit ends: contact, contact timeout or hover cap.
- With the tour that is about 520 decisions per episode, one every 14 s on average. A policy
  that arrives early waits for the promised window (D8) and so takes fewer decisions.
- The episode ends at the horizon, so it is a fixed-horizon task. The time-of-mission feature
  keeps it Markov.
- Discount: γ = 0.99 per T0 = 15 s of mission time, so a decision that lasts Δt seconds is
  discounted by γ^(Δt/T0) (the proposal's semi-MDP discount). `routing/ppo_extras.py` does
  this in PPO's advantage computation; the env reports Δt as `info["dt"]`. A fixed γ per
  decision was tried first and rejected (§6).

## 2. Observation

Clusters are put in slots ordered by flight time from the UAV, nearest first, with the
current cluster last. Slots are padded to K_MAX = 40 (100-sensor networks have 21 to 37
clusters). Sorting makes "slot 0" mean "nearest cluster" on every network, so one policy works
across topologies.

Per slot, 13 features. Here P is the promise period (one tour lap, D7) and d_scale is the
readings generated network-wide during one average stop, N · λ · P / K.

| # | Feature | Normalisation |
|---|---|---|
| 0 | slot holds a real cluster | 0 / 1 |
| 1 | flight time from the UAV to the meeting point | / P |
| 2, 3 | meeting point relative to the UAV (x, y) | / area span |
| 4 | estimated buffer = estimated rate × time since contact | / d_scale, capped at 5 |
| 5 | estimated generation rate (EWMA from contacts) | × P / d_scale |
| 6 | CH residual energy reported at the last contact (1 if never contacted) | / E0 |
| 7 | time since last contact (mission time if never contacted) | / P, capped at 5 |
| 8 | has an outstanding promise | 0 / 1 |
| 9 | slack = promised time − now − flight time (0 if no promise) | / P, clipped to ±2 |
| 10 | missed meetings at this cluster | / 5, capped at 1 |
| 11 | never contacted | 0 / 1 |
| 12 | ETA-lateness quantile for this cluster (A2–A4 only, else 0) | / P |

Global features (3): mission time / simTime, and the UAV position x and y / area span.

**No future information.** Every feature is something the UAV knows at the decision:
- its own position and clock;
- the static meeting points;
- what each CH reported at its last contact;
- the promises it made;
- its own record of past lateness.

The true buffers, energies, future delays and failures are never sent. The per-run totals
on the bridge are used only for the reward.

`tests/test_rl_env.py` checks this. Between two decisions, a cluster that was not visited
keeps its last-contact rate, energy, missed count and flag. Only the clock-driven features
change, and they change by exactly the elapsed time.

## 3. Action and mask

- **Action:** a slot index in 0..39, meaning "fly to that cluster next".
- **Promise length (variant A4P only):** the policy also chooses how long the promise made at
  that cluster will be: 0.75, 1 or 1.5 × P (D7, option b). The action is then
  slot × 3 + factor index, 120 choices in all. The promise is handed to the CH when the UAV
  makes contact there.
  - Why: with a fixed 1 × P promise, only the tour order can keep every promise, so every
    other route is punished regardless of its merit. Choosing the length lets a different
    route keep its own promises.
  - The tour and all Phase 2 baselines always use 1 × P, so they are unchanged.
- **Mask:** padded slots and the current cluster are masked.
- **Promises:** breaking a promise is not masked. It is penalised (D7).
- **UAV battery:** not modelled, so there is no return-to-depot mask.

## 4. Reward

Per decision, from the change in the simulator's running totals since the previous decision:

    R = beta_d * R_D  -  beta_e * R_UAV  -  beta_m * R_miss  -  beta_c * R_CH  -  beta_r * R_risk

| Term | Definition | Default weight |
|---|---|---|
| R_D | readings delivered to the UAV / d_scale | 1.0 |
| R_UAV | (flight time × P_flight + hover time × P_hover) / (P_hover × P / K) | 0.2 |
| R_miss | scheduled windows that closed without the UAV (broken promises) | 1.0 |
| R_CH | Wi-Fi energy of all CH-capable nodes / energy of one CH listening through one fixed window (2 × wakeHalfWidth × I_idle × V = 12 J) | 0.25 |
| R_risk | A4/A4P only: for the chosen cluster, max(0, flight time + lateness quantile − time to promise − late window width) / P | 0.5 (A4/A4P), else 0 |
| F (shaping) | potential-based: Φ = −beta_m × (promises that can no longer be kept: flight time > time to promise + late window width); F = γ^(Δt/T0)·Φ(s') − Φ(s) | on for all final variants |

Notes:
- **Shaping does not change which policy is best** (Ng et al. 1999); it only reports a broken
  promise at the moment it becomes unavoidable, not when the window later closes. Evaluation
  returns in the handoff leave F out.
- **What the weights mean.** With these scales one average tour stop earns about +1 data.
  A broken promise costs about one stop's worth of data.
- **The UAV energy term.** The UAV is always either flying or hovering, so over a fixed
  horizon its total energy hardly depends on the policy. R_UAV mostly acts as a cost per unit
  of time, and it penalises hovering, which draws more power than flying.
- **Why R_CH is in (changed 10 Nov).** The first version followed D18 and left the CH energy
  out. Every learner then found the same loophole: hover at meeting points and collect data
  through the CHs' retry and discovery listening after breaking their promises.
  - That costs 2.4 × the CH energy of the tour but only about 5 % less data, so it scored
    nearly as well as the tour.
  - CH listening energy is what the paper is about, so it belongs in the reward (the
    proposal's R_sensor term).
- **Why R_risk changed (10 Nov).** The first version summed the risk over *all* outstanding
  promises. That penalised the tour, which always has many promises nearly due, and rewarded
  policies that make few promises (tour −26 vs the hovering policy −2 per mission).
  - It now scores only the chosen cluster, closer to eq. (30).
  - It counts lateness beyond the window the CH will actually be listening, so an on-time
    tour arrival scores 0.

Reference returns on training networks (A4P settings, 3 networks):

| Policy | Return | Data | Missed meetings | R_CH |
|---|---|---|---|---|
| tour | 315 | 516 | 48 | 233 |
| hovering policy learned under the first reward | 176 | 487 | 72 | 552 |

## 5. Variants (TEAM_PLAN Phase 3, task 4)

| Variant | Lateness quantile in observation | Wake window | Risk term |
|---|---|---|---|
| A1 (model 5, PPO without ETA risk) | no | fixed ±wakeHalfWidth | no |
| A2 | yes | fixed | no |
| A3 | yes | adaptive (Phase 2 quantile) | no |
| A4 (model 6, full ER-PPO) | yes | adaptive | yes |
| A4P | yes | adaptive | yes, and the policy chooses the promise length |

"Fixed window" is the new simulator switch `adaptiveWindow = false`. The CH then listens
±wakeHalfWidth, but the UAV still keeps its lateness record, so A2 can observe the quantile.

## 6. Training and evaluation

- **Training:** MaskablePPO (sb3-contrib 2.8.0) on network seeds 101–300. Each episode draws a
  network at random.
- **Evaluation:** on network seeds 1–10, the same networks as the Phase 2 baselines, never
  seen in training. The policy acts deterministically.
- **Settings:** `configs/phase3_ppo.toml` for training, `configs/phase3_eval.toml` for
  evaluation. Results and commands: `docs/handoff/phase3.md`.
- **Network and warm start:** the policy scores every cluster with one shared network and a
  self-attention layer (`routing/networks.py`, `--arch scoring`), so it does not depend on slot
  order or cluster count. Before PPO starts, it is trained to copy the tour on 50 000 tour
  decisions, and its critic to predict the tour's returns (`--warm-start`).
- **Training fixes (10–11 Nov).** The first PPO runs drifted away from the tour into waiting at
  meeting points and never got back. Three changes fixed most of this
  (`configs/phase3_fixes.toml`, on-time meetings on held-out networks 83 % → 90 %, tour 92 %):
  - time-based discount (§1). With a fixed γ per decision, a policy that takes fewer, longer
    decisions sees more of the mission inside its discount horizon, which favours waiting;
  - after every PPO rollout, a few behaviour-cloning steps on tour decisions, with a weight that
    fades from 1 to 0 over the first 200 000 steps (`bc_weight`);
  - the shaping term F (§4).
- **Logged:** reward curves (`models/<name>/<variant>_train.monitor.csv`), training wall time
  (`<variant>.json`), and inference time per decision (`ppo.json` in every evaluation run).
