#!/usr/bin/env python3
"""Reproduce the complete Phase 4 experiment and analysis pipeline.

Default workflow:
  1. Validate tracked Phase 3 baselines, model logs, configs and scripts.
  2. Link/build ns-3.47 and run the test suite.
  3. Run the six original Phase 4 experiment groups and their analysis.
  4. Run A7, A8, A9 and the three-way wake-mode ablation.
  5. Regenerate paired ablation statistics, summaries and figures.

Use --analysis-only to regenerate analyses from existing run CSVs.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS3_DIR = Path(os.environ.get("NS3_DIR", ROOT.parent / "ns3-workspace" / "ns-3.47")).resolve()
PHASE4_RESULTS = ROOT / "results_phase4"
ABLATION_RESULTS = ROOT / "results_phase4_full_ablation"

ORIGINAL_CONFIGS = [
    "eta_multiseed",
    "phase4_network_sizes",
    "phase4_window_width",
    "phase4_uav_delay",
    "phase4_ch_failure",
    "phase4_clock_drift",
]
ABLATION_CONFIGS = [
    ("a7_matched_multiseed.toml", 4, 60),
    ("a8_matched_multiseed.toml", 4, 60),
    ("a9_matched_multiseed.toml", 2, 60),
    ("phase4_wake_modes_multiseed.toml", 4, 90),
]
EXPECTED_VARIANTS = {
    "a7_matched_multiseed": {"a7_no_backup", "backup_enabled_control"},
    "a8_matched_multiseed": {"a8_immediate_missed_meeting", "heartbeat_baseline"},
    "a9_matched_multiseed": {"a9_no_survey_lap", "a4_survey_lap_control"},
    "phase4_wake_modes_multiseed": {"a5_always_on", "a6_duty_cycle", "scheduled_wake_control"},
}
TRACKED_PREREQUISITES = [
    Path("results_phase4/phase3_eval/runs.csv"),
    Path("models/phase3_ppo/A1_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_ppo/A2_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_ppo/A3_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_ppo/A4_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_fixes/A_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_fixes/B_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_fixes/C_ppo-scoring_ws_train.monitor.csv"),
    Path("models/phase3_fixes/D_ppo-scoring_ws_train.monitor.csv"),
]
REQUIRED_MODULES = [
    "numpy", "scipy", "pandas", "sklearn", "matplotlib", "gymnasium",
    "stable_baselines3", "sb3_contrib", "torch",
]


def run(command: list[str | Path], *, cwd: Path = ROOT, dry_run: bool = False) -> None:
    printable = " ".join(str(x) for x in command)
    print(f"\n>>> {printable}", flush=True)
    if not dry_run:
        subprocess.run([str(x) for x in command], cwd=cwd, check=True)


def check_files() -> None:
    required = [ROOT / p for p in TRACKED_PREREQUISITES]
    required += [ROOT / "analysis/run_phase4.py", ROOT / "scripts/analyze_matched_ablations.py"]
    required += [ROOT / "scripts/validate_phase4_configs.py", ROOT / "requirements.txt"]
    required += [ROOT / "experiments/run_experiment.py"]
    required += [ROOT / "configs" / f"{name}.toml" for name in ORIGINAL_CONFIGS]
    required += [ROOT / "configs" / name for name, _, _ in ABLATION_CONFIGS]
    # PPO model weights used by Phase 3 policy evaluation are inputs, not outputs
    # of the Phase 4 simulations. Keep the expected artifacts explicit here.
    for name in ("A1", "A2", "A3", "A4"):
        required.append(ROOT / f"models/phase3_ppo/{name}_ppo-scoring_ws.zip")
        required.append(ROOT / f"models/phase3_ppo/{name}_ppo-scoring_ws.json")
    for name in ("A", "B", "C", "D"):
        required.append(ROOT / f"models/phase3_fixes/{name}_ppo-scoring_ws.zip")
        required.append(ROOT / f"models/phase3_fixes/{name}_ppo-scoring_ws.json")
    missing = [p.relative_to(ROOT) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Missing tracked prerequisites:\n" + "\n".join(f"  - {p}" for p in missing))


def check_python_modules() -> None:
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        raise SystemExit(
            "Missing Python packages: " + ", ".join(missing)
            + "\nActivate the project venv and run: pip install -r requirements.txt"
        )


def check_ns3(*, skip_build: bool, dry_run: bool) -> None:
    ns3 = NS3_DIR / "ns3"
    if not ns3.is_file():
        raise SystemExit(
            f"ns-3.47 not found at {NS3_DIR}. Follow docs/SETUP.md to install/configure ns-3.47, "
            "or set NS3_DIR to its location."
        )
    if skip_build:
        binary_dir = NS3_DIR / "build" / "scratch" / "wsn-uav"
        binaries = list(binary_dir.glob("ns3.*-wsn-uav-*"))
        if not binaries:
            raise SystemExit(f"No built wsn-uav binary found under {binary_dir}; rerun without --skip-build.")
        return
    run([ROOT / "scripts/link_ns3.sh", NS3_DIR], dry_run=dry_run)
    run(["./ns3", "build", "wsn-uav", "wsn-uav-range"], cwd=NS3_DIR, dry_run=dry_run)


def run_original_phase4(jobs: int, dry_run: bool) -> None:
    # --overwrite is intentional: a clean clone contains the seed baseline eta_multiseed/runs.csv.
    run([sys.executable, "analysis/run_phase4.py", "--run", "--overwrite", "-j", str(jobs)], dry_run=dry_run)


def run_ablations(dry_run: bool) -> None:
    for config, jobs, _expected_count in ABLATION_CONFIGS:
        run([
            sys.executable, "-m", "experiments.run_experiment",
            ROOT / "configs" / config,
            "-j", str(jobs),
            "--results", ABLATION_RESULTS,
        ], dry_run=dry_run)


def validate_ablation_csvs() -> None:
    for config, _jobs, expected_count in ABLATION_CONFIGS:
        folder = Path(config).stem
        path = ABLATION_RESULTS / folder / "runs.csv"
        if not path.is_file():
            raise SystemExit(f"Missing ablation output: {path.relative_to(ROOT)}")
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if len(rows) != expected_count:
            raise SystemExit(f"{path}: expected {expected_count} rows, found {len(rows)}")
        if not rows:
            raise SystemExit(f"{path}: CSV is empty")
        required = {"variant", "run.num_sensors", "run.seed"}
        if not required.issubset(rows[0]):
            raise SystemExit(f"{path}: missing required columns {sorted(required - set(rows[0]))}")
        cells = [(r["run.num_sensors"], r["run.seed"], r["variant"]) for r in rows]
        if len(cells) != len(set(cells)):
            raise SystemExit(f"{path}: duplicate (network size, seed, variant) cells")
        variants = {r["variant"] for r in rows}
        expected_variants = EXPECTED_VARIANTS[folder]
        if variants != expected_variants:
            raise SystemExit(f"{path}: expected variants {sorted(expected_variants)}, found {sorted(variants)}")
        print(f"OK {path.relative_to(ROOT)}: {len(rows)} rows, {len(variants)} variants, no duplicate cells")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=4, help="Parallel jobs for original Phase 4 experiments (default: 4)")
    ap.add_argument("--skip-build", action="store_true", help="Use an already-built ns-3.47 binary")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--analysis-only", action="store_true", help="Regenerate analyses from existing run CSVs")
    mode.add_argument("--preflight-only", action="store_true", help="Check tracked inputs and Python dependencies only")
    mode.add_argument("--dry-run", action="store_true", help="Print the full command sequence without executing it")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be at least 1")

    print("========== PHASE 4 REPRODUCTION PREFLIGHT ==========")
    check_files()
    check_python_modules()
    print("Tracked baselines, PPO logs/weights, configs, scripts and Python packages: OK")
    run([sys.executable, "scripts/validate_phase4_configs.py"], dry_run=args.dry_run)
    if args.preflight_only:
        return

    if args.analysis_only:
        run([sys.executable, "analysis/run_phase4.py", "--analysis-only" ])
        validate_ablation_csvs()
        run([sys.executable, "scripts/analyze_matched_ablations.py", "--root", ABLATION_RESULTS, "--expected-seeds", "10"])
        return

    if args.dry_run:
        print("\nDRY RUN: no build, tests or simulations will be executed.")
        check_ns3(skip_build=False, dry_run=True)
        run([sys.executable, "-m", "pytest", "-q"], dry_run=True)
        run_original_phase4(args.jobs, dry_run=True)
        run_ablations(dry_run=True)
        run([sys.executable, "scripts/analyze_matched_ablations.py", "--root", ABLATION_RESULTS, "--expected-seeds", "10"], dry_run=True)
        return

    check_ns3(skip_build=args.skip_build, dry_run=False)
    run([sys.executable, "-m", "pytest", "-q"])
    run_original_phase4(args.jobs, dry_run=False)
    run_ablations(dry_run=False)
    validate_ablation_csvs()
    run([sys.executable, "scripts/analyze_matched_ablations.py", "--root", ABLATION_RESULTS, "--expected-seeds", "10"])
    print("\n========== PHASE 4 REPRODUCTION COMPLETE ==========")
    print(f"Original Phase 4 results: {PHASE4_RESULTS}")
    print(f"Matched ablations and analysis: {ABLATION_RESULTS}")


if __name__ == "__main__":
    main()
