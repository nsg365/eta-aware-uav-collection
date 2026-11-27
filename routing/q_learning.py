"""Discretized tabular Q-learning baseline for next-cluster scheduling.

Adaptation of Bouhamed et al. (IEEE Access, 2020), Section III-C. It reuses
WsnUavEnv, its action mask, its reward, and its semi-MDP decision durations.
It is deliberately separate from routing/dqn.py (masked Double-DQN).
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from experiments.run_experiment import REPO
from routing.env import K_MAX, EnvSettings, WsnUavEnv
from routing.train import load, train_seeds, variant_settings


def _bin(value: float, edges: tuple[float, ...]) -> int:
    return int(np.digitize(float(value), np.asarray(edges, dtype=float)))


class Discretizer:
    """Small, fixed-size abstraction over the existing 40-slot observation."""
    def __init__(self, bins: dict | None = None):
        b = bins or {}
        self.edges = {
            "time": tuple(b.get("mission_time", (0.2, 0.4, 0.6, 0.8))),
            "x": tuple(b.get("uav_x", (-0.5, 0.0, 0.5))),
            "y": tuple(b.get("uav_y", (-0.5, 0.0, 0.5))),
            "buffer": tuple(b.get("nearest_buffer", (0.25, 0.5, 1.0, 2.0))),
            "energy": tuple(b.get("nearest_energy", (0.2, 0.4, 0.6, 0.8))),
            "age": tuple(b.get("nearest_age", (0.25, 0.5, 1.0, 2.0))),
            "slack": tuple(b.get("nearest_slack", (-1.0, -0.25, 0.25, 1.0))),
            "misses": tuple(b.get("nearest_misses", (0.0, 0.2, 0.6))),
            "never": tuple(b.get("never_contacted_fraction", (0.0, 0.1, 0.3, 0.6))),
            "risk": tuple(b.get("nearest_eta_risk", (0.0, 0.05, 0.15, 0.4))),
            "count": tuple(b.get("cluster_count", (8, 16, 24, 32))),
        }

    def __call__(self, obs: np.ndarray) -> tuple[int, ...]:
        slots = np.asarray(obs[:-3], dtype=np.float32).reshape(K_MAX, 13)
        global_features = obs[-3:]
        valid = slots[:, 0] > 0.5
        real = slots[valid]
        if not len(real):
            raise ValueError("observation contains no real clusters")
        # Env sorts nearest first and current cluster last.
        near = real[0]
        e = self.edges
        values = (
            global_features[0], global_features[1], global_features[2],
            near[4], near[6], near[7], near[9], near[10],
            float(real[:, 11].mean()), near[12], len(real),
        )
        names = ("time", "x", "y", "buffer", "energy", "age", "slack",
                 "misses", "never", "risk", "count")
        return tuple(_bin(v, e[n]) for v, n in zip(values, names))


class TabularQLearning:
    """Sparse Q-table with masked epsilon-greedy selection."""
    def __init__(self, n_actions: int, *, learning_rate: float = 0.15,
                 gamma: float = 0.99, epsilon_start: float = 1.0,
                 epsilon_end: float = 0.05, epsilon_decay_steps: int = 100_000,
                 seed: int = 0):
        if n_actions <= 0 or not 0 < learning_rate <= 1 or not 0 <= gamma <= 1:
            raise ValueError("invalid Q-learning dimensions or hyperparameters")
        self.n_actions, self.lr, self.gamma = n_actions, learning_rate, gamma
        self.eps_start, self.eps_end = epsilon_start, epsilon_end
        self.eps_decay_steps = max(1, epsilon_decay_steps)
        self.rng = np.random.default_rng(seed)
        self.q: dict[tuple[int, ...], np.ndarray] = defaultdict(
            lambda: np.zeros(self.n_actions, dtype=np.float32))
        self.steps = 0

    @property
    def epsilon(self) -> float:
        f = min(1.0, self.steps / self.eps_decay_steps)
        return self.eps_start + f * (self.eps_end - self.eps_start)

    def act(self, state: tuple[int, ...], mask: np.ndarray, *, explore: bool = True) -> int:
        valid = np.flatnonzero(np.asarray(mask, dtype=bool))
        if not len(valid):
            raise ValueError("no valid actions")
        if explore and self.rng.random() < self.epsilon:
            return int(self.rng.choice(valid))
        vals = self.q[state][valid]
        return int(self.rng.choice(valid[vals == vals.max()]))

    def update(self, state, action, reward, next_state, next_mask, discount):
        target = float(reward)
        if next_state is not None:
            valid = np.flatnonzero(np.asarray(next_mask, dtype=bool))
            if len(valid):
                target += float(discount) * float(self.q[next_state][valid].max())
        old = float(self.q[state][action])
        self.q[state][action] = old + self.lr * (target - old)
        self.steps += 1

    def save(self, path: Path, metadata: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"n_actions": self.n_actions, "learning_rate": self.lr,
                   "gamma": self.gamma, "steps": self.steps,
                   "q": {json.dumps(list(k)): v.tolist() for k, v in self.q.items()},
                   "metadata": metadata}
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: Path):
        payload = json.loads(path.read_text())
        agent = cls(payload["n_actions"], learning_rate=payload["learning_rate"],
                    gamma=payload["gamma"])
        agent.steps = payload["steps"]
        agent.q = defaultdict(lambda: np.zeros(agent.n_actions, dtype=np.float32))
        for k, v in payload["q"].items():
            agent.q[tuple(json.loads(k))] = np.asarray(v, dtype=np.float32)
        return agent, payload["metadata"]


def _episode(env, agent, discretizer, explore: bool):
    obs, _ = env.reset()
    total, decisions, done = 0.0, 0, False
    while not done:
        mask = env.action_masks()
        state = discretizer(obs)
        action = agent.act(state, mask, explore=explore)
        next_obs, reward, terminated, truncated, info = env.step(action)
        done = bool(terminated or truncated)
        next_state = None if done else discretizer(next_obs)
        next_mask = None if done else env.action_masks()
        dt = max(0.0, float(info.get("dt", 0.0)))
        # Project semi-MDP discount: gamma is defined per t0 seconds.
        discount = agent.gamma ** (dt / env.s.t0)
        if explore:
            agent.update(state, action, reward, next_state, next_mask,
                         0.0 if done else discount)
        total += float(reward)
        decisions += 1
        obs = next_obs
    return total, decisions


def train(config_path: Path, variant_name: str, episodes: int | None = None,
          seed: int = 0) -> Path:
    cfg = load(config_path)
    variant = next((v for v in cfg["variant"] if v["name"] == variant_name), None)
    if variant is None:
        raise ValueError(f"variant {variant_name!r} not found")
    settings = variant_settings(cfg, variant, train_seeds(cfg))
    qcfg = dict(cfg.get("q_learning", {}))
    settings.gamma = float(qcfg.get("gamma", 0.99))
    settings.t0 = float(variant.get("t0", 15.0))
    n_episodes = int(episodes or qcfg.get("episodes", 500))
    disc = Discretizer(qcfg.get("bins", {}))
    agent = TabularQLearning(
        K_MAX * len(settings.promise_factors),
        learning_rate=float(qcfg.get("learning_rate", 0.15)),
        gamma=settings.gamma,
        epsilon_start=float(qcfg.get("epsilon_start", 1.0)),
        epsilon_end=float(qcfg.get("epsilon_end", 0.05)),
        epsilon_decay_steps=int(qcfg.get("epsilon_decay_steps", 100_000)), seed=seed)
    history, started = [], time.time()
    env = WsnUavEnv(settings)
    try:
        for ep in range(n_episodes):
            ret, decisions = _episode(env, agent, disc, explore=True)
            history.append((ep + 1, ret, decisions, agent.epsilon))
    finally:
        env.close()
    out = REPO / "models" / "phase3_qlearning"
    model_path = out / f"{variant_name}_qlearning.json"
    env_keys = ("risk_in_obs", "beta_d", "beta_e", "beta_m", "beta_c", "beta_r",
                "promise_factors", "shaping", "gamma", "t0")
    meta = {
        "algo": "tabular_q_learning", "variant": variant_name,
        "num_sensors": settings.num_sensors, "simulation": settings.simulation,
        "variant_simulation": {k: v for k, v in variant.items()
                                if k != "name" and k not in ENV_KEYS and k not in TRAIN_KEYS},
        "env": {k: getattr(settings, k) for k in env_keys},
        "train_seeds": cfg["train"]["train_seeds"],
        "eval_seeds": cfg["train"]["eval_seeds"], "q_learning": qcfg,
        "episodes": n_episodes, "train_wall_s": round(time.time() - started, 2),
    }
    agent.save(model_path, meta)
    out.mkdir(parents=True, exist_ok=True)
    with (out / f"{variant_name}_train.csv").open("w") as f:
        f.write("episode,return,decisions,epsilon\n")
        for row in history:
            f.write(f"{row[0]},{row[1]:.6f},{row[2]},{row[3]:.6f}\n")
    print(f"saved {model_path.relative_to(REPO)}; states={len(agent.q)}")
    return model_path


ENV_KEYS = {"risk_in_obs", "beta_d", "beta_e", "beta_m", "beta_c", "beta_r",
            "promise_factors", "shaping"}
TRAIN_KEYS = {"t0", "bc_weight", "bc_decay_steps", "topology_config"}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("config", type=Path)
    p.add_argument("--variant", default="A4")
    p.add_argument("--episodes", type=int)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    train(a.config, a.variant, a.episodes, a.seed)


if __name__ == "__main__":
    main()
