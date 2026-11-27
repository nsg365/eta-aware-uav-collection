#!/usr/bin/env python3
"""Copy the Phase 3 PPO results into results_phase3_ppo/ (committed), with plots and tables.

Same layout as Prakruthi's results_speed_jitter/: one folder per experiment with runs.csv and
every run's output, a *_plots folder and a *_routes folder. README.md holds the tables.
All experiments use sir's noise (UAV speed uniform 9-11 m/s per leg, no extra delays).

    python3 scripts/export_phase3_results.py

Reads (run these first):
  results/phase3_ch_sweep_{05,10,15,20}/   configs/phase3_ch_sweep_*.toml
  results/phase3_gaussian_scaling/         configs/phase3_gaussian_scaling.toml
  results/phase3_bursts_eval/              configs/phase3_bursts_eval.toml
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "results"
OUT = REPO / "results_phase3_ppo"
SEED = 3  # network shown in the route pictures

STYLE = {  # same colours and markers as scripts/plot_ch_sweep_ppo.py
    "tour":              ("Tour (classical)",  "#2563eb", "o"),
    "nearest_feasible":  ("Nearest Feasible",  "#16a34a", "s"),
    "data_greedy":       ("Data Greedy",       "#dc2626", "^"),
    "energy_data_score": ("Energy-Data Score", "#9333ea", "D"),
    "ppo_A1":            ("PPO A1",            "#94a3b8", "<"),
    "ppo_A2":            ("PPO A2",            "#475569", ">"),
    "ppo_A3":            ("PPO A3",            "#f59e0b", "v"),
    "ppo_A4":            ("PPO A4",            "#0f172a", "P"),
    "ppo_A4P":           ("PPO A4P",           "#64748b", "X"),
}
BASELINES = ["tour", "nearest_feasible", "data_greedy", "energy_data_score"]
PPO = ["ppo_A1", "ppo_A2", "ppo_A3", "ppo_A4", "ppo_A4P"]


def copy_experiment(src: Path, dst: Path) -> pd.DataFrame:
    """runs.csv plus every run folder (the shared topology folders are left out)."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("topology", "summary.*"))
    runs = pd.read_csv(src / "runs.csv")
    runs["uav_kJ"] = (runs["uav.flight_energy_J_est"] + runs["uav.hover_energy_J_est"]) / 1e3
    runs["uav_J_per_reading"] = runs["uav_kJ"] * 1e3 / runs["data.delivered"]
    return runs


def ci95(x: pd.Series) -> float:
    return float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0


def table(runs: pd.DataFrame, group: str, label, variants: list[str]) -> str:
    """Markdown table: PDR, on-time, CH energy, UAV energy per reading and PDR minus the tour."""
    lines = []
    for key, g in runs.groupby(group):
        tour = g[g.variant == "tour"].set_index("run.seed")["data.pdr"]
        lines.append(f"\n**{label(key, g)}**\n")
        lines.append("| Policy | PDR | PDR minus tour (points) | On-time | CH energy (J) | UAV J per reading |")
        lines.append("|---|---|---|---|---|---|")
        for v in variants:
            x = g[g.variant == v]
            if x.empty:
                continue
            diff = (x.set_index("run.seed")["data.pdr"] - tour) * 100
            name = STYLE.get(v, (v,))[0]
            lines.append(
                f"| {name} | {x['data.pdr'].mean():.3f} ± {ci95(x['data.pdr']):.3f} | "
                f"{diff.mean():+.2f} ± {ci95(diff):.2f} | {x['wake.meeting_success_rate'].mean():.3f} | "
                f"{x['energy.primary_ch_mean_J'].mean():.1f} | {x['uav_J_per_reading'].mean():.2f} |")
    return "\n".join(lines) + "\n"


