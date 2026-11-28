"""Build the Phase 3 demo page (demo/phase3/index.html) from the Phase 3 results.

The page replays a mission for the ETA-aware tour, ER-PPO (A4), plain PPO (A1), nearest
feasible, data greedy and the Q-learning baseline, on any of the deployments below and any of
their 10 held-out networks (picked from two menus on the page; network 3 first), and charts the
10-network results of the uniform evaluation. Everything it
shows comes from results/, so run the experiments first:

    python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
    python3 -m analysis.aggregate results/phase3_eval/runs.csv
    python3 -m experiments.run_experiment configs/phase3_gaussian_scaling.toml -j 8
    for t in 05 10 15 20; do python3 -m experiments.run_experiment configs/phase3_ch_sweep_$t.toml -j 8; done
    python3 -m experiments.run_experiment configs/phase3_bursts_eval.toml -j 8
    for f in configs/qlearning/*.toml; do python3 -m experiments.run_experiment $f -j 8; done
    python3 demo/phase3/build.py

A deployment whose results are missing is left out of the menu.

View it with  python3 -m http.server 8000 --directory demo/phase3  and open
http://localhost:8000 (or open index.html directly). The tables of training fixes and
red-team checks are typed into template.html from docs/handoff/phase3.md §4 and §6.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd
from latex2mathml.converter import convert as latex_to_mathml
from scipy import stats

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "results"
SEED = 3                 # network shown first
SEEDS = range(1, 11)     # every held-out network of each deployment
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
    ("phase3_ch_sweep_05", 1000, "CH sweep · target 6 clusters", "3 Gaussian hotspots, clusters capped at 300 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_10", 1000, "CH sweep · target 10 clusters", "5 Gaussian hotspots, clusters capped at 150 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_15", 1000, "CH sweep · target 15 clusters", "5 Gaussian hotspots, clusters capped at 100 sensors", SIR_EXACT, "tour"),
    ("phase3_ch_sweep_20", 1000, "CH sweep · target 20 clusters", "15 Gaussian hotspots, clusters capped at 75 sensors", SIR_EXACT, "tour"),
    ("phase3_bursts_eval", 100, "Event bursts · 100 sensors",
     "uniform random, 4 bursts per hour (one cluster reads 20× faster for 30 min)",
     SIR_EXACT + ", cluster-head failures", "tour", "ppo_A4P_bursts", "PPO A4P (trained on bursts)"),
]


def deployment(exp: str, n: int, label: str, layout: str, noise: str, tour: str,
               ppo: str = "ppo_A4", ppo_name: str = "ER-PPO (A4)") -> dict | None:
    if not (RESULTS / exp / "runs.csv").exists():
        return None
    d = {"label": label, "layout": layout, "noise": noise, "sensors": n,
         "ppoName": ppo_name, "networks": [], "mean": {}}
    # (page key, experiment folder, variant). Q-learning runs live in their own folder
    # (configs/qlearning/), on the same networks; a policy without results is left off the page.
    policies = [("tour", exp, tour), ("ppo_A4", exp, ppo), ("ppo_A1", exp, "ppo_A1"),
                ("nearest_feasible", exp, "nearest_feasible"),
                ("data_greedy", exp, "data_greedy"), ("q_learning", f"qlearning_{exp}", "q_learning")]
    policies = [p for p in policies if (RESULTS / p[1] / "runs.csv").exists()]
    for seed in SEEDS:
        run = RESULTS / exp / f"n{n}" / f"s{seed}"
        if not (run / "topology").exists():
            continue
        clusters = list(csv.DictReader(open(run / "topology" / "clusters.csv")))
        nodes = list(csv.DictReader(open(run / "topology" / "nodes.csv")))
        net = {"seed": seed,
               "clusters": [[round(float(c["meet_x"]), 1), round(float(c["meet_y"]), 1)] for c in clusters],
               "nodes": [[round(float(x["x"])), round(float(x["y"]))] for x in nodes],
               "runs": {}}
        for key, e, v in policies:
            pr = RESULTS / e / f"n{n}" / f"s{seed}" / v
            if not (pr / "metrics.json").exists():
                continue
            m = json.loads((pr / "metrics.json").read_text())
            visits = [[int(r["cluster_id"]), round(float(r["depart_s"])), round(float(r["arrive_s"])),
                       round(float(r["end_s"])), int(float(r["readings"]))]
                      for r in csv.DictReader(open(pr / "visits.csv"))]
            net["runs"][key] = {"visits": visits, "pdr": m["data"]["pdr"],
                                "ontime": m["wake"]["meeting_success_rate"],
                                "chJ": m["energy"]["primary_ch_mean_J"]}
        d["networks"].append(net)
    # Mean over all network seeds of this deployment, for the line under the maps.
    for key, e, v in policies:
        runs = pd.read_csv(RESULTS / e / "runs.csv")
        runs = runs[(runs["run.num_sensors"] == n) & (runs.variant == v)]
        if runs.empty:
            continue
        d["seeds"] = int(runs["run.seed"].nunique())
        d["mean"][key] = {"pdr": float(runs["data.pdr"].mean()),
                          "ontime": float(runs["wake.meeting_success_rate"].mean())}
    return d


def ci95(x: pd.Series) -> float:
    """Half-width of the 95 % confidence interval of the mean (t distribution)."""
    return float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / len(x) ** 0.5)


def page_data() -> dict:
    deps = [d for d in (deployment(*x) for x in DEPLOYMENTS) if d]
    summary = {r["variant"]: r for r in csv.DictReader(open(RESULTS / "phase3_eval" / "summary.csv"))
               if r["num_sensors"] == "100"}
    summary = {v: {k: [float(r[k + ".mean"]), float(r[k + ".ci95"])] for k in METRICS}
               for v, r in summary.items()}
    # Q-learning baseline on the same 10 networks (configs/qlearning/phase3_eval.toml).
    q = RESULTS / "qlearning_phase3_eval" / "runs.csv"
    if q.exists():
        runs = pd.read_csv(q)
        summary["q_learning"] = {k: [float(runs[k].mean()), ci95(runs[k])] for k in METRICS}
    return {"seed": SEED, "deployments": deps, "summary": summary}


def render_math(page: str) -> str:
    """<tex>...</tex> (inline) and <tex-block>...</tex-block> (display) hold LaTeX; replace them with
    MathML, which browsers draw natively, so the page needs no maths library or internet."""
    page = re.sub(r"<tex-block>(.*?)</tex-block>",
                  lambda m: latex_to_mathml(m.group(1).strip(), display="block"), page, flags=re.S)
    return re.sub(r"<tex>(.*?)</tex>", lambda m: latex_to_mathml(m.group(1)), page, flags=re.S)


def main() -> None:
    page = render_math((HERE / "template.html").read_text())
    page = page.replace("__DATA__", json.dumps(page_data(), separators=(",", ":")))
    (HERE / "index.html").write_text(page)
    print(f"wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
