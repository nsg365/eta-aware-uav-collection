# Phase 3 results: PPO against the baselines

Same layout as `results_speed_jitter/`. Every experiment uses sir's noise: UAV speed uniform in
9-11 m/s on every leg, no extra delays. Each folder has `runs.csv` (one row per run) and the
output of every run (`n<sensors>/s<seed>/<policy>/`). Values below are the mean over 10
networks (seeds 1-10) with a 95 % confidence interval; "PDR minus tour" is paired network by
network. Plots use the same style as Prakruthi's (error bars are ±1 SD).

The PPO models (A1-A4, A4P) were trained only on 100-sensor uniform networks with the old noise
(`models/phase3_ppo/`) and are used here without retraining, except where marked. Rebuild this
folder with `python3 scripts/export_phase3_results.py`.

| Folder | What | Config |
|---|---|---|
| `ch_sweep_target_*`, `ch_sweep_plots`, `ch_sweep_routes` | Prakruthi's CH-count sweep (1000 sensors, about 6/10/15/20 clusters) | `configs/phase3_ch_sweep_*.toml` |
| `gaussian_scaling*` | 4 Gaussian hotspots, 100/1000/2000 sensors, CH failures on | `configs/phase3_gaussian_scaling.toml` |
| `bursts*` | Event bursts on 100-sensor uniform networks | `configs/phase3_bursts_eval.toml` |

## CH-count sweep

**Target 5 clusters (median 6), 1000 sensors**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.987 ± 0.010 | +0.00 ± 0.00 | 1.000 | 30.7 | 1.54 |
| Nearest Feasible | 0.987 ± 0.010 | -0.03 ± 0.09 | 1.000 | 37.8 | 1.54 |
| Data Greedy | 0.970 ± 0.034 | -1.74 ± 2.65 | 0.973 | 153.7 | 1.56 |
| Energy-Data Score | 0.969 ± 0.034 | -1.79 ± 2.66 | 0.969 | 155.7 | 1.56 |
| PPO A1 | 0.985 ± 0.012 | -0.20 ± 0.32 | 0.999 | 38.3 | 1.54 |
| PPO A2 | 0.983 ± 0.012 | -0.39 ± 0.74 | 0.995 | 53.2 | 1.54 |
| PPO A3 | 0.960 ± 0.023 | -2.65 ± 2.09 | 0.929 | 139.5 | 1.59 |
| PPO A4 | 0.987 ± 0.010 | -0.03 ± 0.13 | 1.000 | 34.9 | 1.54 |
| PPO A4P | 0.983 ± 0.010 | -0.35 ± 0.31 | 0.984 | 83.4 | 1.54 |

**Target 10 clusters (median 10), 1000 sensors**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.989 ± 0.002 | +0.00 ± 0.00 | 1.000 | 22.1 | 1.55 |
| Nearest Feasible | 0.989 ± 0.003 | -0.02 ± 0.15 | 0.999 | 24.7 | 1.55 |
| Data Greedy | 0.798 ± 0.098 | -19.10 ± 9.60 | 0.783 | 283.9 | 1.95 |
| Energy-Data Score | 0.664 ± 0.114 | -32.52 ± 11.26 | 0.714 | 114.1 | 2.44 |
| PPO A1 | 0.989 ± 0.002 | +0.01 ± 0.02 | 1.000 | 22.3 | 1.55 |
| PPO A2 | 0.989 ± 0.003 | -0.03 ± 0.18 | 0.999 | 28.1 | 1.55 |
| PPO A3 | 0.987 ± 0.003 | -0.18 ± 0.13 | 0.969 | 49.7 | 1.55 |
| PPO A4 | 0.990 ± 0.002 | +0.09 ± 0.09 | 1.000 | 25.9 | 1.55 |
| PPO A4P | 0.989 ± 0.003 | -0.00 ± 0.10 | 0.988 | 38.3 | 1.55 |

