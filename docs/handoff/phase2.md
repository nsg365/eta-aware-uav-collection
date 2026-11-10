# Phase 2 Handoff — UAV Belief State, Routing Baselines, and ETA-Aware Collection

**Owner:** Prakruthi KS
**Phase:** Phase 2
**Implementation period:** 4–12 November 2026
**Overall project deadline:** 30 November 2026
**Repository:** `eta-aware-uav-collection`

---

## 1. Overview

Phase 2 extends the existing UAV-assisted wireless sensor network simulation with a UAV-side belief state, multiple routing policies, Gaussian-hotspot deployment support, and an ETA-based adaptive wake-window mechanism.

The main objectives are:

1. Maintain an estimated belief state for every cluster at the UAV.
2. Apply a common meeting-promise rule across routing policies.
3. Implement and compare multiple routing baselines.
4. Support Gaussian-hotspot sensor deployment.
5. Estimate UAV arrival-time lateness and adapt cluster-head wake windows.
6. Validate the implementation through automated tests and simulation experiments.

The work is intended to provide the routing and state representation needed for Phase 3, where the belief vector can be used as part of the PPO observation.

## 2. Implementation Summary

| Component | Implementation | Status |
|---|---|---|
| UAV belief state | Seven values per cluster, flattened into a vector | Implemented |
| EWMA generation-rate estimation | Alpha = 0.3 | Implemented |
| Common meeting-promise rule | Promise updated after successful contact | Implemented |
| Nearest-feasible routing | Excludes current cluster and avoids A-B-A | Implemented |
| Data-greedy routing | Uses estimated cluster data | Implemented |
| Energy-data-score routing | Combines estimated data and residual energy | Implemented |
| Fixed-tour routing | Existing repeating tour retained | Implemented |
| Gaussian-hotspot deployment | Deterministic Gaussian cluster generation | Implemented |
| ETA lateness estimation | Lateness recorded using promised and actual arrival times | Implemented |
| Adaptive wake windows | Empirical lateness quantile used for late-window margin | Implemented |
| Routing integration tests | Actual ns-3 simulations used | Passed |
| Full automated test suite | 31 tests | Passed |
| ETA p-sweep analysis | p80, p90, p95, p99 results collected | Preliminary results available |
| ETA listening-energy comparison and plot | Requires final isolated listening-energy analysis and plot | Pending |
| Final handoff documentation | This document | In progress |

---

## 3. UAV Belief State

### 3.1 Purpose

The UAV needs an estimate of each cluster's state because it cannot continuously observe the cluster while travelling.

The belief state stores information from previous contacts and uses it to estimate the current condition of each cluster.

This state is maintained at the UAV and is intended to become the observation representation for the Phase 3 PPO agent.

### 3.2 Belief-state representation

The implementation is provided by:

`UavApp::BuildBeliefVector()`

The function returns a flat `std::vector<double>`.

Each cluster contributes seven values:

| Index within cluster | Field | Unit | Description |
|---:|---|---|---|
| 0 | Estimated buffer | Readings | Estimated amount of data currently waiting at the cluster |
| 1 | Estimated generation rate | Readings/second | Estimated rate at which new readings are generated |
| 2 | Residual energy | Joules | Most recently observed cluster energy |
| 3 | Time since contact | Seconds | Time elapsed since the UAV last contacted the cluster |
| 4 | Time until promise | Seconds | Time remaining until the next promised meeting; `-1` if no promise exists |
| 5 | Missed meetings | Count | Number of missed meetings recorded for the cluster |
| 6 | Never contacted | Binary | `1` if the UAV has never successfully contacted the cluster, otherwise `0` |

### 3.3 Flattening order

The vector is constructed in cluster-ID order.

For \(K\) clusters, the vector contains:

\[
7K
\]

values.

For example, the first seven values belong to cluster 0, the next seven to cluster 1, and so on.

### 3.4 Estimation of generation rate

The estimated generation rate is updated using an exponentially weighted moving average (EWMA).

The smoothing factor is:

\[
\alpha = 0.3
\]

The update rule is:

\[
\hat{\lambda}_{new}
=
\alpha \lambda_{observed}
+
(1-\alpha)\hat{\lambda}_{old}
\]

where:

- \(\lambda_{observed}\) is the generation rate calculated from the latest contact.
- \(\hat{\lambda}_{old}\) is the previous estimated generation rate.
- \(\hat{\lambda}_{new}\) is the updated estimate.

The observed generation rate is calculated from the buffer observed at contact and the elapsed time since the previous contact.

### 3.5 Estimated buffer

The estimated buffer is calculated using the estimated generation rate and elapsed time since the last contact:

\[
\widehat{B}(t)
=
\hat{\lambda}\times(t-t_{last})
\]

This assumes that the buffer was drained during a successful collection contact.

### 3.6 Belief updates

The UAV updates cluster beliefs when it receives a successful contact completion (`DONE`).

The update includes:

- Last contact time.
- Observed buffer information.
- Estimated generation rate.
- Residual energy.
- Never-contacted status.
- Next meeting promise.

Failed contacts increment the missed-meeting count.

### 3.7 Normalisation

The belief vector currently contains raw values.

Normalisation is left to the Phase 3 observation-processing stage. The relevant normalisation scales and field definitions are documented in `docs/INTERFACES.md`.

---

## 4. Common Meeting-Promise Rule

All routing policies use the same meeting-promise rule.

After a successful contact with cluster \(k\), the next meeting promise is:

\[
T_k = t_{contact} + P
\]

where:

- \(t_{contact}\) is the current successful contact time.
- \(P\) is the nominal tour period.

The nominal period is calculated using:

- Inter-cluster tour travel distances.
- The final-to-first tour closing leg.
- Cluster hover budgets.
- UAV speed and the configured plan-speed factor.

The depot-to-first-cluster leg is excluded because the promise period begins at a successful cluster contact.

The promise is updated after every successful contact, independently of the selected routing policy.

This ensures that the promise mechanism remains consistent when comparing routing strategies.

---

## 5. Routing Policies

Four routing policies are available.

The routing identifiers used in the experiment configurations are:

| Policy | Configuration identifier |
|---|---|
| Fixed tour | `tour` |
| Nearest-feasible | `nearest-feasible` |
| Data-greedy | `data-greedy` |
| Energy-data-score | `energy-data-score` |

### 5.1 Fixed-tour policy

The existing fixed tour is retained.

The UAV follows the predetermined cluster order and repeats the tour.

This serves as the reference baseline.

### 5.2 Nearest-feasible policy

The nearest-feasible policy selects a feasible cluster based on distance.

Its selection excludes:

- The currently visited cluster.
- An immediate return that creates an A-B-A pattern, when an alternative candidate exists.

The policy does not guarantee that every cluster will be visited.

### 5.3 Data-greedy policy

The data-greedy policy selects clusters using the UAV's estimated data state.

It prioritises never-contacted clusters during exploration. After that, it selects the eligible cluster with the largest estimated buffer.

The policy uses the belief-state estimate rather than directly reading the true cluster buffer.

### 5.4 Energy-data-score policy

The energy-data policy combines estimated data and residual energy.

The implemented score is:

\[
Score(k)
=
0.5\frac{\widehat{B}_k}{B_{max}}
+
0.5\frac{E_k}{E_{max}}
\]

where:

- \(\widehat{B}_k\) is the estimated buffer.
- \(B_{max}\) is the data normalisation scale.
- \(E_k\) is the estimated residual energy.
- \(E_{max}\) is the energy normalisation scale.

Never-contacted clusters are prioritised during exploration.

### 5.5 Ping-pong prevention

The routing implementation includes logic to avoid immediate repeated visits and A-B-A movement patterns when alternative feasible candidates are available.

The A-B-A pattern means:

\[
A \rightarrow B \rightarrow A
\]

The policies are tested against generated visit sequences to check for these patterns.

### 5.6 Coverage considerations

Cluster coverage is calculated as the percentage of clusters contacted at least once.

Coverage does not imply balanced service or equal data collection across clusters.

