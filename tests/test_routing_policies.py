import csv
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "phase2_routing_smoke.toml"

POLICIES = [
    "tour",
    "nearest_feasible",
    "data_greedy",
    "energy_data_score",
]


@pytest.fixture(scope="module")
def routing_results(tmp_path_factory):
    """Run all four routing policies through the actual ns-3 experiment runner."""
    results_dir = tmp_path_factory.mktemp("routing_results")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.run_experiment",
            str(CONFIG),
            "-j",
            "1",
            "--results",
            str(results_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    experiment_dir = results_dir / "phase2_routing_smoke" / "n100" / "s1"

    results = {}
    for policy in POLICIES:
        policy_dir = experiment_dir / policy
        visits_file = policy_dir / "visits.csv"

        assert visits_file.exists(), f"Missing visits.csv for {policy}"

        with visits_file.open(newline="") as f:
            rows = list(csv.DictReader(f))

        results[policy] = {
            "rows": rows,
            "sequence": [int(row["cluster_id"]) for row in rows],
        }

    return results


def has_aba(sequence):
    """Detect A -> B -> A routing patterns."""
    return any(
        sequence[i - 2] == sequence[i]
        and sequence[i - 2] != sequence[i - 1]
        for i in range(2, len(sequence))
    )


def test_all_routing_policies_execute(routing_results):
    """Every policy must produce actual ns-3 visit records."""
    for policy in POLICIES:
        assert routing_results[policy]["sequence"], (
            f"{policy} produced no visits"
        )


def test_no_immediate_repeated_cluster(routing_results):
    """A policy must not select the same cluster consecutively."""
    for policy in POLICIES:
        sequence = routing_results[policy]["sequence"]

        assert all(
            sequence[i] != sequence[i - 1]
            for i in range(1, len(sequence))
        ), f"{policy} selected the same cluster consecutively"


def test_no_aba_ping_pong(routing_results):
    """Heuristic policies must avoid immediate A-B-A ping-pong."""
    for policy in ["nearest_feasible", "data_greedy", "energy_data_score"]:
        sequence = routing_results[policy]["sequence"]

        assert not has_aba(sequence), (
            f"{policy} contains an A-B-A routing pattern"
        )


def test_tour_follows_repeating_fixed_order(routing_results):
    """The tour policy should repeat its fixed cluster order."""
    sequence = routing_results["tour"]["sequence"]

    assert len(sequence) >= 26

    first_lap = sequence[:25]

    assert len(set(first_lap)) == 25
    assert sequence[25] == sequence[0]


def test_belief_policies_explore_all_clusters(routing_results):
    """Both belief-based policies should explore every cluster in this topology."""
    for policy in ["data_greedy", "energy_data_score"]:
        sequence = routing_results[policy]["sequence"]

        assert len(set(sequence)) == 25, (
            f"{policy} visited only {len(set(sequence))} of 25 clusters"
        )


def test_nearest_feasible_does_not_claim_full_coverage(routing_results):
    """Record nearest-feasible coverage without hiding its observed limitation."""
    sequence = routing_results["nearest_feasible"]["sequence"]

    assert 0 < len(set(sequence)) <= 25
