"""Two additions to MaskablePPO for the Phase 3 training fixes (docs/MDP.md §6).

1. Time-based (semi-MDP) discount. A decision can last 5 s or 150 s, so a fixed gamma per
   decision favours policies that take few, long decisions (they fit more of the mission into the
   discount horizon). SemiMdpRolloutBuffer discounts each step by gamma ** (dt / t0) instead,
   where dt is the step's mission time (info["dt"] from the env) and gamma is per t0 seconds.
   This is the proposal's gamma_t = gamma ** (dt / T0).

2. Staying near the tour (demo-augmented policy gradient, Rajeswaran et al. 2017). After every
   rollout, DemoRegularizer takes a few behaviour-cloning steps on recorded tour decisions with a
   weight that decays over training, so PPO's exploration cannot wander far from the tour before
   the critic has learned what the tour is worth.
"""

from __future__ import annotations

import numpy as np
import torch
from sb3_contrib.common.maskable.buffers import MaskableRolloutBuffer
from stable_baselines3.common.callbacks import BaseCallback


class SemiMdpRolloutBuffer(MaskableRolloutBuffer):
    def __init__(self, *args, t0: float = 15.0, **kwargs):
        self.t0 = t0
        self.pending_dt = None
        super().__init__(*args, **kwargs)

    def reset(self) -> None:
        super().reset()
        self.dts = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32)

    def add(self, *args, **kwargs) -> None:
        self.dts[self.pos] = self.pending_dt
        super().add(*args, **kwargs)

    def compute_returns_and_advantage(self, last_values: torch.Tensor, dones: np.ndarray) -> None:
        last_values = last_values.clone().cpu().numpy().flatten()
        gae = 0
        for step in reversed(range(self.buffer_size)):
            if step == self.buffer_size - 1:
                non_terminal = 1.0 - dones.astype(np.float32)
                next_values = last_values
            else:
                non_terminal = 1.0 - self.episode_starts[step + 1]
                next_values = self.values[step + 1]
            g = self.gamma ** (self.dts[step] / self.t0)
            delta = self.rewards[step] + g * next_values * non_terminal - self.values[step]
            gae = delta + g * self.gae_lambda * non_terminal * gae
            self.advantages[step] = gae
        self.returns = self.advantages + self.values


class DtCallback(BaseCallback):
    """Hands each step's mission time to the rollout buffer before PPO stores the step."""

    def _on_step(self) -> bool:
        self.model.rollout_buffer.pending_dt = np.array(
            [info["dt"] for info in self.locals["infos"]], dtype=np.float32)
        return True


class DemoRegularizer(BaseCallback):
    """Behaviour-cloning steps on tour decisions after each rollout, weight decaying linearly
    from `weight` to 0 over `decay_steps` environment steps."""

    def __init__(self, obs, masks, actions, weight=1.0, decay_steps=200_000, batches=8,
                 batch_size=256):
        super().__init__()
        self.obs, self.masks, self.actions = obs, masks, actions
        self.weight, self.decay_steps = weight, decay_steps
        self.batches, self.batch_size = batches, batch_size

    def _on_step(self) -> bool:
        return True

    def _on_rollout_end(self) -> None:
        w = self.weight * max(0.0, 1.0 - self.num_timesteps / self.decay_steps)
        if w <= 0:
            return
        policy = self.model.policy
        for _ in range(self.batches):
            idx = torch.randint(0, len(self.actions), (self.batch_size,))
            _, logp, _ = policy.evaluate_actions(self.obs[idx], self.actions[idx],
                                                 action_masks=self.masks[idx].numpy())
            loss = -w * logp.mean()
            policy.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), self.model.max_grad_norm)
            policy.optimizer.step()