The multi-seed results show that nearest-feasible has a significant coverage limitation. The data-greedy, energy-data-score, and fixed-tour policies achieved full observed coverage in the tested multi-seed experiment.

---

## 6. Gaussian-Hotspot Deployment

### 6.1 Purpose

The Gaussian-hotspot deployment mode supports sensor distributions that are spatially concentrated around several hotspot centres rather than uniformly distributed across the deployment area.

### 6.2 Implementation

The implementation is in:

`clustering/topology.py`

The topology parameters include:

```python
deployment_mode: str = "uniform"
hotspot_count: int = 4
hotspot_std_m: float = 25.0
```

Two deployment modes are supported:

- `uniform`
- `gaussian_hotspot`

For Gaussian-hotspot deployment:

1. Hotspot centres are sampled.
2. Sensor positions are generated around the selected centres using Gaussian distributions.
3. Generated positions are clipped to remain within the deployment area.
4. The random seed controls reproducibility.

Validation checks ensure that the hotspot count is at least one and the standard deviation is positive.

### 6.3 Configuration

Example configuration:

`configs/gaussian_hotspot.toml`

The topology metadata records the deployment parameters using the topology configuration.

### 6.4 Validation

The following tests were added:

- `test_gaussian_hotspot_positions_are_deterministic`
- `test_gaussian_hotspot_positions_within_area`
- `test_gaussian_hotspot_topology_builds`

The clustering test suite passed, including these Gaussian-hotspot tests.

A generated topology example reported:

| Property | Value |
|---|---:|
| Number of clusters | 4 |
| DBSCAN epsilon | 64.0 m |
| DBSCAN noise points | 0 |
| Feasibility splits | 2 |
| Tour length | 1471.13 m |
| Clusters without backup | 0 |

These values correspond to the tested example configuration, not a general guarantee for all deployments.

---

## 7. ETA Lateness Estimation and Adaptive Wake Windows

### 7.1 Purpose

The UAV may arrive earlier or later than the promised meeting time.

A cluster head should therefore not need to remain awake continuously while waiting for the UAV.

The adaptive wake-window mechanism uses observed arrival-time lateness to adjust the late side of the cluster-head listening window.

### 7.2 Lateness definition

For each visit:

\[
e = t_{actual} - t_{promised}
\]

where:

- \(t_{actual}\) is the actual UAV arrival time.
- \(t_{promised}\) is the promised meeting time.
- \(e\) is the lateness.

Interpretation:

- \(e < 0\): UAV arrived early.
- \(e = 0\): UAV arrived exactly on time.
- \(e > 0\): UAV arrived late.

The lateness information is recorded in `visits.csv`.

### 7.3 Stops-since-promise estimation

The implementation tracks the number of UAV arrivals since the promise was established.

The lateness samples are grouped by this count to estimate the arrival-time error distribution.

The implementation maintains lateness samples in:

`m_latenessByStops`

### 7.4 Empirical quantile

The adaptive late margin is calculated using an empirical lateness quantile.

The quantile parameter is configurable:

\[
p \in \{0.80, 0.90, 0.95, 0.99\}
\]

The empirical quantile is used after the configured minimum sample count is reached.

Before sufficient samples are available, the configured fallback late margin is used.

### 7.5 Adaptive wake window

The cluster-head wake window is asymmetric:

\[
Window =
[T_k-w_{drift}-w_{margin},\;
T_k+w_{drift}+q_p]
\]

where:

- \(T_k\) is the promised meeting time.
- \(w_{drift}\) is the clock-drift allowance.
- \(w_{margin}\) is the configured early-side margin.
- \(q_p\) is the empirical lateness quantile.

The UAV's planned early and late widths are passed to the cluster head.

The cluster head adjusts the planned arrival time using its clock offset and schedules its wake window accordingly.

### 7.6 Preliminary lateness observations

For the tested ETA-delay configuration:

| Metric | Value |
|---|---:|
| Valid promised visits | 463 |
| Early arrivals | 47 |
| On-time arrivals | 0 |
| Late arrivals | 416 |
| Mean signed ETA error | +34.70 s |
| Standard deviation | 30.56 s |
| Minimum error | -29.14 s |
| 25th percentile | 10.87 s |
| Median | 30.12 s |
| 75th percentile | 55.35 s |
| Maximum error | 137.53 s |

