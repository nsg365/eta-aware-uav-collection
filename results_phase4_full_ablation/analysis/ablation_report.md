# Phase 4 matched ablation analysis

Pairing key: network size (`run.num_sensors`) and seed (`run.seed`).
All effects are treatment minus control. Positive/negative direction must be interpreted per metric.
Paired 95% t confidence intervals are reported; Wilcoxon signed-rank p-values are Holm-adjusted
within each experiment × network-size family across the listed metrics/comparisons.

## Significant paired differences (Holm-adjusted p < 0.05)

| Experiment | N | Comparison (treatment − control) | Metric | Mean difference | 95% CI | Holm p |
|---|---:|---|---|---:|---:|---:|
| A7_backup_CH | 100 | backup_enabled_control - a7_no_backup | data.pdr | 0.038241 | [0.020725, 0.055758] | 0.01758 |
| A7_backup_CH | 100 | backup_enabled_control - a7_no_backup | reliability.backup_promotions | 3.2 | [2.3206, 4.0794] | 0.01758 |
| A7_backup_CH | 100 | backup_enabled_control - a7_no_backup | reliability.failures_no_backup | -3 | [-4.0117, -1.9883] | 0.01758 |
| A7_backup_CH | 100 | backup_enabled_control - a7_no_backup | uav.distance_m | 537.33 | [297.61, 777.06] | 0.02344 |
| A7_backup_CH | 150 | backup_enabled_control - a7_no_backup | data.pdr | 0.045411 | [0.013868, 0.076955] | 0.01758 |
| A7_backup_CH | 150 | backup_enabled_control - a7_no_backup | reliability.backup_promotions | 3.3 | [1.7528, 4.8472] | 0.01758 |
| A7_backup_CH | 150 | backup_enabled_control - a7_no_backup | reliability.failures_no_backup | -2.9 | [-3.9901, -1.8099] | 0.01758 |
| A7_backup_CH | 150 | backup_enabled_control - a7_no_backup | uav.distance_m | 681.91 | [285.73, 1078.1] | 0.01758 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | energy.sensor_total_J | 376.01 | [159.79, 592.23] | 0.02539 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.backup_promotions | 16.1 | [14.691, 17.509] | 0.02539 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.failures_no_backup | 32.2 | [18.959, 45.441] | 0.02539 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.heartbeat_failure_triggers | -3.7 | [-5.2472, -2.1528] | 0.02539 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.missed_meeting_triggers | 48.6 | [35.556, 61.644] | 0.02539 |
| A8_immediate_failover | 60 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.post_death_contact_triggers | 3.4 | [2.2221, 4.5779] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | data.pdr | -0.013868 | [-0.022798, -0.0049374] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.backup_promotions | 24.4 | [20.718, 28.082] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.failures_no_backup | 24.5 | [14.427, 34.573] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.heartbeat_failure_triggers | -3.8 | [-5.1404, -2.4596] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.missed_meeting_triggers | 49 | [36.079, 61.921] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.post_death_contact_triggers | 3.7 | [2.5294, 4.8706] | 0.02539 |
| A8_immediate_failover | 100 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.retry_successes | -22.2 | [-32.582, -11.818] | 0.02734 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | data.pdr | -0.015305 | [-0.0231, -0.0075106] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | energy.sensor_total_J | 630.12 | [296.92, 963.32] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.backup_promotions | 34.1 | [27.128, 41.072] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.failures_no_backup | 17.3 | [8.1449, 26.455] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.heartbeat_failure_triggers | -4.2 | [-5.6227, -2.7773] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.missed_meeting_triggers | 51.4 | [35.756, 67.044] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.post_death_contact_triggers | 4.2 | [2.7773, 5.6227] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | reliability.retry_successes | -28.3 | [-36.122, -20.478] | 0.02539 |
| A8_immediate_failover | 150 | a8_immediate_missed_meeting - heartbeat_baseline | wake.windows_met | -25.3 | [-37.589, -13.011] | 0.02539 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | energy.sensor_total_J | 4165 | [3026.8, 5303.2] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | reliability.retry_attempts | 91.2 | [41.04, 141.36] | 0.03906 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | uav.contacts | -22.4 | [-35.365, -9.4347] | 0.03906 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | uav.distance_m | 6187 | [4909.5, 7464.5] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | uav.flight_energy_J_est | 84988 | [67329, 1.0265e+05] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | uav.hover_energy_J_est | -96011 | [-1.1596e+05, -76057] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | wake.ch_wifi_awake_fraction | 0.069654 | [0.052533, 0.086775] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | wake.mean_window_listen_s | 22.917 | [13.333, 32.5] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | wake.scheduled_window_energy_J | 2906.1 | [1877, 3935.2] | 0.0332 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | wake.windows_met | -44.7 | [-70.999, -18.401] | 0.04102 |
| A9_survey_lap | 60 | a9_no_survey_lap - a4_survey_lap_control | wake.windows_scheduled | -22.4 | [-35.365, -9.4347] | 0.03906 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | energy.sensor_total_J | 3540.9 | [1917.6, 5164.2] | 0.0332 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | uav.distance_m | 6412.9 | [4555.7, 8270] | 0.0332 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | uav.flight_energy_J_est | 89354 | [66885, 1.1182e+05] | 0.0332 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | uav.hover_energy_J_est | -1.0172e+05 | [-1.28e+05, -75432] | 0.0332 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | wake.ch_wifi_awake_fraction | 0.058443 | [0.033643, 0.083243] | 0.0332 |
| A9_survey_lap | 100 | a9_no_survey_lap - a4_survey_lap_control | wake.scheduled_window_energy_J | 2129.6 | [544.87, 3714.3] | 0.04688 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | energy.sensor_total_J | 4493.6 | [2994.3, 5992.8] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | reliability.promise_violations | 29.7 | [15.964, 43.436] | 0.03516 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | reliability.retry_attempts | 93.4 | [49.671, 137.13] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | reliability.retry_successes | 21.8 | [7.9829, 35.617] | 0.03516 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | uav.distance_m | 6382.2 | [4526, 8238.4] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | uav.flight_energy_J_est | 91928 | [67216, 1.1664e+05] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | uav.hover_energy_J_est | -1.0414e+05 | [-1.3177e+05, -76508] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.ch_wifi_awake_fraction | 0.067696 | [0.044884, 0.090508] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.mean_window_listen_s | 20.097 | [9.7637, 30.431] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.meeting_success_rate | -0.065014 | [-0.095267, -0.034762] | 0.03516 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.scheduled_window_energy_J | 2823 | [1406, 4239.9] | 0.0332 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.windows_met | -50 | [-76.929, -23.071] | 0.03516 |
| A9_survey_lap | 150 | a9_no_survey_lap - a4_survey_lap_control | wake.windows_missed | 29.7 | [15.964, 43.436] | 0.03516 |

## Files

- `variant_summary_by_size.csv`: descriptive mean, SD, and median by variant and sensor size.
- `paired_statistics.csv`: paired effects, confidence intervals, paired t-tests, Wilcoxon tests, and Holm correction.
- `figures/`: paired effect plots for selected metrics.
