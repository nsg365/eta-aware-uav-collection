# Phase 1 Handoff: Simulator Realism and Reliability

## 1. Overview

Phase 1 focused on improving the realism and reliability of the ns-3-based Wireless Sensor Network (WSN) simulator used in the UAV-assisted data collection project.

The objective was to ensure that the simulator represents realistic sensor and radio energy consumption, uses a calibrated UAV–Cluster Head (CH) communication range, and accounts for timing uncertainties that may affect data collection.

The work was divided into three main tasks:

1. Energy parameter calibration.
2. UAV–CH Wi-Fi range calibration.
3. Introduction and evaluation of UAV delays and CH clock drift.

The experiments were conducted using the ns-3.47 simulation environment and the existing clustering and UAV routing pipeline.

---

## 2. Task 1: Energy Parameter Calibration

### 2.1 Objective

The simulator initially used energy parameters that needed to be checked against hardware specifications. The objective was to replace unsupported placeholder values with realistic radio parameters wherever reliable datasheet information was available.

The energy parameters affect the energy consumed by sensor nodes and Cluster Heads during communication and sleep periods.

### 2.2 Parameters investigated

The CC2420 radio was considered for the IEEE 802.15.4 communication model, while ESP32 Wi-Fi specifications were considered for the CH–UAV communication model.

| Parameter | Previous value | Updated / retained value | Explanation |
|---|---:|---:|---|
| 802.15.4 TX power | 0.0522 W | 0.0522 W | Consistent with CC2420 TX current of 17.4 mA at 3 V |
| 802.15.4 RX power | 0.0564 W | 0.0564 W | Consistent with CC2420 RX current of 18.8 mA at 3 V |
| Wi-Fi TX current | 0.24 A | 0.19 A | Updated to 190 mA, corresponding to the ESP32 802.11g TX specification at 16 dBm |
| Wi-Fi RX current | 0.10 A | 0.10 A | Retained; consistent with the approximately 95–100 mA datasheet range |
| Wi-Fi idle current | 0.10 A | 0.10 A | Retained as an approximation |
| Wi-Fi sleep current | 0.00015 A | 0.00015 A | Reviewed; exact support for this value needs to be stated cautiously |
| Initial sensor energy | 500 J | 500 J | Retained as an experimental assumption |

The 802.15.4 TX and RX power values were already consistent with the CC2420 specifications, so they were retained rather than changed.

The Wi-Fi TX current was reduced from 240 mA to 190 mA to better reflect the hardware specification.

The initial energy of 500 J was retained as a simulation assumption rather than presented as a measured hardware value.

### 2.3 Files involved

- `simulation/ns3/wsn-uav/config.h`
  - Updated the Wi-Fi TX current parameter.
  - Reviewed the other radio energy parameters.
- `docs/DESIGN_DECISIONS.md`
  - Documented the energy parameter choices and their rationale.

### 2.4 Outcome

The energy model was reviewed against available hardware specifications. Parameters supported by datasheet information were retained or updated accordingly.

The remaining approximations, such as idle and sleep currents, should be treated as modeling assumptions rather than exact hardware measurements.

---

## 3. Task 2: UAV–CH Wi-Fi Range Calibration

### 3.1 Objective

The simulator previously used a UAV communication range of 80 m.

However, this value was not established through a delivery-ratio calibration experiment. Since UAV–CH communication uses an ns-3 Wi-Fi link with a propagation model, a nominal range should be selected based on the observed communication performance.

The objective was to investigate the relationship between UAV–CH distance and successful data collection.

### 3.2 Methodology

A distance sweep was performed by varying the UAV–CH separation and observing the delivery performance of the simulated link.

The experiment was intended to establish a practical communication range instead of relying on the previously assumed 80 m value.

The measurements were collected using the existing simulation environment and its delivery metrics.

### 3.3 Results

The recorded calibration findings include:

| UAV–CH distance | Observed delivery performance |
|---|---:|
| 30 m | Approximately 99% |
| 42 m | Approximately 73.76% average |

The results indicate that communication performance degrades as UAV–CH distance increases.

At 30 m, the simulated link demonstrated substantially higher delivery performance than at 42 m.

### 3.4 Interpretation

The distance sweep demonstrates that the communication range should not be treated as a fixed value independent of the underlying propagation model.

A range of 80 m should not be assumed to provide reliable communication without calibration.

The 30 m operating distance showed approximately 99% delivery performance, whereas 42 m showed a significant reduction.

**Important:** The delivery measurements are based on the simulator's data collection metrics. They should not automatically be interpreted as pure PHY-layer or Wi-Fi packet delivery ratios, since the overall metrics also depend on UAV visits, CH buffering, and simulation timing.

### 3.5 Files involved

- `simulation/ns3/wsn-uav/config.h`
  - Contains the UAV range parameter.
- `docs/DESIGN_DECISIONS.md`
  - Documents the range calibration rationale and design choice.

The exact final configured value of `uav_range_m` and the names of any dedicated sweep scripts or generated files should be verified from the repository before the handoff is finalized.