These observations show that the tested configuration has a tendency toward late arrivals.

---
## 8. ETA Quantile Sweep

### 8.1 Experiment configuration

The multi-seed quantile sweep compares:

\[
p \in \{0.80,0.90,0.95,0.99\}
\]

Configuration: `configs/eta_multiseed.toml`

The experiment uses:
- 100 sensors.
- Ten random seeds (1–10).
- Four ETA quantile variants: p80, p90, p95, and p99.
- Scheduled wake mode.
- Minimum ETA sample count of 5.
- Adaptive late-margin fallback of 20 seconds.
- UAV delay probability of 0.5.
- Minimum UAV delay of 5 seconds.
- Maximum UAV delay of 15 seconds.

This produces 40 runs in total (10 seeds × 4 quantiles).

### 8.2 Results

The table reports the mean and standard deviation across ten seeds.

| Metric | p80 | p90 | p95 | p99 |
|---|---:|---:|---:|---:|
| Runs | 10 | 10 | 10 | 10 |
| Meeting success (%) | 79.144 ± 7.497 | 90.985 ± 1.562 | 92.197 ± 1.059 | 92.197 ± 1.059 |
| Scheduled-window listening energy (J) | 8073.594 ± 1174.935 | 7624.195 ± 1077.210 | 7522.081 ± 1084.122 | 7526.501 ± 1081.461 |

Summary CSV:

`results_eta_energy/eta_multiseed/quantile_summary.csv`

Plot:

`docs/figures/eta_quantile_energy_vs_meeting_success.png`

The plot compares mean meeting success against mean scheduled-window listening energy. Error bars represent one standard deviation across seeds on each axis.

### 8.3 Interpretation

Increasing the lateness quantile from p80 to p95 improves observed meeting success and reduces mean scheduled-window listening energy.

- p80 has the lowest meeting success (79.144%) and highest mean listening energy (8073.594 J).
- p90 improves meeting success to 90.985% and reduces mean energy to 7624.195 J.
- p95 achieves the highest observed meeting success (92.197%) and the lowest mean energy (7522.081 J).
- p99 has the same observed meeting success as p95, with a very similar mean energy (7526.501 J).

For these tested seeds, p95 is a reasonable choice among the four variants. Increasing the quantile beyond p95 does not produce an observable meeting-success improvement.

Energy standard deviations are substantial, so differences in mean energy should not be interpreted as proof of statistical significance.

### 8.4 Limitations

1. The experiment covers one network size (100 sensors) and ten random seeds.
2. There is substantial run-to-run variation in scheduled-window listening energy.
3. Identical p95 and p99 mean meeting success does not establish equivalence under other configurations.
4. Scheduled-window listening energy must be distinguished from total primary cluster-head energy and overall Wi-Fi awake time.
5. These results do not establish that p95 is optimal for every topology, network size, or delay distribution.

## 9. Routing Baseline Experiment

### 9.1 Configuration

The multi-seed routing experiment uses:

`configs/phase2_routing_multiseed.toml`

The experiment compares:

- Fixed tour.
- Nearest-feasible.
- Data-greedy.
- Energy-data-score.

It uses 10 seeds, with 100 sensors and a simulation duration of 7200 seconds.

### 9.2 Reproduction command

```bash
python3 -m experiments.run_experiment \
    configs/phase2_routing_multiseed.toml \
    -j 1 \
    --results results
```

### 9.3 Output files

The main results are:

```text
results/phase2_routing_multiseed/runs.csv
results/phase2_routing_multiseed/baseline_summary.csv
```

### 9.4 Multi-seed results

Values below are reported as mean ± standard deviation across the 10 runs.

