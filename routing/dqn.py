"""Masked double DQN with n-step returns, on the per-cluster scoring network.

stable-baselines3 has no action-masked DQN, so this is a small one. Invalid actions get
Q = -inf both when acting and in the bootstrap target. Optional demonstrations (DQfD-style):
`demo_steps` transitions of the tour are collected first and kept for the whole run; every
batch mixes in `demo_fraction` of them, with a large-margin loss that makes the tour's action
score at least `margin` above every other valid action.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from routing.env import K_MAX
from routing.networks import ClusterScorer


class Replay:
    def __init__(self, size: int, obs_dim: int):
        self.o = np.zeros((size, obs_dim), np.float32)
        self.m = np.zeros((size, K_MAX), bool)
        self.o2 = np.zeros((size, obs_dim), np.float32)
        self.m2 = np.zeros((size, K_MAX), bool)
        self.a = np.zeros(size, np.int64)
        self.r = np.zeros(size, np.float32)
        self.g = np.zeros(size, np.float32)  # discount to the bootstrap state; 0 at episode end
        self.size, self.n, self.i = size, 0, 0

    def add(self, o, m, a, r, g, o2, m2):
        k = self.i
        self.o[k], self.m[k], self.a[k], self.r[k] = o, m, a, r
        self.g[k], self.o2[k], self.m2[k] = g, o2, m2
        self.i = (self.i + 1) % self.size
        self.n = min(self.n + 1, self.size)

    def sample(self, k: int, rng: np.random.Generator):
        idx = rng.integers(0, self.n, k)
        return [torch.as_tensor(x[idx])
                for x in (self.o, self.m, self.a, self.r, self.g, self.o2, self.m2)]


class NStep:
    """Turns one env's transitions into n-step transitions."""

    def __init__(self, n: int, gamma: float):
        self.n, self.gamma, self.q = n, gamma, deque()

    def push(self, o, m, a, r, o2, m2, done) -> list[tuple]:
        self.q.append((o, m, a, r))
        out = []
        if len(self.q) == self.n:
            out.append(self._emit(o2, m2, done))
        if done:
            while self.q:
                out.append(self._emit(o2, m2, True))
        return out

    def _emit(self, o2, m2, done):
        ret = sum(self.gamma ** i * t[3] for i, t in enumerate(self.q))
        g = 0.0 if done else self.gamma ** len(self.q)
        o, m, a, _ = self.q.popleft()
        return o, m, a, ret, g, o2, m2