### 3.6 Outcome

The distance sweep provided experimental evidence for selecting a more realistic UAV–CH communication range.

The results also demonstrate that increasing the UAV–CH separation can significantly degrade delivery performance.

---

## 4. Task 3: UAV Delay and CH Clock Drift Stressors

### 4.1 Objective

Real-world UAV-assisted WSNs are affected by timing uncertainties.

The UAV may experience unexpected delays while traveling between Cluster Heads. Additionally, individual CHs may have clock offsets, causing them to believe that their scheduled communication windows open at different times than expected.

The objective was to introduce these timing stressors and investigate their effects on data collection performance.

The two stressors considered were:

1. Stochastic UAV leg delays.
2. Bounded CH clock offsets.

### 4.2 UAV delay experiment

The UAV delay experiment compared the baseline simulation against a configuration in which all UAV flight legs were subjected to stochastic delays.

The experiments were conducted with 60 sensors and five random seeds.

The simulation horizon was 7200 seconds.

#### Experimental conditions

- Baseline: No additional UAV leg delays.
- All legs delayed: Stochastic additional delay introduced on UAV flight legs.

#### Results

| Seed | Baseline PDR | Delayed PDR | Improvement |
|---|---:|---:|---:|
| 1 | 51.620% | 53.662% | +2.042 pp |
| 2 | 34.352% | 46.635% | +12.283 pp |
| 3 | 37.710% | 41.498% | +3.788 pp |
| 4 | 32.328% | 44.397% | +12.069 pp |
| 5 | 34.035% | 40.570% | +6.535 pp |
| **Mean** | **38.009%** | **45.352%** | **+7.343 pp** |

The mean collection PDR increased by approximately 19.3% relative to the baseline.

#### Buffer backlog comparison

| Metric | Baseline | All legs delayed |
|---|---:|---:|
| Mean delivered readings | 1363.8 | 1624.6 |
| Mean readings remaining in buffers at the end | 2215.0 | 1954.2 |

The number of delivered readings increased by an average of 260.8 readings.

The mean end-of-simulation buffer backlog decreased by the same amount.

#### Loss metrics

Across the five seeds:

- Buffer overflow: 0
- 802.15.4 losses: 0
- Wi-Fi loss counter: 0

The Wi-Fi loss counter is calculated as the difference between readings sent and readings delivered. It may include readings still in flight at the simulation horizon and should not automatically be interpreted as actual packet loss.

#### UAV delay

The mean additional UAV delay time was approximately 90.44 seconds across the five delayed runs.

The delay was introduced as a timing stressor and was not intended to improve the system.

### 4.3 Interpretation of UAV delay results

The results showed a consistent increase in collection PDR across all five seeds.

However, the number of UAV visits remained unchanged in the earlier visit-level analysis. The delay experiment also showed an increase in the number of readings collected during visits, alongside a reduction in end-of-horizon buffer backlog.

This suggests that the PDR improvement is primarily associated with the timing of data collection within the finite simulation horizon rather than an improvement in wireless transmission reliability.

The effect was seed-dependent. Seeds 2 and 4 showed larger improvements than seeds 1 and 3.

The result should therefore not be generalized to imply that UAV delays inherently improve system performance. The delays may shift the UAV schedule in a favorable way for a particular simulation horizon.

### 4.4 CH clock drift experiment

A separate experiment compared:

- No clock drift.
- A bounded CH clock drift of 5 seconds.

The experiment was conducted using 60 sensors and five random seeds.

The results showed that the effect of clock drift on overall collection PDR was limited in most seeds.

The wake scheduling counters indicated that:

- Scheduled windows were generated.
- Only a small number of scheduled windows were opened or successfully met.
- Discovery contacts accounted for a substantial portion of UAV–CH communication.

This suggests that the existing discovery mechanism may reduce the impact of the bounded clock offset on overall data collection.

The clock drift experiment should therefore be interpreted as a stressor evaluation that exposed the behavior of the current wake scheduling and discovery mechanisms, rather than as evidence that clock drift has no effect.

Further investigation of scheduled-window handling and discovery fallback behavior may be useful.

### 4.5 PDR accounting verification

The PDR calculation was verified in `simulation/ns3/wsn-uav/world.cc`.

The metric is calculated as:

\[
\text{PDR}=\frac{\text{delivered readings}}{\text{generated readings}}
\]

The metric represents the fraction of generated readings received by the UAV within the simulation horizon.

The output metrics include:

- `generated`
- `delivered`
- `pdr`
- `overflow`
- `lost_154`
- `lost_wifi`
- `lost_ch_dead`
- `in_buffer_at_end`

For the lossless delay experiments, the accounting was consistent with:

\[
\text{generated}
=
\text{delivered}
+
\text{in\_buffer\_at\_end}
\]

This verification was important to ensure that the PDR improvement was not caused by a change in the metric definition.

### 4.6 Files and experiment outputs

The experiment outputs were generated under:

- `results/phase1_tests/uav_delay_test/n60/`
- `results/phase1_tests/clock_drift_narrow_test/n60/`

