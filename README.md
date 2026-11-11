# WSN–UAV data muling (ns-3.47)

Course project, *Machine Learning Applications in Wireless Networks*, IIT Dharwad.
Proposal: *Energy-Aware WSN–UAV Data Muling with ETA-Risk-Aware PPO and Adaptive Wake
Scheduling* (`../Energy aware WSN-UAV....pdf`).

**Status: the core simulation (Phase 0) works.** There is no ML yet: the ETA-lateness model is
Phase 2 and PPO is Phase 3. See [docs/TEAM_PLAN.md](docs/TEAM_PLAN.md).

| Doc | Content |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | environment, build, test |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | data flow, what is simulated vs abstracted, risks |
| [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) | every deviation from the proposal + instructor feedback |
| [docs/INTERFACES.md](docs/INTERFACES.md) | config, topology files, metrics schema |
| [docs/TEAM_PLAN.md](docs/TEAM_PLAN.md) | four sequential phases, owners, hand-off checklists |

## Teammates start here

1. Set up your machine. **Windows users: follow [docs/SETUP.md](docs/SETUP.md) (WSL2 + Ubuntu
   24.04)** to install the tools, build ns-3.47, and run the tests.
2. Read, in this order: this README → [docs/TEAM_PLAN.md](docs/TEAM_PLAN.md) (find your
   phase) → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) →
   [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) → the code files your phase owns.
3. Before changing anything, make sure `python3 -m pytest` passes on your machine.

## Quick start (after setup)

```bash
scripts/link_ns3.sh && (cd ../ns3-workspace/ns-3.47 && ./ns3 build wsn-uav wsn-uav-range)
python3 -m pytest                                                    # 26 tests

# one run
python3 -m clustering.topology --config configs/default.toml --out results/topo
../ns3-workspace/ns-3.47/build/scratch/wsn-uav/ns3.47-wsn-uav-default \
    --topologyDir=results/topo --outDir=results/run --wakeMode=scheduled

# example experiment: 3 wake modes x N in {60,100} x 5 seeds (30 runs, ~20 s on 8 cores)
python3 -m experiments.run_experiment configs/example_wake_modes.toml
python3 -m analysis.aggregate results/wake_modes/runs.csv
```

## Layout

```
clustering/       Phase 0: placement, DBSCAN, feasibility split, CH election, survey tour
simulation/ns3/   ns-3 program (symlinked into <ns-3>/scratch/wsn-uav)
experiments/      grid runner (sizes x seeds x variants, common random numbers)
analysis/         mean ± 95% t-CI aggregation
routing/          Phase 3: ns-3 bridge env, PPO training and evaluation (docs/MDP.md)
models/           Phase 3: trained policies, each with its settings (.json) and training curve
demo/phase3/      Phase 3 demo page: mission replay and results (build.py)
configs/          TOML configs
tests/            pytest: clustering properties, data conservation, energy, determinism
results/sample/   committed sample outputs; everything else in results/ is git-ignored
```

## Phase 0 results (sample; placeholder energy parameters, D11)

Output of `configs/example_wake_modes.toml`: 2 h horizon, E0 = 500 J, fixed survey tour,
mean ± 95 % CI over 5 seeds. Lifetime "cens." means no sensor died within the horizon.

| N | variant | PDR | primary-CH energy (J) | CH Wi-Fi awake | meeting success | UAV hover (s) | first death (s) |
|---|---|---|---|---|---|---|---|
| 100 | always_on | 0.263 ± 0.004 | 500 (all CHs die) | 0.231 | – | 3330 ± 150 | 1660 |
| 100 | duty_cycle (10 %) | 0.976 ± 0.004 | 223 ± 0.3 | 0.099 | – | 1830 ± 220 | cens. |
| 100 | scheduled, fixed w = 20 s | 0.977 ± 0.003 | 15.1 ± 0.5 | 0.0026 | 1.00 | 2130 ± 110 | cens. |

How to read this:
- An always-on CH empties its 500 J in ≈ 1660 s at 0.3 W idle. Its cluster's later data is lost.
- Scheduled windows cut CH Wi-Fi energy about 15× versus duty cycling at the same PDR. The UAV
  pays with more hover time, because it holds to keep the timetable (D8).
- PDR < 1 for duty/scheduled is mostly data still buffered at the horizon (D17).
- With a committed timetable plus slack and **no exogenous delays**, there were zero missed
  meetings. The baseline is not yet stressed. UAV delay events and clock drift (Phase 1)
  are needed before ETA-risk modelling can show a benefit.
- UAV flight/hover energies in `metrics.json` are analytic estimates (eq. 9), not simulated.

## Session 1 log

What worked:
- Phase 0 clustering
- the ns-3 program (802.11g CH↔UAV link, WifiRadioEnergyModel, real PHY sleep, waypoint UAV)
- three wake modes
- the runner and aggregation
- 22 tests

Problems found and fixed during validation:
1. ns-3 scratch subdirectory targets are named after the file containing `main()`, so the entry
   file is `wsn-uav.cc`.
2. `WifiRadioEnergyModel` stopped accounting at about 700 s with energy left. The workaround
   and regression test are recorded in D2.
3. Too large an ns-3 source capacity overflowed `ns3::Time`. A guard now checks this.
4. "Promise = now + estimated lap" ETAs were unstable (MAE about 285 s). Replaced by a
   committed timetable (D7).
5. An early UAV gave up before the promised window opened. It now holds (D8), and holds in every
   lap so lap 0 cannot leave it a lap ahead.

Not done: no ML, heuristic baselines (B), failures/retries (E), clock drift, or lr-wpan
simulation (D1). Nothing is committed to git yet (repository initialised only).
