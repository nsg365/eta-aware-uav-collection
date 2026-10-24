# Team plan: four sequential phases (deadline 30 Nov 2026)

The work is done in four phases, **one person per phase, one after another**. Each phase ends
with a hand-off: the next person starts only when the previous phase meets its "done when"
checklist. Shared file formats and metrics are in [INTERFACES.md](INTERFACES.md). Every
deviation from the proposal goes into [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

| Phase | Owner | Content | Dates (target) |
|---|---|---|---|
| 0 | done | Core simulation, 3 wake modes, runner, tests | done 23 Oct |
| 1 | Person 1: Shreya | Simulator realism + reliability (failures, backup CH, retries, delays, drift) | 24 Oct – 3 Nov |
| 2 | Person 2: Prakruthi | UAV belief state, promise rule, heuristic baselines, ETA lateness + adaptive window | 4 Nov – 12 Nov |
| 3 | **Nihar Sagar G** | **Reinforcement learning: ns-3 ↔ Python bridge, MDP, PPO, PPO ablations** | 13 Nov – 23 Nov |
| 4 | Person 4: thiana | Full experiments, statistics, figures, paper/report | 24 Nov – 30 Nov |

Already decided (see DESIGN_DECISIONS.md D7): at every contact the UAV promises the CH a return
time T_k = now + P (P = nominal tour period). Every routing policy, including PPO, works under
these promises; a broken promise is a missed meeting.

**Why this order.** PPO (Phase 3) must be trained on the *final* simulator, including failures,
delays, baselines and the belief state it observes. Otherwise every simulator change after
training forces a retrain. Phase 4 needs everything else finished.

**Hand-off rule, every phase.**
1. `python3 -m pytest` passes, with new tests for the new mechanisms.
2. New config keys are documented in `config.h`, and new metrics in INTERFACES.md.
3. Decisions are recorded in DESIGN_DECISIONS.md.
4. A short `docs/handoff/phaseN.md` says what was done, what was not, and the exact commands to
   reproduce the phase's results.
5. Everything is pushed to GitHub.

**While waiting.** Nobody should change code owned by the active phase. Waiting members can do
non-blocking preparation: read the code and docs, and (Person 4) start the paper parts that do
not depend on results (related work, notation table, system model). Nihar can prototype the
Phase 3 bridge on the current simulator. The `RoutingPolicy` interface is already fixed, so
this does not touch Phase 1/2 files.

---

## Phase 1 — Simulator realism and reliability (Person 1 - shreya)

Goal: make the simulator realistic and stressful enough that routing and wake scheduling
matter, and add the paper's reliability mechanisms.

Files: `simulation/ns3/wsn-uav/{wsn-uav.cc, world.*, ch-app.*, protocol.h, config.h}`, `tests/`

Tasks:
1. **Energy parameters (D11).** Replace the placeholder Wi-Fi and 802.15.4 currents with values
   from cited datasheets, and add a table with sources to DESIGN_DECISIONS.md.
2. **Wi-Fi range calibration.** Run a sweep of delivery ratio vs UAV–CH distance over the
   simulated link, and set `uav_range_m` (R_UAV) from it instead of assuming 80 m.
3. **Stressors** (so missed meetings can happen):
   - UAV delay events: with probability `uavDelayProb` per leg, add a random extra delay.
   - Per-CH clock offset, bounded by `w_drift`, applied to when the CH thinks the window opens.
4. **Reliability (paper Sec. III-F/G):**
   - Primary CH failure: random hazard `µ_CH` plus battery depletion.
   - Heartbeats from primary to backup; the backup takes over after `m_h` missed heartbeats.
     It holds a replicated buffer copy every `T_rep`, and a new backup is elected.
   - A CH-UPDATE tells the UAV which node is now the primary.
   - Missed window → RETRY window at `τ_k⁺ + m_k·Δ_r` (eq. 20). After `M_max` misses →
     DISCOVERY.
   - A missed UAV meeting must **never** trigger failover (the paper's key distinction).
   - Stretch: energy-triggered CH re-election with the corrected score (D3).
5. **New metrics:** CH failures, backup promotions, failover time, data lost in failover,
   retries, re-bootstraps, promise violations.

Done when:
- [ ] Tests cover failure → promotion, missed meeting → retry (no failover), and data
      conservation with failures on.
- [ ] Wake-mode example experiment re-run with stressors on; results in `docs/handoff/phase1.md`.
- [ ] Energy table with citations committed.

## Phase 2 — UAV belief, baselines, ETA lateness and adaptive windows (Person 2 - pakku)

Goal: everything the RL phase needs to plug into, plus the non-learning comparison models.

Files: `simulation/ns3/wsn-uav/{uav-app.*, routing-policy.h}`, `clustering/`, new `eta/`

Tasks:
1. **UAV belief state** per cluster, held on the UAV (eqs. 26–27, Table II): last-contact buffer
   and energy, estimated generation rate λ̂ (EWMA), time since contact, time until its promise
   T_k, missed-meeting count, never-contacted flag. Expose it as one function returning a flat
   vector. **This becomes the PPO observation in Phase 3**, so document every entry and its unit.
2. **Promise rule for every policy (D7):** T_k = now + P. Lift the restriction that scheduled
   wake mode only works with the fixed tour.
3. **Baselines (paper Sec. V, models 1–4):** nearest-feasible, data-greedy (on the *belief*, not
   true buffers), energy/data score, and TSP + fixed wake (exists). "Feasible" must exclude the
   current cluster and avoid ping-ponging between two clusters; document the definition.
4. **Clustered deployment generator** (Gaussian hotspots) as an alternative to uniform (D5).
5. **ETA lateness model (D9, D10).** No deep learning needed:
   - from `visits.csv`, lateness e = actual arrival − promised arrival;
   - an empirical upper quantile q_p of e, per simple bin (e.g. by number of stops since the
     promise);
   - adaptive window: CH listens on [T_k − w_drift − w_margin, T_k + w_drift + q_p] (asymmetric,
     D8);
   - sweep p ∈ {0.8, 0.9, 0.95, 0.99} and report CH listening energy vs meeting success.

Done when:
- [ ] Every baseline runs in an example config and is tested (e.g. nearest-feasible never picks
      the current cluster).
- [ ] Belief vector documented in INTERFACES.md (entries, units, normalisation scale).
- [ ] Baseline comparison table + p-sweep plot in `docs/handoff/phase2.md`.

## Phase 3 — Reinforcement learning (Nihar)

Goal: the paper's ER-PPO and its PPO ablations, trained and evaluated reproducibly.

Files: new `routing/` (Python env, training, evaluation), `ExternalPolicy` in `routing-policy.h`,
optional `eta/` MLP

Tasks:
1. **Bridge** between ns-3 and Python. ns3-gym and ns3-ai are not installed and unverified with
   ns-3.47 / Python 3.14. One decision per UAV visit (about 500 per 2 h episode, about 2–3 s per
   episode) means a small socket/pipe bridge may be enough. Decide early; ask the team before
   adding a major dependency.
2. **MDP specification** (`docs/MDP.md`), written before training:
   - observation = Phase 2 belief vector + UAV state;
   - action = next cluster, with masking of the current/nonexistent clusters;
   - reward = start with R_D − β_E·R_UAV − β_M·R_miss (D18), add terms only if ablations
     justify them;
   - episode = fixed horizon, fixed γ first;
   - explicitly: **no future arrival times, delays or failures in the observation.**
3. **Training** with `MaskablePPO` (sb3-contrib 2.8.0, installed). Training seeds and evaluation
   seeds are disjoint. Log reward curves, training wall time and per-decision inference time.
4. **Variants for the paper's comparisons and ablations:**
   - model 5 / A1: PPO, no ETA risk, fixed window;
   - A2: + lateness quantile in the observation;
   - A3: + adaptive window;
   - A4 (full ER-PPO): + risk term in the reward.
   - Optional: replace Phase 2's empirical quantile with the quantile MLP (eqs. 13–16) only if it
     beats it on held-out pinball loss and coverage.
5. **Hand-off for non-RL users:** trained models saved under `models/`, and evaluation runnable
   as an ordinary experiment variant (`routing = "ppo"`, `model = ...`), so Phase 4 can run
   everything without RL knowledge.

Done when:
- [ ] `docs/MDP.md` complete; the env passes a check that observations contain no future
      information.
- [ ] On held-out seeds, PPO is compared with the best Phase 2 baseline (mean ± 95 % CI). This is
      reported honestly even if PPO does not win.
- [ ] Phase 4 can evaluate every PPO variant with one command, documented in
      `docs/handoff/phase3.md`.

## Phase 4 — Experiments, statistics, paper (Person 4 - thiana)

Goal: the final numbers, figures and write-up, all reproducible from the repository.

Files: `experiments/`, `analysis/`, `configs/`, paper sources

Tasks:
1. **Experiment matrix:**
   - comparison models 1–6 and ablations A1–A9 (one mechanism changed per variant);
   - N ∈ {60, 100, 150};
   - at least 10 seeds;
   - sweeps over UAV delay probability, CH failure rate and clock drift.
2. **Statistics:** paired per-seed differences with 95 % CIs (variants share seeds and
   traffic). Lifetime is reported with censoring, never averaged as if every node died.
3. **Figures** generated by script from `runs.csv` only: PDR, CH energy, lifetime, meeting
   success vs window width, p-sweep, PPO learning curves.
4. **Paper/report rewrite** addressing the instructor's comments:
   - a notation table, and only symbols the implementation uses;
   - sections connected by one system timeline;
   - claims limited to measured metrics; simulated vs analytic energy labelled;
   - every cited paper actually read.

Done when:
- [ ] One documented command sequence regenerates every number and figure in the paper from a
      clean clone.
