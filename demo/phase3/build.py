"""Build the Phase 3 demo page (demo/phase3/index.html) from the Phase 3 results.

The page replays one mission (network seed 3) for the ETA-aware tour, ER-PPO (A4) and data
greedy, on any of the deployments below (picked from a menu on the page), and charts the
10-network results of the uniform evaluation. Everything it shows comes from results/, so run
the experiments first:

    python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
    python3 -m analysis.aggregate results/phase3_eval/runs.csv
    python3 -m experiments.run_experiment configs/phase3_gaussian_scaling.toml -j 8
    for t in 05 10 15 20; do python3 -m experiments.run_experiment configs/phase3_ch_sweep_$t.toml -j 8; done
    python3 demo/phase3/build.py

A deployment whose results are missing is left out of the menu.

View it with  python3 -m http.server 8000 --directory demo/phase3  and open
http://localhost:8000 (or open index.html directly). The tables of training fixes and
red-team checks are typed into template.html from docs/handoff/phase3.md §4 and §6.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "results"
SEED = 3
METRICS = ["data.pdr", "wake.meeting_success_rate", "energy.primary_ch_mean_J"]

STRESS = "speed std 1 m/s, 10 % of flight legs delayed by 10–30 s, random cluster-head failures"
SIR_EXACT = "speed uniform 9–11 m/s per leg, no extra delays (sir's setting)"
# (experiment, num_sensors, menu label, deployment text, noise text, tour variant name[, PPO
#  variant, PPO display name]; PPO defaults to ppo_A4)
DEPLOYMENTS = [
    ("phase3_eval", 100, "Uniform · 100 sensors", "uniform random", STRESS, "tour_adaptive"),
    ("phase3_gaussian_scaling", 100, "Gaussian hotspots · 100 sensors", "4 Gaussian hotspots",
     SIR_EXACT + ", cluster-head failures", "tour"),
    ("phase3_gaussian_scaling", 1000, "Gaussian hotspots · 1000 sensors", "4 Gaussian hotspots",
     SIR_EXACT + ", cluster-head failures", "tour"),
    ("phase3_gaussian_scaling", 2000, "Gaussian hotspots · 2000 sensors", "4 Gaussian hotspots",
     SIR_EXACT + ", cluster-head failures", "tour"),
    ("phase3_ch_sweep_05", 1000, "CH sweep · about 6 clusters", "3 Gaussian hotspots, clusters capped at 300 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_10", 1000, "CH sweep · about 10 clusters", "5 Gaussian hotspots, clusters capped at 150 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_15", 1000, "CH sweep · about 15 clusters", "5 Gaussian hotspots, clusters capped at 100 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_20", 1000, "CH sweep · about 20 clusters", "15 Gaussian hotspots, clusters capped at 75 sensors", SIR_EXACT, "tour"),
    ("phase3_bursts_eval", 100, "Event bursts · 100 sensors",
     "uniform random, 4 bursts per hour (one cluster reads 20× faster for 30 min)",
     SIR_EXACT + ", cluster-head failures", "tour", "ppo_A4P_bursts", "PPO A4P (trained on bursts)"),
]


def deployment(exp: str, n: int, label: str, layout: str, noise: str, tour: str,
               ppo: str = "ppo_A4", ppo_name: str = "ER-PPO (A4)") -> dict | None:
    run = RESULTS / exp / f"n{n}" / f"s{SEED}"
    if not run.exists():
        return None
    clusters = list(csv.DictReader(open(run / "topology" / "clusters.csv")))
    nodes = list(csv.DictReader(open(run / "topology" / "nodes.csv")))
    d = {
        "label": label, "layout": layout, "noise": noise, "sensors": n, "ppoName": ppo_name,
        "clusters": [[round(float(c["meet_x"]), 1), round(float(c["meet_y"]), 1)] for c in clusters],
        "nodes": [[round(float(x["x"]), 1), round(float(x["y"]), 1)] for x in nodes],
        "runs": {},
    }
    for key, v in [("tour", tour), ("ppo_A4", ppo), ("data_greedy", "data_greedy")]:
        m = json.loads((run / v / "metrics.json").read_text())
        visits = [[int(r["cluster_id"]), round(float(r["depart_s"]), 1), round(float(r["arrive_s"]), 1),
                   round(float(r["end_s"]), 1), int(float(r["readings"]))]
                  for r in csv.DictReader(open(run / v / "visits.csv"))]
        d["runs"][key] = {"visits": visits, "pdr": m["data"]["pdr"],
                          "ontime": m["wake"]["meeting_success_rate"],
                          "chJ": m["energy"]["primary_ch_mean_J"]}
    # Mean over all 10 network seeds of this deployment, for the line under the maps.
    runs = pd.read_csv(RESULTS / exp / "runs.csv")
    runs = runs[runs["run.num_sensors"] == n]
    d["seeds"] = int(runs["run.seed"].nunique())
    d["mean"] = {key: {"pdr": float(runs.loc[runs.variant == v, "data.pdr"].mean()),
                       "ontime": float(runs.loc[runs.variant == v, "wake.meeting_success_rate"].mean())}
                 for key, v in [("tour", tour), ("ppo_A4", ppo), ("data_greedy", "data_greedy")]}
    return d


def page_data() -> dict:
    deps = [d for d in (deployment(*x) for x in DEPLOYMENTS) if d]
    summary = {r["variant"]: r for r in csv.DictReader(open(RESULTS / "phase3_eval" / "summary.csv"))
               if r["num_sensors"] == "100"}
    return {
        "seed": SEED,
        "deployments": deps,
        "summary": {v: {k: [float(r[k + ".mean"]), float(r[k + ".ci95"])] for k in METRICS}
                    for v, r in summary.items()},
    }


def main() -> None:
    page = (HERE / "template.html").read_text()
    page = page.replace("__DATA__", json.dumps(page_data(), separators=(",", ":")))
    (HERE / "index.html").write_text(page)
    print(f"wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
