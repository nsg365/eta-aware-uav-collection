# Phase 3 Handoff — PPO next-cluster selection (ER-PPO) and its ablations

**Owner:** Nihar
**Phase:** Phase 3
**Implementation period:** 10–11 November 2026
**Branch:** `phase3-nihar` (built on `main` at 15be8f9, Phase 2 merged)

---

## 1. Summary

- ns-3 now talks to a Python agent through two pipes (`routing=external`), and PPO chooses the
  next cluster at every visit. The MDP is in `docs/MDP.md`.
- Variants A1–A4 (TEAM_PLAN Phase 3, task 4) and A4P (the policy also chooses the promise
  length) are trained and saved under `models/`.
- **Main result:** on the 10 held-out networks, every PPO variant is statistically
  indistinguishable from the ETA-aware tour it is compared with (paired 95 % CIs all include 0).
  PDR is 0.971–0.973 for all of them, against 0.598–0.907 for the other Phase 2 baselines.
- **Why PPO does not beat the tour:** §6 gives the evidence that the tour is close to optimal in
  this simulator. Even a hand-written rule that detours to nearly full clusters loses badly to
  it, also on uneven (hotspot) traffic.
- 41 tests pass (`python3 -m pytest`), including 6 new ones for Phase 3.

| TEAM_PLAN "done when" | Status |
|---|---|
| `docs/MDP.md` complete; no future information in the observation | Done; checked by `tests/test_rl_env.py` |
| PPO vs best Phase 2 baseline on held-out seeds, mean ± 95 % CI | Done (§5) |
| Phase 4 can evaluate every PPO variant with one command | Done (§7) |

## 2. What was built

| Part | Files |
|---|---|
| External routing policy and pipe bridge | `simulation/ns3/wsn-uav/routing-policy.h` (`ExternalPolicy`), `config.h` (`bridgeFdIn`, `bridgeFdOut`) |
| Fixed-window switch for A1/A2 | `config.h` (`adaptiveWindow`), `uav-app.cc` |
| Promise length chosen by the policy (D7 option b) | `RoutingPolicy::PromiseFactor()`, `uav-app.cc` |
| Lateness quantile per cluster in the observation | `ClusterBelief.lateQuantile`, `UavApp::LatenessQuantile` |
| Gym environment (observation, mask, reward) | `routing/env.py` |
| Per-cluster scoring network with self-attention | `routing/networks.py` |
| Time-based discount, behaviour cloning during PPO | `routing/ppo_extras.py` |
| Training (PPO, plus masked DQN used in the comparison) | `routing/train.py`, `routing/dqn.py` |
| Evaluation as an ordinary experiment variant | `routing/evaluate.py`, `experiments/run_experiment.py` |
| Red-team checks (§6) | `routing/redteam.py` |
| Tests | `tests/test_rl_env.py`, `tests/test_ppo_extras.py` |
| Configs | `configs/phase3_ppo.toml`, `phase3_eval.toml`, `phase3_fixes.toml`, `phase3_hotspot.toml` |

With the tour, the new code paths give bit-for-bit the same results as before: the external
policy following the tour reproduces `routing=tour` exactly (`tests/test_rl_env.py`).

## 3. The learning problem (short version; full detail in `docs/MDP.md`)

- **Decision:** after every visit, choose the next cluster (and, for A4P, the promise length
  0.75, 1 or 1.5 × P). Padded slots and the current cluster are masked.
- **Observation:** 13 features per cluster, sorted nearest first, padded to 40 clusters, plus
  the mission time and UAV position. Only what the UAV knows: its own clock and position, what
  each CH reported at its last contact, its promises and its own lateness record.
- **Reward per decision:**

      R = 1.0 * data delivered - 0.2 * UAV energy - 1.0 * broken promises
          - 0.25 * CH Wi-Fi energy - 0.5 * risk (A4/A4P only) + shaping

  Each term is scaled so one average tour stop earns about +1 for data (MDP.md §4).
- **Discount:** 0.99 per 15 s of mission time.

## 4. Training

- MaskablePPO (sb3-contrib 2.8.0), 8 parallel simulations, 300 000 decisions per variant,
  about 17–19 minutes each on an M4 MacBook (A1 18.7, A2 16.7, A3 16.6, A4 17.5 min).
- Network seeds 101–300 for training, seeds 1–10 for evaluation.
- **Setup used for all final variants** (MDP.md §6; each was needed, see the table below):
  1. per-cluster scoring network with one self-attention layer;
  2. warm start: copy the tour on 50 000 tour decisions (99.2–99.9 % agreement afterwards);
  3. time-based discount;
  4. behaviour-cloning steps on tour decisions during PPO, fading out over the whole run;
  5. shaping on promises that can no longer be kept.

**How we got there** (5 held-out networks, uniform traffic, A4P settings; tour: 92.4 % on-time,
PDR 0.972, CH 91 J). These runs used warm-start returns with a fixed 0.99 per decision; the
final A1–A4 and C were retrained with the time-based discount (see §8):

