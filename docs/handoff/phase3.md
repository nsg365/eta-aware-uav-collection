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

## 10. Follow-up: the models on Prakruthi's Gaussian-hotspot networks (19 Nov, rerun 27 Nov)

The A1–A4 and A4P models (trained on 100-sensor uniform networks) were run unchanged on the
Gaussian-hotspot networks of `configs/phase2_gaussian_*.toml` (4 hotspots, 100/1000/2000
sensors, 10 networks each). Noise is sir's setting: UAV speed uniform 9–11 m/s per leg
(`uavSpeedJitter = 0.1`), no extra UAV delay, plus the usual CH failures.
Config: `configs/phase3_gaussian_scaling.toml`.

| Sensors (clusters) | Tour PDR / on-time | Best other baseline PDR | A4 PDR / on-time | A3 PDR / on-time |
|---|---|---|---|---|
| 100 (4.4) | 0.994 / 1.000 | 0.993 (nearest feasible) | 0.994 / 1.000 | 0.992 / 0.954 |
| 1000 (5.7) | 0.857 / 1.000 | 0.850 (nearest feasible) | 0.857 / 1.000 | 0.827 / 0.951 |
| 2000 (7.0) | 0.605 / 1.000 | 0.604 (nearest feasible) | 0.603 / 1.000 | 0.580 / 0.951 |

- The models carry over to these networks without retraining. A4 matches the tour at every
  size (PDR difference 0.2 points or less).
- The PDR drop at 1000/2000 sensors is buffer overflow (tour: 14 % and 39 % of the data), the
  same for every policy that keeps its promises. No visiting order fixes it, since each CH
  serves 170–290 sensors and its 2000-reading buffer fills before the UAV can return.
- Data greedy and energy-data score fall further behind as the network grows (PDR 0.48 and
  0.43 at 2000 sensors).
- Out of distribution, the risk term matters: A3 (no risk term) loses 3.0 ± 2.4 points of PDR
  at 1000 sensors and keeps only 95 % of its meetings, while A4 stays with the tour. A4P is
  slightly worse than A4 (−0.4 to −0.5 points).
- The first run of this set (19 Nov) used speed std 1 m/s instead of uniform 9–11 m/s; every
  PDR moved by under 2.5 points and the conclusions are the same.

## 11. Follow-up: the models on Prakruthi's CH-count sweep (24 Nov)

Same models, unchanged, on Prakruthi's CH-count sweep (`scripts/run_ch_sweep.py`,
`configs/ch_sweep_params.json`): 1000 sensors, Gaussian hotspots, cluster size capped so the
networks have about 6, 10, 15 and 20 clusters, 10 networks each. Noise is sir's setting: UAV
speed uniform 9–11 m/s per leg (`uavSpeedJitter = 0.1`), no extra delays, no CH failures.
Configs: `configs/phase3_ch_sweep_05/10/15/20.toml` (her networks plus the PPO variants).
Plots: `python3 scripts/plot_ch_sweep_ppo.py`.

PDR (%), mean of the 10 networks:

| Clusters (median) | Tour | Nearest feasible | Data greedy | Energy-data score | A4 | A4P | A3 |
|---|---|---|---|---|---|---|---|
| 6 | 98.7 | 98.7 | 97.0 | 96.9 | 98.7 | 98.3 | 96.0 |
| 10 | 98.9 | 98.9 | 79.8 | 66.4 | 99.0 | 98.9 | 98.7 |
| 15 | 98.8 | 96.9 | 80.1 | 63.9 | 98.7 | 98.7 | 98.5 |
| 20 | 98.1 | 77.7 | 72.5 | 55.8 | 97.9 | 98.0 | 97.0 |

- A4 and A4P stay within 0.4 points of the tour at every cluster count (paired difference,
  95 % interval includes zero or is under half a point). The tour keeps 100 % of its meetings,
  A4 98.5–100 %.
- The other baselines fall apart as clusters go up: at 20 clusters data greedy keeps 53 % of
  its meetings and energy-data score 41 %, and nearest feasible starts skipping far clusters.
- UAV total energy is nearly flat (1090–1140 kJ) because the UAV flies or hovers for the whole
  run, so the plots also show UAV energy per delivered reading: about 1.55 J for the tour and
  PPO at every cluster count, 2.1–2.8 J for the other baselines at 15–20 clusters.
- A3 (no risk term) is again the weakest PPO variant, 1–2.6 points behind at 6 and 20 clusters.
- The same sweep with the older noise (speed std 1 m/s) gave the same picture; every number
  moved by under 2 points.

## 12. Retraining on sir's setting (steps for whoever runs it)

`configs/phase3_ppo_sir.toml` retrains the same variants with sir's noise (UAV speed uniform
9–11 m/s per leg, no extra delays, CH failures on). A1–A4P train on 100-sensor networks
(uniform and 4 Gaussian hotspots, alternating by seed). A4M is A4 trained on the full mix we
report on (uniform 100, Gaussian 100/1000 and the four CH-sweep networks, 3–37 clusters). The
reward, training fixes and seeds (train 101–300, evaluation 1–10) are unchanged.

