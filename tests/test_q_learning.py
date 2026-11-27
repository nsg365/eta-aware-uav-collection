import numpy as np
import pytest

from routing.q_learning import Discretizer, TabularQLearning


def test_masked_epsilon_greedy_never_selects_invalid_action():
    agent = TabularQLearning(5, seed=2)
    mask = np.array([False, True, False, True, False])
    for _ in range(100):
        assert agent.act((1, 2), mask, explore=True) in (1, 3)


def test_q_update_uses_masked_bootstrap_maximum():
    agent = TabularQLearning(3, learning_rate=1.0, gamma=0.5)
    s, s2 = (0,), (1,)
    agent.q[s2][:] = [100.0, 4.0, 8.0]
    agent.update(s, 1, 2.0, s2, np.array([False, True, True]), 0.5)
    assert agent.q[s][1] == pytest.approx(6.0)


def test_terminal_update_has_no_bootstrap():
    agent = TabularQLearning(2, learning_rate=1.0)
    agent.update((0,), 0, 3.5, None, None, 0.0)
    assert agent.q[(0,)][0] == pytest.approx(3.5)


def test_discretizer_returns_stable_tuple():
    obs = np.zeros(40 * 13 + 3, dtype=np.float32)
    slots = obs[:-3].reshape(40, 13)
    slots[0, 0] = 1.0
    slots[0, 4] = 0.4
    slots[0, 6] = 0.7
    slots[0, 7] = 0.2
    slots[0, 11] = 1.0
    d = Discretizer()
    state = d(obs)
    assert isinstance(state, tuple)
    assert len(state) == 11
    assert state == d(obs.copy())
