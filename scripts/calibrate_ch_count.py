#!/usr/bin/env python3
"""Calibrate (hotspot_count, max_cluster_size) combos that produce target cluster counts.

Runs topology-only (no ns-3) across a grid of topology parameters with multiple seeds,
records the resulting number of clusters, and recommends the best params for each target.

Output:
  configs/ch_sweep_params.json  –  machine-readable lookup table for run_ch_sweep.py

Usage:
  python3 scripts/calibrate_ch_count.py
  python3 scripts/calibrate_ch_count.py --targets 5 10 15 20 --seeds 1 2 3 4 5

After this, review the printed table and run:
  python3 scripts/run_ch_sweep.py --targets 5 10   (person 1)
  python3 scripts/run_ch_sweep.py --targets 15 20  (person 2)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Repo root on sys.path so we can import clustering.*
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from clustering.topology import TopologyParams, build_topology  # noqa: E402

# ---------------------------------------------------------------------------
# Base topology params – kept consistent with phase2_gaussian_speed_jitter_p010.toml
# (1000 sensors, 500 m area, same DBSCAN/UAV range settings)
# ---------------------------------------------------------------------------
BASE_PARAMS: dict = dict(
    num_sensors=1000,
    area_m=500.0,
    sensor_range_m=80.0,
    dbscan_kappa=0.8,
    dbscan_min_samples=3,
    uav_range_m=30.0,
    alpha=0.5,
    min_candidates=2,
    depot_x=0.0,
    depot_y=0.0,
    deployment_mode="gaussian_hotspot",
    hotspot_std_m=25.0,
)

# Grid to sweep:  hotspot_count × max_cluster_size
HOTSPOT_COUNTS: list[int] = [2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20]
MAX_CLUSTER_SIZES: list[int | None] = [50, 75, 100, 150, 200, 300, None]


# ---------------------------------------------------------------------------
# Core calibration logic
# ---------------------------------------------------------------------------

def run_single(hc: int, mcs: int | None, seed: int) -> int | None:
    """Build one topology and return num_clusters, or None on error."""
    p = TopologyParams(
        **BASE_PARAMS,
        seed=seed,
        hotspot_count=hc,
        max_cluster_size=mcs,
    )
    try:
        _, _, _, diag = build_topology(p)
        return int(diag["num_clusters"])
    except Exception as exc:
        print(f"  WARNING: hc={hc} mcs={mcs} seed={seed} → {exc}", file=sys.stderr)
        return None


def run_grid(seeds: list[int]) -> list[dict]:
    """Sweep the full (hotspot_count, max_cluster_size, seed) grid."""
    total = len(HOTSPOT_COUNTS) * len(MAX_CLUSTER_SIZES) * len(seeds)
    done = 0
    results: list[dict] = []

    print(f"Sweeping {len(HOTSPOT_COUNTS)} hotspot counts × "
          f"{len(MAX_CLUSTER_SIZES)} max_cluster_size values × "
          f"{len(seeds)} seeds = {total} topology builds...")

    for hc in HOTSPOT_COUNTS:
        for mcs in MAX_CLUSTER_SIZES:
            per_seed: list[int | None] = []
            for seed in seeds:
                per_seed.append(run_single(hc, mcs, seed))
                done += 1
                if done % 25 == 0 or done == total:
                    print(f"  {done}/{total} done", flush=True)

            valid = [c for c in per_seed if c is not None]
            if not valid:
                continue

            results.append({
                "hotspot_count": hc,
                "max_cluster_size": mcs,
                "median_clusters": float(np.median(valid)),
                "mean_clusters": float(np.mean(valid)),
                "std_clusters": float(np.std(valid)),
                "min_clusters": int(np.min(valid)),
                "max_clusters": int(np.max(valid)),
                "per_seed": {str(s): c for s, c in zip(seeds, per_seed)},
            })

    return results


def find_best(results: list[dict], target: int) -> dict:
    """Return the combo whose median_clusters is closest to target.

    Tie-break: prefer lower std (more consistent across seeds).
    """
    return min(
        results,
        key=lambda r: (abs(r["median_clusters"] - target), r["std_clusters"]),
    )


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def _mcs_str(mcs: int | None) -> str:
    return "none" if mcs is None else str(mcs)


def print_grid_table(results: list[dict]) -> None:
    print()
    print("=" * 82)
    print("FULL CALIBRATION GRID  (sorted by median cluster count)")
    print("=" * 82)
    hdr = (f"{'hotspot_count':>14}  {'max_cluster_size':>16}  "
           f"{'median':>8}  {'mean':>8}  {'std':>6}  {'min':>5}  {'max':>5}")
    print(hdr)
    print("-" * 82)
    for r in sorted(results, key=lambda x: (x["median_clusters"], x["hotspot_count"])):
        print(f"{r['hotspot_count']:>14}  {_mcs_str(r['max_cluster_size']):>16}  "
              f"{r['median_clusters']:>8.1f}  {r['mean_clusters']:>8.1f}  "
              f"{r['std_clusters']:>6.2f}  "
              f"{r['min_clusters']:>5}  {r['max_clusters']:>5}")


def print_recommendations(mapping: dict[str, dict]) -> None:
    print()
    print("=" * 82)
    print("RECOMMENDED CONFIGS  (use these with run_ch_sweep.py)")
    print("=" * 82)
    for target_str, v in sorted(mapping.items(), key=lambda kv: int(kv[0])):
        mcs_s = _mcs_str(v["max_cluster_size"])
        print(f"  Target ~{int(target_str):>2} clusters  →  "
              f"hotspot_count={v['hotspot_count']},  max_cluster_size={mcs_s}"
              f"   (median={v['median_clusters']:.1f}  ±{v['std_clusters']:.2f})")
    print()
    print("Example commands:")
    print("  python3 scripts/run_ch_sweep.py --targets 5 10 -j 4   # person 1")
    print("  python3 scripts/run_ch_sweep.py --targets 15 20 -j 4  # person 2")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--targets", type=int, nargs="+", default=[5, 10, 15, 20],
        help="Target cluster counts to find configs for (default: 5 10 15 20)",
    )
    ap.add_argument(
        "--seeds", type=int, nargs="+", default=list(range(1, 11)),
        help="Seeds to use for calibration (default: 1–10)",
    )
    ap.add_argument(
        "--out", type=Path,
        default=REPO / "configs" / "ch_sweep_params.json",
        help="Where to write the calibration lookup table (JSON)",
    )
    a = ap.parse_args()

    results = run_grid(a.seeds)
    print_grid_table(results)

    mapping: dict[str, dict] = {}
    for target in sorted(a.targets):
        best = find_best(results, target)
        mapping[str(target)] = {
            "hotspot_count": best["hotspot_count"],
            "max_cluster_size": best["max_cluster_size"],
            "median_clusters": best["median_clusters"],
            "std_clusters": best["std_clusters"],
        }

    print_recommendations(mapping)

    out_data = {
        "_comment": (
            "Generated by calibrate_ch_count.py. "
            "Keys in 'targets' map desired cluster count → topology params."
        ),
        "base_params": BASE_PARAMS,
        "targets": mapping,
        "full_grid": results,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out_data, indent=2))
    print(f"Saved calibration data → {a.out}")


if __name__ == "__main__":
    main()
