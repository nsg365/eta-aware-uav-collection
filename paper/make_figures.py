#!/usr/bin/env python3
"""Draw the data figures of the paper (figures/*.pdf) from the experiment results.

    cd paper && python3 make_figures.py --results ../results --phase4 ../results_phase4

Reads results/phase3_eval, results/phase3_ch_sweep_{05,10,15,20} and the matching
results/qlearning_* runs (configs/qlearning/), and results_phase4/phase4_uav_delay.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

OUT = Path(__file__).resolve().parent / "figures"

# One colour per policy, the same in every figure.
STYLE = {
    "tour":              ("Tour",               "#2a78d6", "o"),
    "ppo_A4":            ("PPO A4",             "#eb6834", "s"),
    "nearest_feasible":  ("Nearest feasible",   "#1baf7a", "^"),
    "data_greedy":       ("Data greedy",        "#eda100", "D"),
    "energy_data_score": ("Energy–data score", "#6250d6", "v"),
    "q_learning":        ("Q-learning",         "#e34948", "X"),
}

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "lines.linewidth": 1.4,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#dddddd", "grid.linewidth": 0.5, "savefig.bbox": "tight",
})


def ci95(x: pd.Series) -> float:
    x = x.dropna()
    return float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)))


def routes(results: Path) -> None:
    """Fig. 2: the same 20 minutes of one mission (network 3, 100 sensors) for four policies."""
    run = results / "phase3_eval" / "n100" / "s3"
    meet = pd.read_csv(run / "topology" / "clusters.csv").set_index("cluster_id")[["meet_x", "meet_y"]]
    nodes = pd.read_csv(run / "topology" / "nodes.csv")
    panels = [("tour", run / "tour_adaptive"), ("ppo_A4", run / "ppo_A4"),
              ("data_greedy", run / "data_greedy"),
              ("q_learning", results / "qlearning_phase3_eval" / "n100" / "s3" / "q_learning")]
    fig, axes = plt.subplots(1, 4, figsize=(7.16, 2.0))
    t0, t1 = 1800.0, 3000.0
    for ax, (key, path) in zip(axes, panels):
        v = pd.read_csv(path / "visits.csv")
        v = v[(v.depart_s >= t0) & (v.depart_s < t1)]
        xy = meet.loc[v.cluster_id].to_numpy()
        name, color, _ = STYLE[key]
        ax.scatter(nodes.x, nodes.y, s=1.5, color="#b5b5b5", zorder=1)
        ax.scatter(meet.meet_x, meet.meet_y, s=10, facecolors="white", edgecolors="#444444",
                   linewidths=0.6, zorder=3)
        ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=1.0, zorder=2)
        m = __import__("json").loads((path / "metrics.json").read_text())
        ax.set_title(name, fontweight="bold")
        ax.set_xlabel(f"PDR {m['data']['pdr']:.2f} · on time {m['wake']['meeting_success_rate'] * 100:.0f}%\n"
                      f"{len(v)} visits in 20 min", fontsize=6.5)
        ax.set_xlim(-10, 510)
        ax.set_ylim(-10, 510)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(True)
            s.set_color("#999999")
    fig.savefig(OUT / "routes.pdf")
    plt.close(fig)


def ch_sweep(results: Path) -> None:
    """Fig. 3: PDR and UAV energy per delivered reading against the number of clusters."""
    frames = []
    for t in ["05", "10", "15", "20"]:
        for exp in (f"phase3_ch_sweep_{t}", f"qlearning_phase3_ch_sweep_{t}"):
            d = pd.read_csv(results / exp / "runs.csv")
            frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["jpr"] = (d["uav.flight_energy_J_est"] + d["uav.hover_energy_J_est"]) / d["data.delivered"]
    # x position of a setting: median cluster count of its 10 networks (as in Prakruthi's plots)
    d["setting"] = d["run.topology_dir"].str.extract(r"(ch_sweep_\d\d)")[0]
    xpos = d[d.variant == "tour"].groupby("setting")["run.num_clusters"].median()
    d["x"] = d["setting"].map(xpos)
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.75))
    for ax, (col, scale, ylabel) in zip(axes, [("data.pdr", 100, "PDR (%)"),
                                               ("jpr", 1, "UAV J per reading")]):
        for key, (name, color, marker) in STYLE.items():
            g = d[d.variant == key].groupby("x")[col]
            if g.ngroups == 0:
                continue
            m, c = g.mean() * scale, g.apply(ci95) * scale
            # the tour is drawn wider and dashed underneath, since PPO A4 lies almost on top of it
            tour = key == "tour"
            ax.errorbar(m.index, m.values, yerr=c.values, color=color, marker=marker,
                        markersize=5 if tour else 3.5, capsize=1.5, elinewidth=0.7, label=name,
                        linewidth=2.6 if tour else 1.4, linestyle="--" if tour else "-",
                        zorder=2 if tour else 3)
        ax.set_xlabel("Clusters (median)")
        ax.set_ylabel(ylabel)
        ax.set_xticks(sorted(d["x"].dropna().unique()))
    axes[0].set_ylim(20, 102)
    axes[1].set_ylim(1, 6.5)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.2), frameon=False)
    fig.tight_layout(w_pad=1.0)
    fig.savefig(OUT / "ch_sweep.pdf")
    plt.close(fig)


def uav_delay(phase4: Path) -> None:
    """Fig. 4: meetings kept and CH energy as more UAV legs are delayed (tour, adaptive window)."""
    d = pd.read_csv(phase4 / "phase4_uav_delay" / "runs.csv")
    frac = {"delay_0": 0, "delay_01": 10, "delay_025": 25, "delay_05": 50, "delay_1": 100}
    d["x"] = d["variant"].map(frac)
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.45))
    for ax, (col, scale, ylabel) in zip(axes, [("wake.meeting_success_rate", 100, "On time (%)"),
                                               ("energy.primary_ch_mean_J", 1, "CH energy (J)")]):
        g = d.groupby("x")[col]
        m, c = g.mean() * scale, g.apply(ci95) * scale
        ax.errorbar(m.index, m.values, yerr=c.values, color=STYLE["tour"][1], marker="o",
                    markersize=3.5, capsize=1.5, elinewidth=0.7)
        ax.set_xlabel("Delayed legs (%)")
        ax.set_ylabel(ylabel)
        ax.set_xticks([0, 25, 50, 100])
    fig.tight_layout(w_pad=1.0)
    fig.savefig(OUT / "uav_delay.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--phase4", type=Path, required=True)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    routes(a.results)
    ch_sweep(a.results)
    uav_delay(a.phase4)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