The UAV delay experiment contains seed-specific configurations:

- `baseline`
- `all_legs_delayed`
- `no_clock_drift`
- `clock_drift_5s`

The clock drift experiment contains:

- `no_clock_drift`
- `clock_drift_5s`

Each run includes a `metrics.json` output.

The output metrics and their calculations were inspected in:

- `simulation/ns3/wsn-uav/world.cc`

The precise list of source code files modified to introduce the stressors should be verified using Git before finalizing this handoff.

### 4.7 Outcome

The stochastic UAV delay stressor was evaluated across five seeds and showed a consistent increase in collection PDR.

The bounded clock drift stressor was also investigated. The existing discovery mechanism appeared to mitigate much of its impact on collection performance.

The results demonstrate that UAV timing and CH scheduling behavior are relevant factors in the simulator and should be considered when evaluating routing and wake scheduling policies.

---

## 5. Overall Findings

The Phase 1 work addressed simulator realism in terms of energy modeling, communication range, and timing uncertainties.

The key findings are:

1. Radio energy parameters were reviewed against available hardware specifications, and the Wi-Fi TX current was updated.
2. The UAV–CH distance sweep demonstrated a significant degradation in delivery performance with increasing distance.
3. The previously assumed UAV range of 80 m required calibration based on observed communication performance.
4. Stochastic UAV delays consistently increased collection PDR in the five-seed experiment, but the improvement was primarily associated with collection timing and reduced buffer backlog.
5. Bounded CH clock drift was investigated, and the discovery mechanism appeared to mitigate much of its impact.
6. PDR accounting was verified against the simulator's generated, delivered, and buffered reading counts.

---

## 6. Limitations and Remaining Work

The following points should be considered before the Phase 1 work is treated as fully complete:

- The calibrated UAV–CH range should be confirmed in the final configuration.
- Energy values that are not directly supported by hardware datasheets should remain explicitly documented as approximations.
- The delay experiment demonstrates a collection-timing effect; it does not demonstrate an improvement in wireless reliability.
- The clock drift experiment showed limited overall impact, potentially due to the discovery mechanism.
- The primary CH failure and backup takeover mechanisms described in the reliability design should be verified separately. Their implementation and testing are not established by the timing stressor experiments alone.
- The exact source file list should be checked using Git to distinguish modified files from generated experiment outputs.

---

## 7. Final Conclusion

Phase 1 improved the realism of the WSN-UAV simulator by reviewing radio energy parameters, calibrating the UAV–CH communication distance, and evaluating timing stressors.

The experiments showed that the UAV–CH communication distance has a substantial effect on delivery performance. They also demonstrated that timing uncertainties can affect the fraction of generated readings collected within a finite simulation horizon.

The UAV delay experiment produced a consistent PDR increase across five seeds, accompanied by a reduction in the end-of-simulation buffer backlog. This improvement is interpreted as a collection-timing effect rather than an enhancement in wireless link reliability.

The clock drift experiment showed that the existing discovery mechanism may mitigate the effect of bounded CH clock offsets.

Overall, the work provides a more experimentally grounded simulator configuration for subsequent UAV routing and reinforcement learning experiments. Full reliability completion should additionally require verification of the primary CH failure and backup takeover mechanisms.

## 8. Files Changed or Added

### Modified files

**Simulation source code**
- `simulation/ns3/wsn-uav/config.h`
- `simulation/ns3/wsn-uav/ch-app.cc`
- `simulation/ns3/wsn-uav/ch-app.h`
- `simulation/ns3/wsn-uav/uav-app.cc`
- `simulation/ns3/wsn-uav/uav-app.h`
- `simulation/ns3/wsn-uav/world.cc`
- `simulation/ns3/wsn-uav/world.h`
- `simulation/ns3/wsn-uav/wsn-uav.cc`

**Configuration**
- `configs/default.toml`
- `configs/example_wake_modes.toml`

**Documentation**
- `docs/DESIGN_DECISIONS.md`

### Added files

**Experiment configurations**
- `configs/test_clock_drift.toml`
- `configs/test_clock_drift_metrics.toml`
- `configs/test_clock_drift_metrics_v3.toml`
- `configs/test_clock_drift_narrow.toml`
- `configs/test_clock_drift_smoke.toml`
- `configs/test_uav_delay.toml`

**Analysis scripts**
- `compare_visits.py`
- `scripts/analysis/analyze_clock_drift.py`
- `scripts/analysis/compare_clock_drift.sh`
- `scripts/analysis/inspect_clock_metrics.sh`
- `scripts/analysis/inspect_discovery.sh`

**Experiment execution scripts**
- `scripts/experiments/run_clock_drift.sh`
- `scripts/experiments/run_clock_drift_narrow.sh`
- `scripts/experiments/run_uav_delay.sh`

**Handoff documentation**
- `docs/PHASE1_HANDOFF_until_task3.md`

### Generated experiment outputs

Experiment results were generated under `results/phase1_tests/`, including UAV delay and clock drift experiment metrics. These are simulation outputs and are not listed as source-code changes in the current Git status.