**Target 15 clusters (median 15), 1000 sensors**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.988 ± 0.001 | +0.00 ± 0.00 | 1.000 | 19.4 | 1.57 |
| Nearest Feasible | 0.969 ± 0.040 | -1.82 ± 4.01 | 0.997 | 27.7 | 1.60 |
| Data Greedy | 0.801 ± 0.081 | -18.61 ± 8.00 | 0.636 | 246.9 | 1.94 |
| Energy-Data Score | 0.639 ± 0.067 | -34.89 ± 6.62 | 0.515 | 157.0 | 2.48 |
| PPO A1 | 0.987 ± 0.002 | -0.05 ± 0.09 | 1.000 | 19.9 | 1.57 |
| PPO A2 | 0.986 ± 0.003 | -0.14 ± 0.27 | 0.998 | 26.1 | 1.57 |
| PPO A3 | 0.985 ± 0.002 | -0.21 ± 0.20 | 0.963 | 54.8 | 1.56 |
| PPO A4 | 0.987 ± 0.002 | -0.06 ± 0.11 | 0.998 | 25.0 | 1.57 |
| PPO A4P | 0.987 ± 0.002 | -0.07 ± 0.15 | 0.996 | 35.5 | 1.57 |

**Target 20 clusters (median 20), 1000 sensors**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.981 ± 0.004 | +0.00 ± 0.00 | 1.000 | 18.7 | 1.58 |
| Nearest Feasible | 0.777 ± 0.137 | -20.38 ± 13.68 | 0.960 | 74.5 | 2.22 |
| Data Greedy | 0.725 ± 0.038 | -25.58 ± 3.80 | 0.532 | 271.1 | 2.12 |
| Energy-Data Score | 0.558 ± 0.031 | -42.31 ± 3.17 | 0.407 | 125.0 | 2.81 |
| PPO A1 | 0.981 ± 0.004 | +0.00 ± 0.00 | 1.000 | 18.7 | 1.58 |
| PPO A2 | 0.981 ± 0.003 | +0.05 ± 0.07 | 1.000 | 20.4 | 1.58 |
| PPO A3 | 0.970 ± 0.010 | -1.04 ± 0.89 | 0.923 | 60.3 | 1.59 |
| PPO A4 | 0.979 ± 0.004 | -0.17 ± 0.23 | 0.985 | 25.4 | 1.58 |
| PPO A4P | 0.980 ± 0.003 | -0.07 ± 0.14 | 0.992 | 24.6 | 1.58 |

Plots: `ch_sweep_plots/` (PDR, UAV energy, CH energy, UAV energy per reading).
Routes: `ch_sweep_routes/target_*/tour_vs_ppo_A4.png`.

## Gaussian hotspots, 100/1000/2000 sensors

**100 sensors, 4 hotspots (mean 4.4 clusters)**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.994 ± 0.001 | +0.00 ± 0.00 | 1.000 | 28.5 | 15.24 |
| Nearest Feasible | 0.993 ± 0.001 | -0.09 ± 0.12 | 1.000 | 61.7 | 15.21 |
| Data Greedy | 0.992 ± 0.001 | -0.21 ± 0.12 | 0.871 | 185.5 | 15.34 |
| Energy-Data Score | 0.991 ± 0.002 | -0.24 ± 0.20 | 0.873 | 154.8 | 15.44 |
| PPO A1 | 0.994 ± 0.001 | -0.01 ± 0.04 | 0.999 | 39.3 | 15.22 |
| PPO A2 | 0.993 ± 0.001 | -0.03 ± 0.06 | 0.998 | 66.4 | 15.22 |
| PPO A3 | 0.992 ± 0.001 | -0.20 ± 0.12 | 0.954 | 105.4 | 15.32 |
| PPO A4 | 0.994 ± 0.001 | +0.00 ± 0.00 | 1.000 | 28.5 | 15.24 |
| PPO A4P | 0.993 ± 0.001 | -0.09 ± 0.07 | 0.981 | 73.4 | 15.24 |