def line_plot(runs: pd.DataFrame, x_col: str, metric: str, ylabel: str, title: str,
              xlabel: str, variants: list[str], path: Path, scale: float = 1.0) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    for v in variants:
        name, color, marker = STYLE[v]
        g = runs[runs.variant == v].groupby(x_col)[metric]
        m, s = g.mean() * scale, g.std(ddof=1) * scale
        ax.errorbar(m.index, m.values, yerr=s.values, label=name, color=color, marker=marker,
                    markersize=7, linewidth=1.8, capsize=4, capthick=1.5, elinewidth=1.2, zorder=3)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_xticks(sorted(runs[x_col].unique()))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=10, framealpha=0.85, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def bar_plot(runs: pd.DataFrame, metric: str, ylabel: str, title: str, variants: list[str],
             names: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    xs = np.arange(len(variants))
    for i, v in enumerate(variants):
        x = runs[runs.variant == v][metric]
        color = STYLE.get(v, (None, "#0f172a"))[1]
        ax.bar(i, x.mean(), yerr=ci95(x), color=color, width=0.65, capsize=4, edgecolor="white")
        ax.text(i, x.mean() + ci95(x) + 0.01, f"{x.mean():.3f}", ha="center", fontsize=9)
    ax.set_xticks(xs, [names[v] for v in variants], rotation=20, ha="right")
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def route_plot(run_dir: Path, variants: list[str], path: Path, title: str, laps: int = 2) -> None:
    """Sensors, meeting points and the first `laps` laps of each policy's route, side by side."""
    nodes = pd.read_csv(run_dir / "topology" / "nodes.csv")
    clusters = pd.read_csv(run_dir / "topology" / "clusters.csv")
    meet = clusters.set_index("cluster_id")[["meet_x", "meet_y"]]
    fig, axes = plt.subplots(1, len(variants), figsize=(6 * len(variants), 6))
    for ax, v in zip(np.atleast_1d(axes), variants):
        visits = pd.read_csv(run_dir / v / "visits.csv").head(laps * len(clusters) + 1)
        path_xy = np.vstack([[0.0, 0.0], meet.loc[visits.cluster_id].to_numpy()])
        name, color, _ = STYLE.get(v, (v, "#0f172a", "o"))
        ax.scatter(nodes.x, nodes.y, s=2 if len(nodes) > 300 else 6, color="#94a3b8", alpha=0.5)
        ax.plot(path_xy[:, 0], path_xy[:, 1], color=color, linewidth=1.4, alpha=0.8)
        ax.scatter(meet.meet_x, meet.meet_y, s=40, facecolors="none", edgecolors="#0f172a", zorder=3)
        ax.scatter([0], [0], marker="s", color="#0f172a", s=40, zorder=3)
        ax.set_title(f"{name}: first {laps} laps", fontsize=12, fontweight="bold")
        ax.set_xlim(-10, 510)
        ax.set_ylim(-10, 510)
        ax.set_aspect("equal")
        ax.set_xticks([0, 250, 500])
        ax.set_yticks([0, 250, 500])
    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def ch_sweep() -> str:
    frames = []
    for t in ["05", "10", "15", "20"]:
        runs = copy_experiment(SRC / f"phase3_ch_sweep_{t}", OUT / f"ch_sweep_target_{t}")
        runs["target"] = int(t)
        frames.append(runs)
        (OUT / "ch_sweep_routes" / f"target_{t}").mkdir(parents=True, exist_ok=True)
        route_plot(SRC / f"phase3_ch_sweep_{t}" / "n1000" / f"s{SEED}", ["tour", "ppo_A4"],
                   OUT / "ch_sweep_routes" / f"target_{t}" / "tour_vs_ppo_A4.png",
                   f"CH sweep, about {int(t)} clusters, network {SEED}")
    runs = pd.concat(frames, ignore_index=True)
    plots = OUT / "ch_sweep_plots"
    plots.mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "plot_ch_sweep_ppo.py"), "--results",
                    str(SRC), "--out", str(plots)], check=True, stdout=subprocess.DEVNULL)
    label = lambda t, g: f"Target {t} clusters (median {g['run.num_clusters'].median():.0f}), 1000 sensors"
    return table(runs, "target", label, BASELINES + PPO)


