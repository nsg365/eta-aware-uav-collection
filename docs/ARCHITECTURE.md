# Architecture

## Data flow

```
configs/*.toml
   │  [topology]                         [simulation] + [[variant]]
   ▼                                          │
clustering/topology.py  (Phase 0, offline)    │
   DBSCAN → noise attach → feasibility split (eq. 2) → election (eq. 3*) → NN+2-opt tour
   │  nodes.csv, clusters.csv, depot.csv      │
   ▼                                          ▼
simulation/ns3/wsn-uav  (ns-3.47 program, symlinked into ns-3 scratch/)
   World         sensors, clusters, buffers, energy ledger, metrics output
   GenerateReading (Poisson per sensor) → 802.15.4 hop [analytic] → CH buffer (B_max)
   ClusterHeadApp  Wi-Fi sleep/listen: always_on | duty_cycle | scheduled (DISCOVERY fallback)
   UavApp          WaypointMobility flight → POLL broadcast → DATA/DONE upload → PLAN (promise)
   RoutingPolicy   tour (now); heuristics (Phase 2); external PPO (Phase 3)
   CheckEnergy     combined Wi-Fi (ns-3) + 802.15.4 (ledger) budget → death, PHY OFF
   │  metrics.json, per_cluster.csv, per_node.csv, visits.csv
   ▼
experiments/run_experiment.py → runs.csv → analysis/aggregate.py → summary.csv / summary.md
```

`*` eq. (3) with the normalised distance term (D3).

## Simulated vs abstracted

| Component | How it is modelled |
|---|---|
| CH↔UAV link | ns-3 802.11g ad hoc, YansWifiPhy, log-distance path loss, ConstantRate 6 Mb/s, UDP |
| CH Wi-Fi energy | ns-3 `WifiRadioEnergyModel`, with real `SetSleepMode`/`ResumeFromSleep` |
| UAV motion | ns-3 `WaypointMobilityModel`, straight legs at altitude H, per-leg speed ~ N(v, σ_v) |
| Member→CH 802.15.4 | analytic airtime × power, Bernoulli loss (D1) |
| UAV energy | analytic P_flight·t + P_hover·t (eq. 9), reported as an estimate |
| Battery / death | E0 budget on combined energy, checked every second (D2) |
| Clock drift, CH failures, retries, re-election | not yet modelled (Phase 1) |

## CH Wi-Fi state machine

```
 always_on:  AWAKE ───────────────────────────────────────────────▶ (never sleeps)

 duty_cycle / DISCOVERY:  sleep (T_b − t_l) ⇄ listen t_l   [random initial phase]
        │ POLL heard
        ▼
     UPLOAD: DATA frames (paced) → DONE ── no PLAN within planTimeout ──▶ DISCOVERY
        │ PLAN(t*, w)   [scheduled mode only]
        ▼
     SLEEP until t* − w ─▶ LISTEN until t* + w ── POLL ──▶ UPLOAD   (window met)
                                    └── window closes ─────▶ DISCOVERY (missed meeting)
```

The UAV holds at a meeting point until a promised window opens (D8), and gives up after
`contactWait` beyond that. `maxHover` caps every visit.

## Assessment against the proposal

The proposal's *core loop* (clusters → CH buffering → UAV visits → wake windows → energy and
delivery metrics) is implementable, and now runs. About 2 s of wall time simulate 2 h with
100 sensors, so PPO training in ns-3 is computationally feasible: roughly 500 decisions per
episode at about 2–3 s per episode, before bridge overhead.