| Setup | On-time meetings | PDR | CH energy (J) | Note |
|---|---|---|---|---|
| First reward (no CH-energy term), any learner | 14–62 % | 0.88–0.91 | 200–300 | all learned to hover and collect through retry listening (D18 outcome) |
| + CH-energy term, warm start | 82.9 % | 0.952 | 124 | drifted to fewer, longer decisions |
| + time-based discount (A) | 84.8 % | 0.967 | 120 | drift stopped |
| + behaviour cloning during PPO (B) | 87.0 % | 0.967 | 162 | |
| + shaping (C) = final setup | 90.1 % | 0.969 | 131 | |

PPO from scratch, an MLP policy and masked double DQN (with and without tour demonstrations)
were all tried on the first reward and did worse than the warm-started scoring PPO.

## 5. Results on the 10 held-out networks

Same stress as training (10 % of legs delayed by U(10, 30) s, one CH hardware failure per
10 h), 100 sensors, 2 h missions, mean ± 95 % CI over seeds 1–10
(`results/phase3_eval/summary.md`).

| Variant | PDR | On-time meetings | CH energy (J) | CH Wi-Fi awake |
|---|---|---|---|---|
| tour, fixed window (model 4) | 0.972 ± 0.006 | 0.852 ± 0.051 | 96.8 ± 12 | 0.043 |
| tour, adaptive window | 0.972 ± 0.004 | 0.910 ± 0.022 | 95.1 ± 12 | 0.042 |
| nearest feasible | 0.598 ± 0.075 | 0.867 ± 0.019 | 122 ± 13 | 0.056 |
| data greedy | 0.907 ± 0.041 | 0.247 ± 0.059 | 238 ± 21 | 0.165 |
| energy-data score | 0.878 ± 0.026 | 0.189 ± 0.041 | 230 ± 21 | 0.161 |
| PPO A1 (model 5) | 0.972 ± 0.006 | 0.859 ± 0.041 | 92.6 ± 9.7 | 0.041 |
| PPO A2 | 0.971 ± 0.008 | 0.815 ± 0.099 | 108 ± 28 | 0.048 |
| PPO A3 | 0.972 ± 0.006 | 0.885 ± 0.059 | 113 ± 34 | 0.051 |
| PPO A4 (model 6, ER-PPO) | 0.973 ± 0.005 | 0.885 ± 0.055 | 114 ± 40 | 0.052 |
| PPO A4P | 0.971 ± 0.006 | 0.903 ± 0.025 | 100 ± 16 | 0.045 |

**Paired difference from the matching tour** (same network, PPO minus tour; A1/A2 against the
fixed-window tour, A3/A4/A4P against the adaptive one):

| Variant | PDR (points) | On-time (points) | CH energy (J) |
|---|---|---|---|
| A1 | +0.00 ± 0.03 | +0.7 ± 2.3 | −4.2 ± 7.8 |
| A2 | −0.09 ± 0.26 | −3.7 ± 6.0 | +10.8 ± 21.0 |
| A3 | −0.04 ± 0.30 | −2.5 ± 4.7 | +17.6 ± 27.4 |
| A4 | +0.02 ± 0.23 | −2.5 ± 4.4 | +19.2 ± 33.8 |
| A4P | −0.14 ± 0.24 | −0.7 ± 0.8 | +5.0 ± 8.2 |

**Reading:**
- All PPO variants match the tour; none is significantly better or worse.
- Against the best non-tour baseline (data greedy), every PPO variant has clearly higher PDR,
  about 3.6 × the on-time rate and less than half the CH energy.
- The adaptive window helps, both for the tour (0.852 → 0.910 on-time) and for PPO
  (A2 0.815 → A3 0.885). A4's risk term gives no measurable gain over A3 (0.885 both); A4P
  is the closest to the tour (0.903, CH 100 J).
- CH energy varies more between PPO runs than PDR does: a retrain of the same setup moved A4
  from 101 to 114 J and A4P from 115 to 100 J, always within the CIs above.
- A4P never used the 0.75 × or 1.5 × promise on held-out networks.
- Inference: 1.5–1.6 ms mean, 2.8 ms p95 per decision on CPU (`ppo.*` in `runs.csv`).

## 6. Is the tour just hard for PPO, or hard to beat at all?

Three checks (`routing/redteam.py`, 5 held-out networks each):

1. **Uneven traffic.** Experiment D trained the final setup on 20-hotspot networks with CH
   buffers of 250 readings, where the tour loses 8.9 % of data to overflow. D ended up
   choosing exactly the tour's action at 100 % of decisions, with identical results
   (return 237.8, PDR 0.896).
