"""Integration tests: run the ns-3 program on a small topology. Skipped if it is not built."""

import json
import subprocess

import pytest

from clustering.topology import TopologyParams, build_topology, write_topology
from experiments.run_experiment import ns3_binary

pytestmark = pytest.mark.skipif(not ns3_binary().exists(),
                                reason="ns-3 program not built (see docs/SETUP.md)")

SIM_TIME = 900.0


@pytest.fixture(scope="module")
def topology(tmp_path_factory):
    d = tmp_path_factory.mktemp("topo")
    p = TopologyParams(num_sensors=40, seed=3, sensor_range_m=80.0)
    write_topology(d, p, *build_topology(p))
    return d


def run(topology, out, **kw):
    args = {"topologyDir": topology, "outDir": out, "simTime": SIM_TIME, **kw}
    subprocess.run([str(ns3_binary())] + [f"--{k}={v}" for k, v in args.items()],
                   check=True, capture_output=True)
    return json.loads((out / "metrics.json").read_text())


@pytest.mark.parametrize("mode", ["always_on", "duty_cycle", "scheduled"])
def test_readings_are_conserved(topology, tmp_path, mode):
    d = run(topology, tmp_path, wakeMode=mode)["data"]
    accounted = (d["delivered"] + d["overflow"] + d["lost_154"] + d["lost_wifi"]
                 + d["lost_ch_dead"] + d["in_buffer_at_end"])
    assert d["generated"] > 0
    assert d["generated"] == accounted


def test_always_on_wifi_energy_matches_idle_power(topology, tmp_path):
    # Regression guard for D2: the ns-3 radio model must not stop accounting part-way.
    # Large E0 so no CH dies; CH Wi-Fi energy >= idle floor I_idle * V * T.
    m = run(topology, tmp_path, wakeMode="always_on", initialEnergy=4000, simTime=1500)
    k = m["run"]["num_clusters"]
    floor = 0.10 * 3.0 * 1500 * k
    assert floor <= m["energy"]["wifi_total_J"] <= 1.05 * floor


def test_scheduled_mode_sleeps_and_meets(topology, tmp_path):
    m = run(topology, tmp_path, wakeMode="scheduled")
    assert m["wake"]["meeting_success_rate"] > 0.9
    assert m["wake"]["ch_wifi_awake_fraction"] < 0.1


def test_same_seed_is_deterministic(topology, tmp_path):
    a = run(topology, tmp_path / "a", wakeMode="scheduled", seed=5)
    b = run(topology, tmp_path / "b", wakeMode="scheduled", seed=5)
    for m in (a, b):
        m["run"].pop("wall_time_s")
        m["run"].pop("topology_dir")
    assert a == b