**1000 sensors, 4 hotspots (mean 5.7 clusters)**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.857 ± 0.076 | +0.00 ± 0.00 | 1.000 | 34.2 | 1.80 |
| Nearest Feasible | 0.850 ± 0.083 | -0.67 ± 1.00 | 1.000 | 60.3 | 1.81 |
| Data Greedy | 0.785 ± 0.084 | -7.19 ± 5.16 | 0.888 | 234.7 | 1.96 |
| Energy-Data Score | 0.720 ± 0.069 | -13.70 ± 6.71 | 0.847 | 155.2 | 2.15 |
| PPO A1 | 0.849 ± 0.082 | -0.83 ± 1.25 | 0.997 | 62.4 | 1.82 |
| PPO A2 | 0.849 ± 0.081 | -0.79 ± 0.96 | 0.997 | 67.0 | 1.81 |
| PPO A3 | 0.827 ± 0.074 | -2.97 ± 2.37 | 0.951 | 109.5 | 1.87 |
| PPO A4 | 0.857 ± 0.076 | +0.00 ± 0.08 | 1.000 | 36.9 | 1.79 |
| PPO A4P | 0.853 ± 0.073 | -0.43 ± 0.42 | 0.991 | 63.5 | 1.80 |

**2000 sensors, 4 hotspots (mean 7.0 clusters)**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.605 ± 0.074 | +0.00 ± 0.00 | 1.000 | 36.0 | 1.29 |
| Nearest Feasible | 0.604 ± 0.074 | -0.05 ± 0.18 | 1.000 | 39.8 | 1.29 |
| Data Greedy | 0.479 ± 0.083 | -12.58 ± 7.47 | 0.835 | 220.5 | 1.70 |
| Energy-Data Score | 0.431 ± 0.089 | -17.43 ± 8.84 | 0.782 | 186.6 | 1.94 |
| PPO A1 | 0.603 ± 0.075 | -0.15 ± 0.35 | 0.998 | 42.5 | 1.30 |
| PPO A2 | 0.600 ± 0.075 | -0.51 ± 0.37 | 0.997 | 56.9 | 1.30 |
| PPO A3 | 0.580 ± 0.077 | -2.47 ± 1.47 | 0.951 | 112.7 | 1.36 |
| PPO A4 | 0.603 ± 0.073 | -0.16 ± 0.20 | 1.000 | 42.3 | 1.29 |
| PPO A4P | 0.600 ± 0.072 | -0.49 ± 0.29 | 0.995 | 52.5 | 1.30 |

At 1000 and 2000 sensors the PDR drop is buffer overflow (each CH serves 170-290 sensors), the
same for every policy that keeps its promises. Plots: `gaussian_scaling_plots/`.

## Event bursts

**100 sensors, uniform, 4 bursts/h (one cluster reads 20x faster for 30 min)**

| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |
|---|---|---|---|---|---|
| Tour (classical) | 0.817 ± 0.050 | +0.00 ± 0.00 | 1.000 | 16.3 | 9.61 |
| Nearest Feasible | 0.504 ± 0.098 | -31.28 ± 10.06 | 0.925 | 98.5 | 17.40 |
| Data Greedy | 0.624 ± 0.054 | -19.26 ± 5.03 | 0.250 | 251.4 | 12.88 |
| Energy-Data Score | 0.618 ± 0.055 | -19.93 ± 3.75 | 0.189 | 258.0 | 12.99 |
| PPO A4 | 0.759 ± 0.051 | -5.79 ± 1.25 | 0.825 | 106.8 | 10.24 |
| PPO A4P | 0.762 ± 0.057 | -5.45 ± 2.32 | 0.835 | 101.2 | 10.18 |
| PPO A4P (trained on bursts) | 0.817 ± 0.050 | +0.00 ± 0.00 | 1.000 | 16.3 | 9.61 |
| PPO A4P, faster fade (trained on bursts) | 0.772 ± 0.039 | -4.45 ± 1.87 | 0.814 | 118.6 | 10.13 |

Burst data lost to full buffers: Tour 0.283, Nearest Feasible 0.534, Data Greedy 0.528, Energy-Data Score 0.536, PPO A4 (no bursts in training) 0.371, PPO A4P (no bursts in training) 0.366, PPO A4P (trained on bursts) 0.283, PPO A4P, faster fade (trained on bursts) 0.330

Plots: `bursts_plots/`. Burst model: `burstsPerHour`, `burstDuration`, `burstMultiplier` in
`simulation/ns3/wsn-uav/config.h`. Training config: `configs/phase3_ppo_bursts.toml`.
