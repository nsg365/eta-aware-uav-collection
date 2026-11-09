# Shared interfaces

These are the contracts between phases (see TEAM_PLAN.md). A later phase may extend them; a
breaking change must be agreed with the owners of the phases that use it. Version the metrics schema (`schema_version`) on any breaking change.

## 1. Configuration (keys owned by the module that reads them)

One TOML file per experiment (`configs/*.toml`):

| Table | Read by | Notes |
|---|---|---|
| `[experiment]` | `experiments/run_experiment.py` | `name`, `num_sensors` (list), `seeds` (list) |
| `[topology]` | `clustering/topology.py` (`TopologyParams`) | unknown keys are an error |
| `[simulation]` | ns-3 program, passed as `--key=value` | keys/units/defaults: `simulation/ns3/wsn-uav/config.h` |
| `[[variant]]` | runner | `name` + any `[simulation]` overrides; one run per variant per cell |

Seeds: `seed` sets both the topology RNG and the ns-3 run number. Random streams are fixed per
purpose (traffic per sensor, speed, loss, phase, Wi-Fi), so variants in the same cell share
traffic and UAV speed draws (common random numbers).

## 2. Topology files (producer: Phase 0/2, consumer: simulation)

Directory with:

- `nodes.csv` — `node_id,x,y,cluster_id,role`; ids 0..N−1 in order; role ∈ {primary, backup, member}
- `clusters.csv` — `cluster_id,meet_x,meet_y,primary_id,backup_id,size,tour_index`; ids 0..K−1
  in order; `backup_id = -1` if none; `tour_index` = position in the survey/TSP tour
- `depot.csv` — `depot_x,depot_y`
- `meta.json` — parameters and diagnostics (informational; not read by ns-3)

## 3. Simulation outputs (producer: simulation, Phase 1; consumers: Phases 2–4)

Per run, in `outDir`:

- `metrics.json` — schema v1, below
- `per_cluster.csv` — data/contact/window counters and residual energy fraction per cluster
- `per_node.csv` — `energy_used_J`, `wifi_J`, `residual_J`, `alive`, `death_time_s` per sensor
- `visits.csv` — one row per UAV visit: depart/arrive/contact/end times, leg distance, promised
  ETA (−1 if none), readings collected. **This is the ETA-lateness data source for Phases 2–3.**

### metrics.json v1

| Key | Meaning | Source |
|---|---|---|
| `data.generated / delivered` | readings generated / received at the UAV | counted |
| `data.pdr` | delivered / generated (includes end-of-horizon backlog, D17) | derived |
| `data.overflow, lost_154, lost_wifi, lost_ch_dead, in_buffer_at_end` | where undelivered readings went; they sum with `delivered` to `generated` | counted |
| `energy.wifi_total_J` | CH Wi-Fi radio energy | **ns-3 WifiRadioEnergyModel** |
| `energy.ieee802154_total_J, baseline_total_J` | 802.15.4 and sleep energy | **analytic ledger (D1)** |
| `energy.primary_ch_mean_J, non_primary_mean_J, sensor_mean_J` | per-role means | derived |
| `energy.jain_cluster_residual` | Jain index of per-cluster residual energy fraction | derived |
| `lifetime.first_node_death_s, lifetime_x_s` (+ `_censored`) | time to first death / to `dead_fraction_x` dead; censored = horizon reached | ledger |
| `uav.distance_m, flight_time_s, hover_time_s` | UAV motion | simulated mobility |
| `uav.flight_energy_J_est, hover_energy_J_est` | constant-power estimate, eq. (9) | **analytic** |
| `uav.visits, contacts, failed_contacts` | visits; visits where the CH answered (DATA or DONE); visits that timed out without an answer | counted |
| `wake.windows_scheduled/met/missed, meeting_success_rate` | scheduled-window outcomes (met / (met+missed)) | counted |
| `wake.planned_window_width_s, mean_window_listen_s, ch_wifi_awake_fraction` | 2w; mean time awake per closed window; CH non-sleep fraction | counted |
| `eta.mean_signed_error_s, mae_s, rmse_s, late_beyond_window_frac` | actual − promised arrival | counted |
| `run.wall_time_s` | simulation wall-clock time | measured |

Not yet measured (do not report): retries, CH failures/promotions, re-bootstraps, ML
training/inference cost, depot offload.

## 4. Aggregated results (producer: Phase 4)

`results/<experiment>/runs.csv`: one row per run, with flattened `metrics.json` keys plus
`variant`. `analysis/aggregate.py` writes `summary.csv` (mean and 95 % t-CI per
(num_sensors, variant)) and `summary.md`.

## 5. Routing policy (producers: Phases 2–3)

C++ `RoutingPolicy` in `simulation/ns3/wsn-uav/routing-policy.h`:
`uint32_t Next(const World&)` and `bool CommitsToOrder()`. Phase 3 adds an external policy whose
`Next()` calls the Python agent; the bridge is chosen in Phase 3.

## 6. UAV belief state (producer: Phase 2; consumer: Phase 3)

The UAV maintains an estimated belief state for every cluster. It uses information
from previous contacts rather than directly reading the cluster's true simulator buffer.

`UavApp::BuildBeliefVector()` in `simulation/ns3/wsn-uav/uav-app.cc`
returns the belief state as a flat `std::vector<double>`.

Each cluster contributes seven entries in this order:

| Index | Feature | Meaning | Unit |
|---|---|---|---|
| 0 | `estimatedBuffer` | Estimated readings currently waiting at the cluster | readings |
| 1 | `estimatedGenerationRate` | EWMA estimate of the reading generation rate | readings/second |
| 2 | `residualEnergy` | Residual energy recorded at the last contact | joules |
| 3 | `timeSinceContact` | Time elapsed since the last contact | seconds |
| 4 | `timeUntilPromise` | Time remaining until the promised meeting; -1 if no promise exists | seconds |
| 5 | `missedMeetings` | Number of missed meetings | count |
| 6 | `neverContacted` | Whether the UAV has never contacted the cluster | binary (1 = true, 0 = false) |

### Flattening and ordering

For K clusters, the vector contains exactly 7 × K values.
Clusters are ordered by cluster ID. Cluster i occupies indices `7*i` through `7*i + 6`.
### Belief estimation

- Estimated buffer = estimated generation rate × elapsed time since the last successful contact.
- Generation rate is updated using an exponential weighted moving average (EWMA)
  with smoothing factor alpha = 0.3.
- Time since contact is zero for a cluster that has never been contacted.
- Time until promise is -1 when no promise has been recorded.
- The never-contacted flag is represented as 1.0 or 0.0.

The function returns raw, unnormalised values. For Phase 3 PPO observations,
use the following normalisation scales:

| Feature | Normalisation |
|---|---|
| Estimated buffer | Clamp `value / bufferCapacity` to [0, 1]. |
| Estimated generation rate | Clamp `value / (clusterSensorCount * readingRate)` to [0, 1]. |
| Residual energy | Clamp `value / (initialEnergy * clusterSensorCount)` to [0, 1]. |
| Time since contact | Divide by the nominal UAV tour period. |
| Time until promise | Divide by the nominal UAV tour period; preserve -1 as the no-promise sentinel. |
| Missed meetings | Clamp `log(1 + value) / log(11)` to [0, 1]. |
| Never contacted | Keep as 0 or 1. |

The reference value of 10 missed meetings is a design choice. The raw
BuildBeliefVector() output is not normalised; Phase 3 should apply these
transformations when constructing the PPO observation.

The flat vector is converted into `ClusterBelief` entries and passed to routing
policies through `RoutingPolicy::Next()`.
