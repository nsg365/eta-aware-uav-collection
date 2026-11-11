"""Time-based (semi-MDP) discount of routing/ppo_extras.py (docs/MDP.md §1)."""

import numpy as np
import torch
from gymnasium import spaces

from routing.ppo_extras import SemiMdpRolloutBuffer


def returns(dts, rewards, values, last_value, gamma=0.9, lam=1.0, t0=15.0):
    buf = SemiMdpRolloutBuffer(len(dts), spaces.Box(-1, 1, (2,)), spaces.Discrete(3),
                               gamma=gamma, gae_lambda=lam, n_envs=1, t0=t0)
    for dt, r, v in zip(dts, rewards, values):
        buf.pending_dt = np.array([dt], np.float32)
        buf.add(np.zeros((1, 2)), np.zeros((1, 1)), np.array([r]), np.array([False]),
                torch.tensor([v]), torch.tensor([0.0]), action_masks=np.ones((1, 3)))
    buf.compute_returns_and_advantage(torch.tensor([last_value]), np.array([False]))
    return buf.returns[:, 0]


def test_discount_follows_mission_time():
    # with lambda = 1 the return is the discounted sum, each step discounted by gamma^(dt/t0)
    dts, rewards = [15.0, 30.0, 7.5], [1.0, 2.0, 3.0]
    got = returns(dts, rewards, [0.0, 0.0, 0.0], last_value=4.0)
    g = [0.9 ** (dt / 15.0) for dt in dts]
    r3 = 3.0 + g[2] * 4.0
    r2 = 2.0 + g[1] * r3
    r1 = 1.0 + g[0] * r2
    assert np.allclose(got, [r1, r2, r3], rtol=1e-5)


def test_equal_steps_of_t0_match_fixed_gamma():
    got = returns([15.0] * 4, [1.0] * 4, [0.0] * 4, last_value=0.0)
    assert np.allclose(got, [sum(0.9 ** k for k in range(4 - i)) for i in range(4)], rtol=1e-5)
