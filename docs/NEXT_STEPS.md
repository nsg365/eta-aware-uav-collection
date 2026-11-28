# Next steps: from course project to paper

Written 28 Nov 2026, after the course demo. Read this first when picking the project up again.

## 1. Where things stand

The course project is finished: simulator (Phase 1), baselines and wake rule (Phase 2), PPO
(Phase 3) and evaluation (Phase 4) are on `main`.

Main result: PPO matches the shortest tour (PDR 0.973 vs 0.972 on ten unseen networks, no paired
difference significant) and beats every heuristic (data greedy 0.907) and a tabular Q-learning
baseline adapted from Bouhamed et al. 2020 (0.718). One model trained on 100-sensor networks
transfers to hotspot networks with up to 2000 sensors and 20 clusters. In every case built to
favour leaving the tour (small buffers, event bursts), a trained agent either follows the tour or
does worse, because every detour breaks promises made to other clusters.

| What | Where |
|---|---|
| All Phase 3 results and reasoning | `docs/handoff/phase3.md` (§1–14) |
| RL result tables and plots | `results_phase3_ppo/README.md` |
| Phase 4 robustness results | `results_phase4/` |
| Paper draft | `paper/` (build: `cd paper && tectonic main.tex`) |
| Demo page | `demo/phase3/` (build: `python3 demo/phase3/build.py`, needs `results/`) |

## 2. Is it publishable?

Not yet as a regular conference paper. A reviewer would say:

1. The proposed RL method ties a simple baseline (the tour), so the paper must be pitched around
   the wake rule and the "tour is near-optimal under promises" finding, with PPO as evidence.
2. The only learning baseline (Q-learning) is weak: small state, about 53k updates while its
   exploration was set to decay over 100k.
3. The wake rule is not compared with always-on and duty-cycled CHs in the final setting (the
   simulator has both wake modes, so this is cheap).
4. Agents were trained with the older noise; the retrain on 9–11 m/s
   (`configs/phase3_ppo_sir.toml`, §12 of the handoff) did not finish.

Realistic target: **IEEE WF-IoT 2027, deadline 1 March 2027** (has a UAV / advanced air mobility
track). Confirm the date on the official site. ICUAS '27 (5 Feb 2027) is possible but less on
topic.

## 3. Sir's suggestion: change the reward

After the demo, sir suggested that RL does not beat the tour because the reward only counts data
delivered. His idea:

- count PDR only over the readings that should have reached the UAV but did not (leave out the
  readings lost to buffer overflow), and
- add a term that penalises overflow and pushes the UAV to change its path towards a CH that is
  close to overflowing, which the tour (a fixed path) never does.

### What we already know

1. **Overflow is already in the reward.** `R_D` counts readings delivered, so a reading lost to
   overflow is already a reading not collected. A separate overflow penalty mostly counts the same
   loss twice. Its possible benefit is faster credit assignment: the penalty arrives when the
   overflow happens, not at the next visit.
2. **"Go to the CH close to overflow" has been tested as a rule.** In the small-buffer test
   (handoff §6) the rule "detour to any cluster at least 70 % full" dropped to PDR 0.716 and 53 %
   on time, against the tour's 0.896 and 95 %. Data greedy is the same idea and loses everywhere.
   Each detour breaks promises made to other clusters. A reward that simply pays for visiting
   near-full CHs would teach PPO that losing behaviour.
3. **Most overflow cannot be fixed by any route.** In the 1000/2000-sensor Gaussian networks each
   CH serves 170–290 sensors and fills before any UAV can return (capacity, not routing). Under
   bursts the UAV only learns of a burst at its next visit to that cluster, and promises stop it
   going back early. An ideal "visit busy clusters twice per lap" schedule beats the tour by at
   most about 4 PDR points, and only when buffers are right at the edge.
4. **Removing overflow from PDR does not change who wins.** Tour and PPO would both be near 100 %
   and still tie; it changes the metric, not the result.

So the bottleneck is the information the UAV has and the promise constraint, not only the
reward. Sir's reward change should be tested together with one change that gives the UAV room to
react.

### Planned experiment

| Step | What | Why |
|---|---|---|
| 1 | Add an overflow penalty from the true overflow count (needs ns-3 to report overflow in the bridge totals, `ExternalPolicy::WriteTotals` in `routing-policy.h`, and `TOTALS` in `routing/env.py`). Add a "near overflow" signal as **potential-based** shaping on the estimated fill level, so it can guide learning without changing which policy is best. | Sir's idea, implemented so the agent cannot learn to chase buffers blindly |
| 2 | Train and evaluate on the two cases where a gain is possible: event bursts (`configs/phase3_ppo_bursts.toml`, `configs/phase3_bursts_eval.toml`) and small buffers (`configs/phase3_hotspot.toml`). | Where reacting can pay at all |
| 3 | Add one enabler: (a) CHs send a short "filling fast" beacon the UAV can hear from further away, or (b) let the agent choose shorter promises (A4P already has 0.5–1.5 × P on bursts). | Early news of a burst, or the freedom to act on it |
| 4 | Compare reward only, enabler only, and both, against the tour on 10 held-out networks with paired CIs. | Shows which part matters |

Possible outcomes: reward alone gives nothing (confirms the paper's claim, now with sir's
suggestion tested), or reward plus early news beats the tour (the result that makes the paper
publishable). Step 3(a) changes the simulator, so tell Prakruthi and Shreya before starting.

Cost: about half a day to implement steps 1 and 3; each training run is about 40 min on
100-sensor networks (`--warm-start --arch scoring`, 300k decisions).

## 4. Other open items

1. **Retrain on the reduced noise** (`configs/phase3_ppo_sir.toml`, handoff §12): A1–A4P on
   100-sensor networks (about 35–40 min each), A4M on the full mix (3–4 h). Then rerun the
   Gaussian, CH-sweep and burst evaluations with the new models.
2. **A stronger learning baseline**: retrain Q-learning for its full schedule, and add one deep-RL
   method from a published UAV data-collection paper.
3. **Wake-rule comparison** with always-on and duty-cycled CHs in the reduced-noise setting.
4. **Ablations A7–A9** (no backup CH, takeover on a missed meeting, no survey lap): switches exist
   (Thiaana, Phase 4); full runs still to do.
5. **Q-learning in `results_phase3_ppo/`**: its runs are in `results/qlearning_*` and on the demo
   page, but not yet in the exported tables and plots (`scripts/export_phase3_results.py`).
6. **Clean-up**: the `uav_range_m` default in `configs/gaussian_hotspot.toml` and
   `clustering/topology.py` is still 80 m; all our runs use 30 m.

## 5. How to resume

```bash
cd wsn-uav && git pull
export PATH=/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:$PATH   # this Mac
(cd ../ns3-workspace/ns-3.47 && ./ns3 build wsn-uav)
python3 -m pytest -q                      # 49 tests

# regenerate the results the demo page and paper read (git-ignored), about 1 h in total
python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
python3 -m analysis.aggregate results/phase3_eval/runs.csv
python3 -m experiments.run_experiment configs/phase3_gaussian_scaling.toml -j 8
for t in 05 10 15 20; do python3 -m experiments.run_experiment configs/phase3_ch_sweep_$t.toml -j 8; done
python3 -m experiments.run_experiment configs/phase3_bursts_eval.toml -j 8
for f in configs/qlearning/*.toml; do python3 -m experiments.run_experiment $f -j 8; done
python3 demo/phase3/build.py
```

Team rules that still apply: work on a branch and open a pull request, never push to `main`.
