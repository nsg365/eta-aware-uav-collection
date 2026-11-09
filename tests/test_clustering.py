import numpy as np
import pytest

from clustering.topology import TopologyParams, build_topology, feasible_candidates, generate_positions


@pytest.fixture(params=[(60, 1), (100, 2), (150, 3)])
def topo(request):
    n, seed = request.param
    p = TopologyParams(num_sensors=n, seed=seed, sensor_range_m=80.0)
    return p, *build_topology(p)


def test_every_sensor_in_exactly_one_cluster(topo):
    p, pos, clusters, order, diag = topo
    members = np.concatenate([c.members for c in clusters])
    assert sorted(members.tolist()) == list(range(p.num_sensors))


def test_meeting_point_is_centroid(topo):
    _, pos, clusters, *_ = topo
    for c in clusters:
        assert np.allclose(c.meet, pos[c.members].mean(axis=0))


def test_primary_and_backup_are_feasible_and_distinct(topo):
    p, pos, clusters, *_ = topo
    for c in clusters:
        feasible = set(feasible_candidates(pos, c.members, c.meet, p).tolist())
        assert c.primary in feasible
        if len(c.members) >= p.min_candidates:
            assert c.backup in feasible and c.backup != c.primary
        # Eq. (2): the primary reaches every member and is UAV-reachable from p_k.
        assert np.linalg.norm(pos[c.members] - pos[c.primary], axis=1).max() <= p.sensor_range_m
        assert np.linalg.norm(pos[c.primary] - c.meet) <= p.uav_range_m


def test_initial_election_prefers_closest_to_meeting_point(topo):
    # With equal (full) batteries, eq. (3) reduces to distance to p_k.
    p, pos, clusters, *_ = topo
    for c in clusters:
        cand = feasible_candidates(pos, c.members, c.meet, p)
        d = np.linalg.norm(pos[cand] - c.meet, axis=1)
        assert np.isclose(np.linalg.norm(pos[c.primary] - c.meet), d.min())


def test_tour_visits_each_cluster_once(topo):
    _, _, clusters, order, _ = topo
    assert sorted(order) == list(range(len(clusters)))


def test_deterministic_for_seed():
    p = TopologyParams(num_sensors=80, seed=7)
    a, b = build_topology(p), build_topology(p)
    assert np.array_equal(a[0], b[0])
    assert [c.primary for c in a[1]] == [c.primary for c in b[1]]
    assert a[2] == b[2]

def test_gaussian_hotspot_positions_are_deterministic():
    p = TopologyParams(
        num_sensors=100,
        seed=42,
        deployment_mode="gaussian_hotspot",
        hotspot_count=4,
        hotspot_std_m=25.0,
    )

    a = generate_positions(p)
    b = generate_positions(p)

    assert np.array_equal(a, b)


def test_gaussian_hotspot_positions_within_area():
    p = TopologyParams(
        num_sensors=100,
        seed=42,
        area_m=500.0,
        deployment_mode="gaussian_hotspot",
    )

    pos = generate_positions(p)

    assert pos.shape == (100, 2)
    assert np.all(pos >= 0.0)
    assert np.all(pos <= 500.0)


def test_gaussian_hotspot_topology_builds():
    p = TopologyParams(
        num_sensors=100,
        seed=42,
        sensor_range_m=80.0,
        deployment_mode="gaussian_hotspot",
        hotspot_count=4,
        hotspot_std_m=25.0,
    )

    pos, clusters, order, diag = build_topology(p)

    members = np.concatenate([c.members for c in clusters])

    assert sorted(members.tolist()) == list(range(100))
    assert sorted(order) == list(range(len(clusters)))