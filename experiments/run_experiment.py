"""Run a grid of (network size x seed x variant) simulations from one TOML experiment file.

Every variant of a given (num_sensors, seed) cell uses the same topology and the same ns-3 run
number, so traffic and UAV speed noise are identical across variants (common random numbers).

Layout:  results/<experiment>/n<N>/s<seed>/topology/        (Phase 0 output, shared)
         results/<experiment>/n<N>/s<seed>/<variant>/       (metrics.json, per_*.csv, visits.csv)
         results/<experiment>/runs.csv                       (one flattened row per run)

Usage:   python3 -m experiments.run_experiment configs/example_wake_modes.toml [-j 4] [--build]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clustering.topology import TopologyParams, build_topology, write_topology

REPO = Path(__file__).resolve().parents[1]
DEFAULT_NS3 = REPO.parent / "ns3-workspace" / "ns-3.47"


def ns3_dir() -> Path:
    return Path(os.environ.get("NS3_DIR", DEFAULT_NS3)).resolve()


def ns3_binary() -> Path:
    """The built program; its suffix depends on the ns-3 build profile (default, debug, ...)."""
    folder = ns3_dir() / "build" / "scratch" / "wsn-uav"
    found = sorted(folder.glob("ns3.*-wsn-uav-*"))
    return found[0] if found else folder / "ns3.47-wsn-uav-default"


def build_ns3() -> None:
    subprocess.run([str(REPO / "scripts" / "link_ns3.sh"), str(ns3_dir())], check=True)
    subprocess.run(["./ns3", "build", "wsn-uav"], cwd=ns3_dir(), check=True)


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def sim_args(params: dict) -> list[str]:
    return [f"--{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in params.items()]


def run_one(job: dict) -> dict:
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_config.json").write_text(json.dumps(job, indent=2))
    extra = {}
    # if job["simulation"].get("routing") == "ppo":
    #     # A trained Phase 3 policy drives the UAV through routing/env.py.
    #     from routing.evaluate import run_ppo
    #     extra = {"ppo": run_ppo(job["simulation"]["model"], job["simulation"])}
    if job["simulation"].get("routing") in ("ppo", "q_learning"):
        from routing.evaluate import run_ppo
        extra = {
            "policy": run_ppo(
                job["simulation"]["model"],
                job["simulation"]
            )
        }
    else:
        cmd = [str(ns3_binary())] + sim_args(job["simulation"])
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        (out / "stdout.log").write_text(proc.stdout + proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"simulation failed ({proc.returncode}) in {out}; see stdout.log:\n"
                               + (proc.stdout + proc.stderr)[-2000:])
    metrics = json.loads((out / "metrics.json").read_text())
    return {"variant": job["variant"], "num_sensors_cfg": job["num_sensors"], "seed_cfg": job["seed"],
            **flatten(metrics), **flatten(extra)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--build", action="store_true", help="link and build the ns-3 program first")
    ap.add_argument("--results", type=Path, default=REPO / "results")
    a = ap.parse_args()

    with open(a.config, "rb") as f:
        cfg = tomllib.load(f)
    exp = cfg["experiment"]
    base_sim = cfg.get("simulation", {})
    variants = cfg.get("variant", [{"name": "default"}])

    if a.build:
        build_ns3()
    if not ns3_binary().exists():
        sys.exit(f"error: {ns3_binary()} not found. Build it with:\n"
                 f"  scripts/link_ns3.sh && (cd {ns3_dir()} && ./ns3 build wsn-uav)\n"
                 f"or rerun with --build. Set NS3_DIR if ns-3 lives elsewhere.")

    root = a.results / exp["name"]
    jobs = []
    for n in exp["num_sensors"]:
        for seed in exp["seeds"]:
            cell = root / f"n{n}" / f"s{seed}"
            topo = TopologyParams.from_toml(a.config, num_sensors=n, seed=seed)
            write_topology(cell / "topology", topo, *build_topology(topo))
            for v in variants:
                sim = {**base_sim, **{k: val for k, val in v.items() if k != "name"},
                       # Paths relative to the repo (the program runs with cwd=REPO), so
                       # outputs contain no machine-specific absolute paths.
                       "topologyDir": os.path.relpath(cell / "topology", REPO),
                       "outDir": os.path.relpath(cell / v["name"], REPO),
                       "seed": seed}
                jobs.append({"variant": v["name"], "num_sensors": n, "seed": seed,
                             "out": str(cell / v["name"]), "simulation": sim})

    print(f"{exp['name']}: {len(jobs)} runs ({len(exp['num_sensors'])} sizes x "
          f"{len(exp['seeds'])} seeds x {len(variants)} variants), {a.jobs} parallel")
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        rows = list(pool.map(run_one, jobs))

    fields = sorted({k for r in rows for k in r})
    with open(root / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {root / 'runs.csv'}")


if __name__ == "__main__":
    main()