| Metric | Tour | Nearest-feasible | Data-greedy | Energy-data-score |
|---|---:|---:|---:|---:|
| UAV visits | 478 ± 20 | 91 ± 53 | 85 ± 3 | 86 ± 3 |
| UAV contacts | 478 ± 20 | 88 ± 46 | 85 ± 3 | 86 ± 3 |
| Data delivered | 69,907 ± 252 | 8,998 ± 9,909 | 11,404 ± 2,872 | 8,770 ± 3,059 |
| PDR (%) | 97.01 ± 0.30 | 12.94 ± 15.14 | 15.82 ± 3.97 | 12.17 ± 4.23 |
| Meeting success (%) | 92.20 ± 1.06 | 91.24 ± 5.90 | 66.89 ± 5.29 | 65.24 ± 4.80 |
| CH awake (%) | 12.86 ± 0.93 | 10.55 ± 5.43 | 9.01 ± 0.09 | 9.02 ± 0.09 |
| Missed windows (%) | 7.80 ± 1.06 | 8.76 ± 5.90 | 33.11 ± 5.29 | 34.76 ± 4.80 |
| ETA MAE (s) | 47.52 ± 10.18 | 138.81 ± 75.67 | 110.88 ± 11.26 | 125.35 ± 13.69 |
| UAV distance (m) | 44,589 ± 1,298 | 6,919 ± 3,948 | 17,751 ± 2,913 | 10,519 ± 2,357 |
| Buffer at end | 2,156 ± 222 | 38,380 ± 7,164 | 40,248 ± 4,889 | 41,076 ± 4,358 |
| Primary CH energy (J) | 286.68 ± 20.08 | 213.52 ± 43.22 | 203.75 ± 1.92 | 203.94 ± 1.85 |

### 9.5 Cluster coverage

Cluster coverage was analysed independently using:

`scripts/analyze_cluster_coverage.py`

The script generates:

```text
results/phase2_routing_multiseed/cluster_coverage_by_run.csv
results/phase2_routing_multiseed/cluster_coverage_summary.csv
```

Coverage results across the 10 seeds:

| Policy | Mean coverage (%) | Standard deviation (%) |
|---|---:|---:|
| Tour | 100.00 | 0.00 |
| Nearest-feasible | 33.22 | 16.44 |
| Data-greedy | 100.00 | 0.00 |
| Energy-data-score | 100.00 | 0.00 |

Coverage was cross-checked against the per-cluster contact counters for seeds 1 and 8.

The results confirm that nearest-feasible does not guarantee full cluster coverage in the tested experiment.

### 9.6 Baseline interpretation

**Fixed tour**

- Delivers the most data.
- Achieves the highest PDR.
- Has the lowest remaining buffer.
- Achieves strong meeting success and ETA accuracy.
- Requires substantially more UAV travel and visits.
- Has higher CH awake fraction and primary CH energy than the two belief-based heuristics.

**Nearest-feasible**

- Has substantial run-to-run variability.
- Has poor average cluster coverage.
- Can repeatedly service a subset of clusters without covering the deployment.
- Its performance should not be interpreted as a reliable full-coverage strategy.

**Data-greedy**

- Delivers the most data among the three heuristic policies in the multi-seed experiment.
- Achieves full observed cluster coverage.
- Has lower CH awake fraction and primary CH energy than the fixed tour.
- Has poorer meeting success and higher missed-window fraction than the fixed tour.

**Energy-data-score**

- Has the lowest primary CH energy among the tested policies.
- Achieves full observed cluster coverage.
- Delivers less data than data-greedy in the reported multi-seed results.
- Has relatively poor meeting success and a high missed-window fraction.

### 9.7 Overall comparison

There is no single winner across all metrics.

The fixed tour is strongest in data delivery, PDR, and meeting reliability, but uses more travel and energy.

Data-greedy and energy-data-score reduce CH energy and achieve full observed cluster coverage, but their meeting reliability is lower.

Nearest-feasible has a significant coverage weakness and high variability.

The appropriate policy therefore depends on the objective being optimised.

---

## 10. Routing Smoke Experiment and Integration Tests

### 10.1 Smoke configuration

The short routing test uses:

`configs/phase2_routing_smoke.toml`

It executes all four policies using the actual experiment runner.

Reproduction command:

```bash
python3 -m experiments.run_experiment \
    configs/phase2_routing_smoke.toml \
    -j 1 \
    --results results
```

### 10.2 Routing integration tests

The test file is:

`tests/test_routing_policies.py`

The tests run the ns-3 experiment runner and inspect the generated visit sequences.

The six tests are:

1. `test_all_routing_policies_execute`
2. `test_no_immediate_repeated_cluster`
3. `test_no_aba_ping_pong`
4. `test_tour_follows_repeating_fixed_order`
5. `test_belief_policies_explore_all_clusters`
6. `test_nearest_feasible_does_not_claim_full_coverage`

Command:

```bash
python3 -m pytest tests/test_routing_policies.py -v
```

Result:

```text
6 passed in 9.15s
```

These are ns-3-backed integration tests, not tests using mocked routing results.

They validate observable policy behaviour from the generated simulation output. They do not independently verify every internal implementation detail, such as every possible belief-state update or every candidate-score calculation.

---

## 11. Automated Testing

The complete test suite was executed after adding the routing integration tests.

Command:

```bash
python3 -m pytest -v
```

Final result:

```text
========================= test session starts ==========================
collected 31 items

tests/test_clustering.py       19 passed
tests/test_routing_policies.py  6 passed
tests/test_simulation.py        6 passed

========================= 31 passed in 18.87s ==========================
```

### Test coverage summary

| Test module | Tests | Result |
|---|---:|---|
| `tests/test_clustering.py` | 19 | Passed |
| `tests/test_routing_policies.py` | 6 | Passed |
| `tests/test_simulation.py` | 6 | Passed |
| **Total** | **31** | **Passed** |

The tests cover:

- Sensor-to-cluster assignment.
- Meeting-point calculation.
- Primary and backup cluster-head feasibility.
- Initial cluster-head election.
- Tour construction.
- Deterministic topology generation.
- Gaussian-hotspot deployment.
- Routing policy execution.
- Repeated-visit and A-B-A prevention.
- Belief-policy exploration behaviour.
- Reading conservation.
- Wi-Fi energy accounting.
- Scheduled wake behaviour.
- Deterministic simulation output.

---

## 12. Configuration Files and Reproduction

The main Phase 2 configurations are:

| File | Purpose |
|---|---|
| `configs/phase2_routing_smoke.toml` | Short routing-policy smoke experiment |
| `configs/phase2_routing_multiseed.toml` | Ten-seed routing baseline comparison |
| `configs/gaussian_hotspot.toml` | Gaussian-hotspot topology example |
| `configs/eta_delay_test.toml` | ETA-delay test configuration |
| `configs/eta_delay_quantiles.toml` | p80/p90/p95/p99 quantile sweep |
| `configs/eta_multiseed.toml` | Ten-seed p80/p90/p95/p99 listening-energy comparison |

### Reproduce routing smoke test

```bash
python3 -m experiments.run_experiment \
    configs/phase2_routing_smoke.toml \
    -j 1 \
    --results results
```

### Reproduce routing multi-seed experiment

```bash
python3 -m experiments.run_experiment \
    configs/phase2_routing_multiseed.toml \
    -j 1 \
    --results results
```

### Reproduce ETA quantile sweep

```bash
python3 -m experiments.run_experiment \
    configs/eta_delay_quantiles.toml \
    -j 1 \
    --results results
```

### Reproduce Gaussian-hotspot tests

```bash
python3 -m pytest tests/test_clustering.py -v
```

### Reproduce the ten-seed ETA quantile experiment

```bash
python3 -m experiments.run_experiment \
    configs/eta_multiseed.toml \
    -j 1 \
    --results results_eta_energy
```

### Generate the ETA quantile summary and plot
```bash
python3 scripts/plot_eta_quantiles.py
```

### Reproduce the complete test suite

```bash
python3 -m pytest -v
```

---

## 13. Documentation and Interface Updates

The belief-state representation and its field definitions are documented in:

`docs/INTERFACES.md`

The documentation covers:

