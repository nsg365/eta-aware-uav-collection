#!/usr/bin/env python3
"""Validate Phase 4 matched-ablation TOML configs from the repository root."""
from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

CONFIGS = [
    "configs/a7_matched_multiseed.toml",
    "configs/a8_matched_multiseed.toml",
    "configs/a9_matched_multiseed.toml",
    "configs/phase4_wake_modes_multiseed.toml",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.repo_root.resolve()

    total_runs = 0
    for name in CONFIGS:
        path = root / name
        with path.open("rb") as f:
            cfg = tomllib.load(f)
        exp = cfg["experiment"]
        variants = cfg["variant"]
        assert exp["num_sensors"] == [60, 100, 150], (name, exp["num_sensors"])
        assert exp["seeds"] == list(range(1, 11)), (name, exp["seeds"])
        assert len(variants) in (2, 3), (name, len(variants))
        expected = len(exp["num_sensors"]) * len(exp["seeds"]) * len(variants)

        if name.endswith("a7_matched_multiseed.toml"):
            assert variants[0]["enableBackupCH"] is False
            assert variants[1]["enableBackupCH"] is True
            assert cfg["simulation"]["failoverOnMissedMeeting"] is False
        elif name.endswith("a8_matched_multiseed.toml"):
            assert variants[0]["failoverOnMissedMeeting"] is True
            assert variants[1]["failoverOnMissedMeeting"] is False
        elif name.endswith("a9_matched_multiseed.toml"):
            assert variants[0]["enableSurveyLap"] is False
            assert variants[1]["enableSurveyLap"] is True
            assert variants[0]["model"] == variants[1]["model"]
            model = root / variants[0]["model"]
            if not model.is_file():
                raise FileNotFoundError(f"A9 PPO checkpoint is missing: {model}")

        total_runs += expected
        print(f"OK {name}: {expected} runs ({len(variants)} variants x 3 sizes x 10 seeds)")

    print(f"\nValidated {len(CONFIGS)} configs: {total_runs} total runs.")


if __name__ == "__main__":
    main()
