"""Phase 3 environment: the ns-3 bridge and the MDP of docs/MDP.md. Skipped if ns-3 is not built."""

import json
import subprocess

import numpy as np
import pytest

from experiments.run_experiment import ns3_binary
from routing.env import K_MAX, EnvSettings, WsnUavEnv

pytestmark = pytest.mark.skipif(not ns3_binary().exists(),
                                reason="ns-3 program not built (see docs/SETUP.md)")

SIM = {"simTime": 900.0, "uavDelayProb": 0.2, "uavDelayMin": 10, "uavDelayMax": 30}


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return EnvSettings(seeds=[3], num_sensors=40, simulation=SIM, risk_in_obs=True,
                       beta_r=0.5, cache=tmp_path_factory.mktemp("rl_cache"))


def tour_order(env):
    c = np.genfromtxt(env.topo / "clusters.csv", delimiter=",", names=True)
    order = np.empty(env.K, int)
    order[c["tour_index"].astype(int)] = c["cluster_id"].astype(int)
    return order


def test_bridge_reproduces_the_tour(settings, tmp_path):
    # Choosing the tour order through Python must give exactly the --routing=tour run. The
    # teacher used for warm starts (expert_action) must make the same choices.
    env = WsnUavEnv(settings, out_dir=tmp_path / "ext")
    env.reset(options={"seed": 3})
    order, i, done = tour_order(env), 0, False
    while not done:
        slot = int(np.flatnonzero(env.slot_cluster == order[i % env.K])[0])
        assert env.expert_action() == slot
        _, _, done, _, _ = env.step(slot)
        i += 1
    subprocess.run([str(ns3_binary()), f"--topologyDir={env.topo}", "--routing=tour", "--seed=3",
                    f"--outDir={tmp_path / 'tour'}"] + [f"--{k}={v}" for k, v in SIM.items()],
                   check=True, capture_output=True)
    a = json.loads((tmp_path / "ext" / "s3" / "metrics.json").read_text())
    b = json.loads((tmp_path / "tour" / "metrics.json").read_text())
    for key in ("data", "wake", "energy", "reliability"):
        assert a[key] == b[key], key


def test_observation_holds_only_last_contact_beliefs(settings):
    # No future or hidden information: between two decisions, a cluster the UAV did not visit
    # keeps its last-contact values, and only the clock-driven features move with elapsed time.
    env = WsnUavEnv(settings)
    obs, _ = env.reset(options={"seed": 3})
    rng = np.random.default_rng(0)
    checked, done = 0, False
    while not done:
        assert obs.shape == env.observation_space.shape and np.isfinite(obs).all()
        mask = env.action_masks()
        assert not mask[env.K:].any()                                 # padding
        assert env.last_msg["current"] not in env.slot_cluster[mask]  # no self-loop
        before = env.last_msg
        slot = rng.choice(np.flatnonzero(mask))
        visited = env.slot_cluster[slot]
        obs, _, done, _, _ = env.step(slot)
        if done:
            break
        after, dt = env.last_msg, env.last_msg["now"] - before["now"]
        for k in range(env.K):
            if k == visited:
                continue
            b, a = before["clusters"][k], after["clusters"][k]
            # rate, energy, missed meetings, never-contacted flag: unchanged
            assert np.allclose(a[[3, 4, 7, 8]], b[[3, 4, 7, 8]]), k
            if b[8] < 0.5:  # contacted before: age grows with the clock, buffer = rate * age
                assert a[5] == pytest.approx(b[5] + dt, abs=1e-3)
                assert a[2] == pytest.approx(a[3] * a[5], rel=1e-4, abs=1e-6)
            if b[6] >= 0:   # an outstanding promise is a fixed time
                assert a[6] == pytest.approx(b[6] - dt, abs=1e-3)
            checked += 1
    assert checked > 100


def test_padding_and_action_space(settings):
    env = WsnUavEnv(settings)
    obs, _ = env.reset(options={"seed": 3})
    assert env.action_space.n == K_MAX and env.K < K_MAX
    assert sorted(env.slot_cluster[:env.K]) == list(range(env.K))
    assert (env.slot_cluster[env.K:] == -1).all()
    with pytest.raises(ValueError):
        env.step(K_MAX - 1)
    env.close()


def test_chosen_promise_length_is_used(settings, tmp_path):
    # With promise factors, the PLAN handed to a cluster promises factor x P after the contact.
    from dataclasses import replace
    env = WsnUavEnv(replace(settings, promise_factors=(0.75, 1.0, 1.5)))
    env.reset(options={"seed": 3})
    assert env.action_space.n == 3 * K_MAX
    order = tour_order(env)
    for i in range(env.K):  # one lap after the survey lap: every contact promises 1.5 x P
        slot = int(np.flatnonzero(env.slot_cluster == order[i % env.K])[0])
        _, _, done, _, _ = env.step(slot * 3 + 2)
        assert not done
    cl = env.last_msg["clusters"]
    promised = cl[:, 6] >= 0
    length = (cl[:, 6] + cl[:, 5])[promised]  # promise time - last contact time
    assert promised.sum() > env.K // 2
    assert np.median(length) == pytest.approx(1.5 * env.P, rel=0.03)
    env.close()