def masked(q: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return q.masked_fill(~mask, -torch.inf)


class MaskedDQN:
    def __init__(self, obs_dim: int, *, lr=1e-4, gamma=0.99, n_step=3, buffer_size=200_000,
                 batch_size=256, learning_starts=5_000, updates_per_step=1, tau=0.005,
                 eps_start=1.0, eps_end=0.05, eps_fraction=0.3, demo_steps=0,
                 demo_fraction=0.25, margin=0.8, margin_weight=1.0, seed=0, arch=None):
        self.arch = arch or {}
        self.q = ClusterScorer(**self.arch)
        self.target = ClusterScorer(**self.arch)
        self.target.load_state_dict(self.q.state_dict())
        self.opt = torch.optim.Adam(self.q.parameters(), lr=lr)
        self.gamma, self.n_step, self.batch, self.tau = gamma, n_step, batch_size, tau
        self.learning_starts, self.updates_per_step = learning_starts, updates_per_step
        self.eps = (eps_start, eps_end, eps_fraction)
        self.demo_steps, self.demo_fraction = demo_steps, demo_fraction
        self.margin, self.margin_weight = margin, margin_weight
        self.buf = Replay(buffer_size, obs_dim)
        self.demo = Replay(max(demo_steps, 1), obs_dim)
        self.rng = np.random.default_rng(seed)
        torch.manual_seed(seed)

    # ---- acting

    @torch.no_grad()
    def act(self, obs: np.ndarray, masks: np.ndarray, eps: float = 0.0) -> np.ndarray:
        q = masked(self.q(torch.as_tensor(obs, dtype=torch.float32)), torch.as_tensor(masks))
        a = q.argmax(1).numpy()
        for i in np.flatnonzero(self.rng.random(len(a)) < eps):
            a[i] = self.rng.choice(np.flatnonzero(masks[i]))
        return a

    # ---- learning

    def _update(self) -> None:
        nd = int(self.batch * self.demo_fraction) if self.demo.n else 0
        b = self.buf.sample(self.batch - nd, self.rng)
        if nd:
            b = [torch.cat([x, y]) for x, y in zip(b, self.demo.sample(nd, self.rng))]
        o, m, a, r, g, o2, m2 = b
        with torch.no_grad():
            a2 = masked(self.q(o2), m2).argmax(1, keepdim=True)          # double DQN
            q2 = self.target(o2).gather(1, a2).squeeze(1)
            y = r + g * torch.where(g > 0, q2, torch.zeros_like(q2))
        q_all = self.q(o)
        loss = F.smooth_l1_loss(q_all.gather(1, a[:, None]).squeeze(1), y)
        if nd:  # large-margin loss on demonstrations (DQfD): max(Q + margin*[a != a_E]) - Q(a_E)
            qd, ad = q_all[-nd:], a[-nd:, None]
            plus = masked(qd + self.margin, m[-nd:]).scatter(1, ad, qd.gather(1, ad))
            loss = loss + self.margin_weight * (plus.max(1).values - qd.gather(1, ad)[:, 0]).mean()
        self.opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
        self.opt.step()
        with torch.no_grad():
            for p, tp in zip(self.q.parameters(), self.target.parameters()):
                tp.mul_(1 - self.tau).add_(self.tau * p)

    def learn(self, vec, total_steps: int, log_path: Path | None = None) -> None:
        n = vec.num_envs
        obs = vec.reset()
        masks = np.array(vec.env_method("action_masks"))
        nsteps = [NStep(self.n_step, self.gamma) for _ in range(n)]
        ep_ret, ep_len, t0 = np.zeros(n), np.zeros(n, int), time.time()
        log = open(log_path, "w") if log_path else None
        if log:
            log.write("r,l,t\n")
        if self.demo_steps:
            self._collect_demos(vec, obs, masks)
            obs = vec.reset()
            masks = np.array(vec.env_method("action_masks"))
        start, eps_start, eps_end, frac = 0, *self.eps
        while start < total_steps:
            eps = max(eps_end, eps_start - (eps_start - eps_end) * start / (frac * total_steps))
            act = self.act(obs, masks, eps)
            obs2, rew, done, info = vec.step(act)
            masks2 = np.array(vec.env_method("action_masks"))
            for i in range(n):
                o2 = info[i]["terminal_observation"] if done[i] else obs2[i]
                for tr in nsteps[i].push(obs[i], masks[i], act[i], rew[i], o2, masks2[i],
                                         done[i]):
                    self.buf.add(*tr)
                ep_ret[i] += rew[i]
                ep_len[i] += 1
                if done[i]:
                    if log:
                        log.write(f"{ep_ret[i]:.4f},{ep_len[i]},{time.time() - t0:.2f}\n")
                        log.flush()
                    ep_ret[i], ep_len[i] = 0.0, 0
            obs, masks = obs2, masks2
            start += n
            if self.buf.n >= self.learning_starts:
                for _ in range(self.updates_per_step):
                    self._update()
        if log:
            log.close()

    def _collect_demos(self, vec, obs, masks):
        """Fill the demonstration buffer by following the tour (env.expert_action)."""
        nsteps = [NStep(self.n_step, self.gamma) for _ in range(vec.num_envs)]
        while self.demo.n < self.demo_steps:
            act = np.array(vec.env_method("expert_action"))
            obs2, rew, done, info = vec.step(act)
            masks2 = np.array(vec.env_method("action_masks"))
            for i in range(vec.num_envs):
                o2 = info[i]["terminal_observation"] if done[i] else obs2[i]
                for tr in nsteps[i].push(obs[i], masks[i], act[i], rew[i], o2, masks2[i],
                                         done[i]):
                    self.demo.add(*tr)
            obs, masks = obs2, masks2

    def save(self, path: Path) -> None:
        torch.save({"state_dict": self.q.state_dict(), "arch": self.arch}, path)

    @staticmethod
    def load_scorer(path: Path) -> ClusterScorer:
        ck = torch.load(path, map_location="cpu")
        net = ClusterScorer(**ck["arch"])
        net.load_state_dict(ck["state_dict"])
        return net.eval()