- Belief-state fields.
- Units.
- Flat-vector ordering.
- EWMA estimation.
- Estimated buffer calculation.
- Normalisation information.
- Phase 3 observation usage.

The meeting-promise and related design decisions are recorded in:

`docs/DESIGN_DECISIONS.md`

Before final handoff, verify that the following are also up to date:

- All Phase 2 configuration keys and defaults.
- Metrics emitted by the simulation.
- The final Gaussian-hotspot design decision.
- The final ETA quantile and listening-energy methodology.
- Any known limitations that affect interpretation of the results.

---

## 14. Known Limitations and Outstanding Work

The following limitations must remain visible when interpreting the Phase 2 results.

### 14.1 ETA quantile experiment scope

The p80/p90/p95/p99 comparison uses ten seeds for each quantile (40 runs total), with a network size of 100 sensors.

The results provide stronger evidence than the earlier single-seed sweep, but they do not establish generality across different network sizes or deployment configurations.

### 14.2 Scheduled listening-energy interpretation

Scheduled-window listening energy is now measured separately and used in the ETA quantile comparison.

It must be distinguished from:
- Total primary cluster-head energy.
- Overall Wi-Fi awake time.
- Mean scheduled-window listening duration.

These metrics describe different aspects of energy consumption and radio activity.

### 14.3 Quantile selection

P95 has the lowest observed mean scheduled-window listening energy and ties P99 on meeting success in the current experiment.

However, the energy standard deviations are substantial. The results do not establish statistical significance or prove that p95 is universally optimal.

### 14.4 Nearest-feasible coverage

Nearest-feasible does not guarantee full cluster coverage. Its poor coverage in the multi-seed experiment is an observed limitation, not a test failure.

### 14.5 Routing test scope

The routing integration tests validate the observable behaviour of the policies using ns-3 output. They do not constitute exhaustive tests of every internal routing decision or belief-state update.

### 14.6 Further validation

Additional network sizes and delay configurations would strengthen the generality of the ETA quantile findings.

## 15. Phase 2 Completion Checklist

| Deliverable | Status |
|---|---|
| UAV belief state implemented | Done |
| Belief vector documented in `docs/INTERFACES.md` | Done |
| Common meeting-promise rule | Implemented |
| Nearest-feasible baseline | Implemented and tested |
| Data-greedy baseline | Implemented and tested |
| Energy-data-score baseline | Implemented and tested |
| Existing fixed-tour baseline | Tested |
| Ping-pong prevention checks | Tested |
| Gaussian-hotspot deployment | Implemented and tested |
| ETA lateness recording | Implemented |
| Adaptive wake-window mechanism | Implemented |
| ETA p80/p90/p95/p99 ten-seed experiment | Done (40 runs) |
| Scheduled-window listening-energy measurement | Implemented and used |
| ETA quantile summary CSV | Generated |
| ETA quantile energy-versus-success plot | Generated |
| Ten-seed routing comparison | Run |
| Cluster coverage analysis | Run |
| Routing integration tests | 6 passed |
| Full automated test suite | 31 passed |
| Final documentation/configuration audit | Pending |
| Final Git review and commit | Pending |


## 16. Final Handoff Status

The core Phase 2 implementation and automated tests are complete.

The routing baselines have been evaluated across ten seeds, and the ETA quantile experiment has been completed across ten seeds for each of p80, p90, p95, and p99 (40 runs total).

The ETA analysis now includes:
- A comparison of meeting success and scheduled-window listening energy.
- Mean and standard deviation across ten seeds.
- A generated summary CSV.
- An energy-versus-meeting-success plot.

The results indicate that p95 achieves the highest observed meeting success (tied with p99) and the lowest mean scheduled-window listening energy among the tested variants. These findings are limited to the current experiment configuration.

Before the Phase 2 handoff is finalized, the remaining work is:

1. Audit configuration keys, defaults, emitted metrics, and design decisions.
2. Review the final Git changes and ensure generated result files are not accidentally included.
3. Commit the reviewed Phase 2 changes on the appropriate branch.

**Current status: Core implementation, experiments, analysis outputs, and automated tests complete; final audit and Git review pending.**