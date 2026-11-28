# WSN–UAV data collection with promise-based wake-up and PPO (ns-3.47)

Course project, *Machine Learning Applications in Wireless Networks*, IIT Dharwad.
Team: Shreya S Bhat (Phase 1), Prakruthi K S (Phase 2), Nihar Sagar G (Phase 3),
Balasani Thiaana (Phase 4).

A UAV collects data from the cluster heads (CHs) of a sensor network that has no base station.
At every visit the UAV promises the CH when it will be back, and the CH sleeps until a listening
window around that time, widened by the UAV's measured lateness (promise-then-honour). Routing
policies (shortest tour, heuristics, PPO, tabular Q-learning) only decide the order of visits.
Everything runs in ns-3: 802.11g CH–UAV links, radio energy, backup CHs, retries, delays and
failures.

**Status (28 Nov 2026): the course project is complete.** All four phases are merged. Next steps
towards a paper, including the instructor's reward suggestion: [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).

## Main results

Ten unseen 100-sensor networks, 10 % of UAV legs delayed by 10–30 s, random CH failures
(mean over networks; full tables with 95 % CIs in [docs/handoff/phase3.md](docs/handoff/phase3.md)):

| Policy | PDR | Meetings on time | CH energy (J) |
|---|---|---|---|
| Shortest tour, adaptive window | 0.972 | 91 % | 95 |
| **PPO A4 (ER-PPO)** | **0.973** | **89 %** | **114** |
| Data greedy | 0.907 | 25 % | 238 |
| Tabular Q-learning (Bouhamed et al. 2020, adapted) | 0.718 | 20 % | 245 |
| Nearest feasible | 0.598 | 87 % | 122 |

- PPO matches the shortest tour (no paired difference significant) and beats every heuristic and
  Q-learning.
- The same PPO model, trained only on 100-sensor networks, stays within 0.2–0.4 pp of the tour on
  hotspot networks with up to 2000 sensors and 20 clusters (UAV speed 9–11 m/s), where the
  heuristics lose up to 42 pp ([results_phase3_ppo/README.md](results_phase3_ppo/README.md)).
- With small buffers and with event bursts, a trained agent either follows the tour exactly or
  does worse: under promise-based wake-up every detour breaks promises made to other clusters, so
  the shortest tour is already close to the best order.
- The adaptive wake window gives the clearest gain (tour meetings on time 85 % → 91 %).
- Robustness to UAV delays, CH failures, clock offsets and window width:
  [results_phase4/](results_phase4/).

## Documentation

| Doc | Content |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | environment, build, test (Windows: WSL2 + Ubuntu 24.04) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | data flow, what is simulated vs abstracted |
| [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) | every deviation from the proposal, instructor feedback |
| [docs/INTERFACES.md](docs/INTERFACES.md) | config, topology files, metrics schema |
| [docs/TEAM_PLAN.md](docs/TEAM_PLAN.md) | the four phases and their owners |
| [docs/handoff/phase1.md](docs/handoff/phase1.md) | simulator realism: energy, 30 m range, delays, drift, failover, retries |
| [docs/handoff/phase2.md](docs/handoff/phase2.md) | UAV belief, routing baselines, Gaussian hotspots, ETA lateness, adaptive window |
| [docs/handoff/phase3.md](docs/handoff/phase3.md) | PPO: bridge, MDP, training, all results (§1–14) |
| [docs/MDP.md](docs/MDP.md) | observation, action, reward, discount |
| [docs/Q_LEARNING.md](docs/Q_LEARNING.md) | tabular Q-learning baseline |
| [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) | open items and the plan towards a paper |
| [paper/README.md](paper/README.md) | paper draft, build, where each number comes from |

## Quick start

Setup as in [docs/SETUP.md](docs/SETUP.md), then:

```bash
pip install -r requirements.txt
scripts/link_ns3.sh && (cd ../ns3-workspace/ns-3.47 && ./ns3 build wsn-uav wsn-uav-range)
python3 -m pytest -q                                                 # 49 tests

# one mission
python3 -m clustering.topology --config configs/default.toml --out results/topo
../ns3-workspace/ns-3.47/build/scratch/wsn-uav/ns3.47-wsn-uav-default \
    --topologyDir=results/topo --outDir=results/run --wakeMode=scheduled

# main evaluation: every policy and PPO variant on 10 unseen networks (about 1 min)
python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
python3 -m analysis.aggregate results/phase3_eval/runs.csv

# PPO and the tour side by side on one network, live (about 10 s)
python3 -m routing.redteam models/phase3_ppo/A4_ppo-scoring_ws.zip tour agreement --seeds 3

# train a PPO variant (about 20 min)
python3 -m routing.train configs/phase3_ppo.toml --variant A4 --arch scoring --warm-start --timesteps 300000

# demo page (needs the results of the configs listed in demo/phase3/build.py)
python3 demo/phase3/build.py && python3 -m http.server 8000 --directory demo/phase3
```

## Layout

```
clustering/            placement (uniform or Gaussian hotspots), DBSCAN, feasibility split, CH election, survey tour
simulation/ns3/        ns-3 program (symlinked into <ns-3>/scratch/wsn-uav): links, energy, wake rule,
                       failover, retries, delays, clock drift, speed jitter, event bursts
experiments/           grid runner (sizes x seeds x variants, common random numbers)
analysis/              mean ± 95 % t-CI aggregation, Phase 4 paired statistics and plots
routing/               ns-3 bridge env, PPO / DQN training, Q-learning, evaluation, red-team checks
models/                trained policies, each with its settings (.json) and training curve
configs/               TOML configs (phase3_*: RL experiments; qlearning/: Q-learning on every deployment)
scripts/               CH-count sweep, plots, results export, setup helpers
demo/phase3/           demo page: project overview, six-policy mission replay, results (build.py)
paper/                 paper draft (main.tex, refs.bib, figures, make_figures.py)
results_phase3_ppo/    RL results: runs, tables (README.md) and plots
results_phase4/        Phase 4 evaluation: robustness sweeps, lifetime, learning curves
results_speed_jitter/  Phase 2 CH-count sweep (baselines, UAV speed 9–11 m/s)
tests/                 pytest: clustering, data conservation, energy, determinism, RL env, networks
results/               raw runs (git-ignored except results/sample/); rebuilt from the configs
```

## Phase 0: why scheduled wake-up

Before any routing work, the three wake modes on the fixed tour (2 h, E0 = 500 J, no delays,
5 seeds; `configs/example_wake_modes.toml`):

| N = 100 | PDR | primary-CH energy (J) | CH Wi-Fi awake |
|---|---|---|---|
| always on | 0.263 | 500 (all CHs die) | 0.231 |
| duty cycle (10 %) | 0.976 | 223 | 0.099 |
| scheduled, fixed window 20 s | 0.977 | 15.1 | 0.0026 |

Scheduled windows cut CH Wi-Fi energy about 15× against duty cycling at the same PDR; an always-on
CH runs out of energy in about 28 minutes.

## Working rules

- Work on a branch and open a pull request; do not push to `main`.
- Before changing anything, make sure `python3 -m pytest` passes.
- When a result changes, update the phase handoff first, then the paper and the demo page.