2. **Hand-written detours on the same hotspot networks.** Follow the tour, but detour to any
   cluster whose estimated buffer on arrival is ≥ θ × capacity, then resume the tour:

   | Policy | Return | PDR | Overflow | On-time | CH J |
   |---|---|---|---|---|---|
   | tour | 238 | 0.896 | 8.9 % | 95 % | 103 |
   | detour at θ = 0.7 | −58 | 0.716 | 25.7 % | 53 % | 287 |
   | detour at θ = 0.85 / 1.0 | −93 / −129 | 0.68 / 0.63 | 29–34 % | 35–45 % | 230–270 |
   | 0.75 × P promises at overflow-prone clusters | −32 | 0.818 | 16.1 % | 71 % | 242 |

   Each detour is a long flight (279 m per visit on average vs 129 m on the tour), and the clusters
   skipped meanwhile miss their promised windows. With θ set so high that no detour happens,
   the rule reproduces the tour exactly, so the check itself is sound.
3. **Uniform traffic: the models do not just copy the tour.** After the warm start a model
   picks the tour's next stop 99.2–99.9 % of the time. After PPO, on 5 held-out networks:

   | Model | Same as tour | Most urgent promise instead | Skips one tour stop | Other |
   |---|---|---|---|---|
   | A1 | 84.8 % | 7.3 % | 5.6 % | 2.3 % |
   | A2 | 84.9 % | 4.8 % | 4.6 % | 5.7 % |
   | A3 | 77.8 % | 8.2 % | 5.7 % | 8.3 % |
   | A4 | 79.8 % | 4.8 % | 7.0 % | 8.4 % |
   | A4P (C) | 86.9 % | 4.9 % | 5.4 % | 2.8 % |

   So PPO learned "the tour, with corrections": typically going first to a cluster whose
   promise is about to run out. The corrections help on some networks (network 3: A4 delivers
   0.973 vs the tour's 0.970) and cost on others, and they even out over 10 networks.
   PPO without the warm start reached only 59 % on-time meetings (PDR 0.926) in the same
   training budget.

**Conclusion:** with promise-at-contact wake windows of one lap, any change of visiting order
breaks promises, and the cost of that outweighs what it gains. The tour is close to optimal
here, and learning to match it is the correct outcome, not a training failure. A reward-weight
search was considered and dropped: weights cannot create a gain that a direct rule cannot find.

## 7. Commands

Setup as in `docs/SETUP.md`; on the Mac used here, Python 3.14 and Homebrew's cmake:

    export PATH=/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:$PATH

**Phase 4: evaluate every variant and baseline (one command, about 1 minute):**

    python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
    python3 -m analysis.aggregate results/phase3_eval/runs.csv

Any experiment config can use a trained model as a variant:

    [[variant]]
    name = "er_ppo"
    routing = "ppo"
    model = "models/phase3_ppo/A4_ppo-scoring_ws.zip"

The model's `.json` applies its own variant settings (e.g. `adaptiveWindow = false` for A1/A2)
on top of the experiment's `[simulation]` table. Models are trained for 100 sensors.

**Retrain (about 20 min each):**

    python3 -m routing.train configs/phase3_ppo.toml --variant A4 --algo ppo --arch scoring --warm-start --timesteps 300000

**Red-team checks (§4 table and §6):**

    python3 -m routing.train configs/phase3_fixes.toml --variant C --algo ppo --arch scoring --warm-start --timesteps 300000
    python3 -m routing.redteam models/phase3_fixes/C_ppo-scoring_ws.zip tour agreement
    python3 -m routing.redteam models/phase3_fixes/D_ppo-scoring_ws.zip tour agreement buffer:0.7 buffer:0.85 buffer:1.0 short:9

**Demo page** (mission replay of held-out network 3 and the results above; needs the
evaluation results first):

    python3 demo/phase3/build.py
    python3 -m http.server 8000 --directory demo/phase3     # then open http://localhost:8000

## 8. Models

| File | What |
|---|---|
| `models/phase3_ppo/A1..A4_ppo-scoring_ws.zip` | final variants; `.json` = settings, `_train.monitor.csv` = reward per training episode |
| `models/phase3_fixes/C_ppo-scoring_ws.zip` | A4P (used as `ppo_A4P` in `phase3_eval.toml`) |
| `models/phase3_fixes/A, B, D_*` | red-team runs of §4 and §6; trained before the warm-start fix below and not retrained |

**Warm-start fix (12 November).** The warm start first computed the tour's returns with a fixed
0.99 per decision, while PPO discounts 0.99 per 15 s. `tour_rollouts` now uses the same
time-based discount (MDP.md §1). Tour decisions take 13.3 s on average, so this only lengthens
the critic's starting horizon a little (about 113 instead of 100 decisions). A1–A4 and C were
retrained and evaluated again; every result stayed within its earlier CI, and the tables above
are the retrained numbers.

## 9. Limitations and open points

- Only 100-sensor networks and one stress level were trained and evaluated. A Phase 4 sweep
  over network size or delay needs either retraining or a check that the 100-sensor models
  carry over.
- 300 000 decisions per variant (about 600 missions). The 1M-decision run of the first
  setup did not improve on its 300 000 result, but longer training of the final setup was not
  tried.
- The optional quantile MLP (eqs. 13–16) was not built; Phase 2's empirical quantile is used.
- Where the tour is not close to optimal (e.g. a different wake scheme, or no promises), PPO
  might gain. Not tested.
