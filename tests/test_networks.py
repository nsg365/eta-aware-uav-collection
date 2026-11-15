"""Slot count of the scoring networks (routing/networks.py, docs/MDP.md §2)."""

import torch

from routing.env import GLOBAL_FEATURES, SLOT_FEATURES
from routing.networks import ClusterScorer


def obs(k, real):
    o = torch.zeros(2, k * SLOT_FEATURES + GLOBAL_FEATURES)
    o[:, :real * SLOT_FEATURES].view(2, real, SLOT_FEATURES)[..., 0] = 1.0  # slot holds a cluster
    o[:, :real * SLOT_FEATURES] += torch.rand(2, real * SLOT_FEATURES) * 0.1
    return o


def test_same_weights_score_any_slot_count():
    net = ClusterScorer(n_out=1)
    assert net(obs(40, 30)).shape == (2, 40)
    assert net(obs(64, 55)).shape == (2, 64)


def test_padding_does_not_change_scores():
    # the same 30 clusters padded to 40 or 64 slots get the same scores
    torch.manual_seed(0)
    net = ClusterScorer(n_out=1).eval()
    o40 = obs(40, 30)
    o64 = torch.zeros(2, 64 * SLOT_FEATURES + GLOBAL_FEATURES)
    o64[:, :40 * SLOT_FEATURES] = o40[:, :40 * SLOT_FEATURES]
    o64[:, -GLOBAL_FEATURES:] = o40[:, -GLOBAL_FEATURES:]
    with torch.no_grad():
        assert torch.allclose(net(o40)[:, :30], net(o64)[:, :30], atol=1e-5)
