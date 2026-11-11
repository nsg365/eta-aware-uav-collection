"""Build the Phase 3 demo page (demo/phase3/index.html) from the Phase 3 evaluation.

The page replays one held-out mission (network 3) for the ETA-aware tour, ER-PPO (A4) and data
greedy, and charts the 10-network results. Everything it shows comes from
results/phase3_eval, so run the evaluation first:

    python3 -m experiments.run_experiment configs/phase3_eval.toml -j 8
    python3 -m analysis.aggregate results/phase3_eval/runs.csv
    python3 demo/phase3/build.py

View it with  python3 -m http.server 8000 --directory demo/phase3  and open
http://localhost:8000 (or open index.html directly). The tables of training fixes and
red-team checks are typed into template.html from docs/handoff/phase3.md §4 and §6.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "results" / "phase3_eval"
SEED = 3
POLICIES = ["tour_adaptive", "ppo_A4", "data_greedy"]
METRICS = ["data.pdr", "wake.meeting_success_rate", "energy.primary_ch_mean_J"]


def page_data() -> dict:
    run = RESULTS / "n100" / f"s{SEED}"
    clusters = list(csv.DictReader(open(run / "topology" / "clusters.csv")))
    nodes = list(csv.DictReader(open(run / "topology" / "nodes.csv")))
    data = {
        "clusters": [[round(float(c["meet_x"]), 1), round(float(c["meet_y"]), 1)] for c in clusters],
        "nodes": [[round(float(n["x"]), 1), round(float(n["y"]), 1)] for n in nodes],
        "runs": {},
    }
    for v in POLICIES:
        m = json.loads((run / v / "metrics.json").read_text())
        visits = [[int(r["cluster_id"]), round(float(r["depart_s"]), 1), round(float(r["arrive_s"]), 1),
                   round(float(r["end_s"]), 1), int(float(r["readings"]))]
                  for r in csv.DictReader(open(run / v / "visits.csv"))]
        data["runs"][v] = {"visits": visits, "pdr": m["data"]["pdr"],
                           "ontime": m["wake"]["meeting_success_rate"],
                           "chJ": m["energy"]["primary_ch_mean_J"]}
    summary = {r["variant"]: r for r in csv.DictReader(open(RESULTS / "summary.csv"))
               if r["num_sensors"] == "100"}
    data["summary"] = {v: {k: [float(r[k + ".mean"]), float(r[k + ".ci95"])] for k in METRICS}
                       for v, r in summary.items()}
    return data


def main() -> None:
    page = (HERE / "template.html").read_text()
    page = page.replace("__DATA__", json.dumps(page_data(), separators=(",", ":")))
    (HERE / "index.html").write_text(page)
    print(f"wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