**1. Setup** (once). Pull main, then:

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt               # now includes torch, stable-baselines3, sb3-contrib
    (cd ../ns3-workspace/ns-3.47 && ./ns3 build wsn-uav)   # rebuild: the simulator needs uavSpeedJitter
    python3 -m pytest -q                          # all tests should pass

**2. Train** (one variant at a time; each uses 8 simulator processes). On a 10-core laptop:
about 35–40 min for each of A1–A4P and 3–4 h for A4M. Run it overnight and keep the computer
awake (`caffeinate -i` on a Mac; on WSL, keep Windows from sleeping):

    for v in A4 A1 A2 A3 A4P A4M; do
      python3 -m routing.train configs/phase3_ppo_sir.toml --arch scoring --warm-start --variant $v
    done 2>&1 | tee train_sir.log

Each finished variant prints one line (`... steps in N min -> models/phase3_ppo_sir/...`) with
the warm start's tour agreement (should be about 0.99). If the run stops, start the loop again
with only the variants that have no `.zip` yet. With fewer cores, add `--n-envs 4`.

**3. Hand back.** Commit `models/phase3_ppo_sir/` (the `.zip`, `.json` and `_train.monitor.csv`
of each variant) on a branch and open a PR, with the finished-variant lines of `train_sir.log`
in the PR description (do not commit the log). Evaluation (Gaussian
100/1000/2000 and the CH sweep) is then rerun with the new models on the Phase 3 side.

## 13. Event bursts: can PPO beat the tour when traffic changes over time? (28 Nov)

The simulator now has event bursts (`burstsPerHour`, `burstDuration`, `burstMultiplier` in
`config.h`, off by default): at random times one random cluster's sensors read faster for a
while. Every policy with the same seed sees the same bursts. Setting used: 100-sensor uniform
networks, sir's noise, 4 bursts per hour, 20x for 30 min. A bursting cluster fills its buffer
in about 5 min and one tour lap takes about 7 min, so the tour loses data at every burst.

A4P was trained on this (`configs/phase3_ppo_bursts.toml`, promise lengths 0.5–1.5x of a lap)
twice: with the usual copying step (A4P) and with the copying step fading out after 100k of
300k decisions (A4Pb). Evaluation: `configs/phase3_bursts_eval.toml`, 10 held-out networks.

| Policy | PDR | PDR minus tour | Burst data lost | On-time |
|---|---|---|---|---|
| Tour | 0.817 | — | 28 % | 100 % |
| Data greedy | 0.624 | −19.3 ± 5.0 | 53 % | 25 % |
| A4P trained without bursts | 0.762 | −5.5 ± 2.3 | 37 % | 84 % |
| A4P trained on bursts | 0.817 | 0.0 (identical to the tour) | 28 % | 100 % |
| A4Pb trained on bursts | 0.772 | −4.5 ± 1.9 | 33 % | 81 % |

PPO either follows the tour exactly or leaves it and does worse: every detour to a full cluster
breaks promises made to the others, and the UAV only learns of a burst at its next visit to
that cluster. To beat the tour a policy would need earlier news of a burst or a way to change
promises already made. All tables and plots: `results_phase3_ppo/README.md`.

## 14. Q-learning baseline on every deployment, demo page and paper (28 Nov)

Thiaana's tabular Q-learning baseline (`routing/q_learning.py`, `docs/Q_LEARNING.md`, adapted
from Bouhamed et al., IEEE Access 2020) was run on the same networks as every Phase 3 evaluation:
`configs/qlearning/*.toml`, results in `results/qlearning_<experiment>/`.

| Deployment | Tour | PPO A4 | Q-learning |
|---|---|---|---|
| Uniform 100, stress noise (10 networks) | 0.972 | 0.973 | 0.718 |
| Gaussian 1000 / 2000 sensors | 0.857 / 0.605 | 0.857 / 0.603 | 0.487 / 0.274 |
| CH sweep, 6 / 20 clusters | 0.987 / 0.981 | 0.987 / 0.979 | 0.547 / 0.296 |
| Event bursts | 0.817 | 0.817 (trained on bursts) | 0.451 |

Its state describes only the nearest cluster, so it cannot tell the other candidates apart, and
on unseen networks it often meets states it never saw, where all values are equal and it picks at
random. Its result therefore varies between runs on the same networks (0.677 and 0.718 on the
uniform set). The saved table has 52,862 updates while exploration was set to decay over 100,000,
so it is a weak version of the method, not a fair measure of the original paper.

**Demo page** (`demo/phase3/`): one page for the whole project (system, algorithms, PPO, results,
robustness, limits). The mission replay shows six policies (tour, ER-PPO A4, plain PPO A1,
nearest feasible, data greedy, Q-learning) on nine deployments, each with its 10 held-out
networks. Formulas are written in LaTeX in `template.html` and turned into MathML by `build.py`
(`latex2mathml`, no internet needed).

**Paper** (`paper/`): `main.tex` with four figures (`make_figures.py` draws Figs. 2–4 from the
results). Next steps, including sir's reward suggestion after the demo: `docs/NEXT_STEPS.md`.
