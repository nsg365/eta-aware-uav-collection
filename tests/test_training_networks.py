"""Training network mix (EnvSettings.networks, configs/phase3_ppo_sir.toml)."""

import csv

from clustering.topology import TopologyParams, generate_positions
from routing.env import EnvSettings, ensure_topology

NETWORKS = (
    {"name": "uniform_n60", "num_sensors": 60},
    {"name": "gauss_n120_h3", "num_sensors": 120, "deployment_mode": "gaussian_hotspot",
     "hotspot_count": 3},
)


def sensors(topo):
    with open(topo / "nodes.csv") as f:
        return sum(1 for _ in csv.DictReader(f))


def test_seed_picks_the_network_type(tmp_path):
    s = EnvSettings(seeds=[4, 5], networks=NETWORKS, cache=tmp_path)
    even, odd = ensure_topology(s, 4), ensure_topology(s, 5)
    assert even.parent.name == "uniform_n60" and sensors(even) == 60
    assert odd.parent.name == "gauss_n120_h3" and sensors(odd) == 120


def test_network_type_matches_a_direct_build(tmp_path):
    # a network type only overrides [topology] keys, so it is the same network as a direct build
    s = EnvSettings(seeds=[5], networks=NETWORKS, cache=tmp_path)
    topo = ensure_topology(s, 5)
    p = TopologyParams.from_toml(s.topology_config, num_sensors=120, seed=5,
                                 deployment_mode="gaussian_hotspot", hotspot_count=3)
    assert p.deployment_mode == "gaussian_hotspot"
    with open(topo / "nodes.csv") as f:
        first = next(csv.DictReader(f))
    x, y = generate_positions(p)[0]
    assert abs(float(first["x"]) - x) < 0.1 and abs(float(first["y"]) - y) < 0.1