def gaussian() -> str:
    runs = copy_experiment(SRC / "phase3_gaussian_scaling", OUT / "gaussian_scaling")
    plots = OUT / "gaussian_scaling_plots"
    plots.mkdir(exist_ok=True)
    show = BASELINES + ["ppo_A3", "ppo_A4", "ppo_A4P"]
    for metric, ylabel, title, scale in [
            ("data.pdr", "PDR (%)", "PDR vs Number of Sensors", 100.0),
            ("wake.meeting_success_rate", "Meetings on time (%)", "Meetings on Time vs Number of Sensors", 100.0),
            ("energy.primary_ch_mean_J", "Mean primary CH energy (J)", "CH Energy vs Number of Sensors", 1.0),
            ("uav_J_per_reading", "UAV energy per reading (J)", "UAV Energy per Delivered Reading", 1.0)]:
        line_plot(runs, "run.num_sensors", metric, ylabel, title, "Number of sensors (4 Gaussian hotspots)",
                  show, plots / f"{metric.split('.')[-1]}.png", scale)
    (OUT / "gaussian_scaling_routes").mkdir(exist_ok=True)
    for n in [100, 1000, 2000]:
        route_plot(SRC / "phase3_gaussian_scaling" / f"n{n}" / f"s{SEED}", ["tour", "ppo_A4"],
                   OUT / "gaussian_scaling_routes" / f"n{n}_tour_vs_ppo_A4.png",
                   f"Gaussian hotspots, {n} sensors, network {SEED}")
    label = lambda n, g: f"{n} sensors, 4 hotspots (mean {g['run.num_clusters'].mean():.1f} clusters)"
    return table(runs, "run.num_sensors", label, BASELINES + PPO)


def bursts() -> str:
    runs = copy_experiment(SRC / "phase3_bursts_eval", OUT / "bursts")
    names = {"tour": "Tour", "nearest_feasible": "Nearest Feasible", "data_greedy": "Data Greedy",
             "energy_data_score": "Energy-Data Score", "ppo_A4": "PPO A4\n(no bursts in training)",
             "ppo_A4P": "PPO A4P\n(no bursts in training)", "ppo_A4P_bursts": "PPO A4P\n(trained on bursts)",
             "ppo_A4Pb_bursts": "PPO A4P, faster fade\n(trained on bursts)"}
    variants = [v for v in names if v in set(runs.variant)]
    plots = OUT / "bursts_plots"
    plots.mkdir(exist_ok=True)
    bar_plot(runs, "data.pdr", "PDR", "Event Bursts: PDR (10 networks, 95 % CI)", variants, names,
             plots / "pdr.png")
    bar_plot(runs, "bursts.overflow_ratio", "Share of burst data lost to full buffers",
             "Event Bursts: Burst Data Lost", variants, names, plots / "burst_loss.png")
    bar_plot(runs, "wake.meeting_success_rate", "Meetings on time", "Event Bursts: Meetings on Time",
             variants, names, plots / "meeting_success_rate.png")
    for v in variants:
        STYLE.setdefault(v, (names[v].replace("\n", " "), "#0f172a", "o"))
    label = lambda n, g: f"100 sensors, uniform, 4 bursts/h (one cluster reads 20x faster for 30 min)"
    out = table(runs, "run.num_sensors", label, variants)
    loss = runs.groupby("variant")["bursts.overflow_ratio"].mean()
    out += "\nBurst data lost to full buffers: " + ", ".join(
        f"{names[v].replace(chr(10), ' ')} {loss[v]:.3f}" for v in variants) + "\n"
    return out


README = """# Phase 3 results: PPO against the baselines

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
{ch}
Plots: `ch_sweep_plots/` (PDR, UAV energy, CH energy, UAV energy per reading).
Routes: `ch_sweep_routes/target_*/tour_vs_ppo_A4.png`.

## Gaussian hotspots, 100/1000/2000 sensors
{gauss}
At 1000 and 2000 sensors the PDR drop is buffer overflow (each CH serves 170-290 sensors), the
same for every policy that keeps its promises. Plots: `gaussian_scaling_plots/`.

## Event bursts
{bursts}
Plots: `bursts_plots/`. Burst model: `burstsPerHour`, `burstDuration`, `burstMultiplier` in
`simulation/ns3/wsn-uav/config.h`. Training config: `configs/phase3_ppo_bursts.toml`.
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    text = README.format(ch=ch_sweep(), gauss=gaussian(), bursts=bursts())
    (OUT / "README.md").write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
