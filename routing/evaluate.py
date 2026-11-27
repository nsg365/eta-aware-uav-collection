
"""Evaluate a trained Phase 3 policy (PPO, DQN, or tabular Q-learning)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import torch
from sb3_contrib import MaskablePPO

from experiments.run_experiment import REPO
from routing.env import EnvSettings, WsnUavEnv

_models: dict[Path, tuple] = {}
_lock = threading.Lock()


def load_model(path: str | Path) -> tuple:
    """Return (act(obs, mask) -> action, metadata)."""
    path = (REPO / path).resolve()

    with _lock:
        if path not in _models:
            torch.set_num_threads(1)

            # Tabular Q-learning stores its Q-table and metadata together.
            if path.suffix == ".json":
                from routing.q_learning import Discretizer, TabularQLearning

                agent, meta = TabularQLearning.load(path)
                discretizer = Discretizer(meta["q_learning"]["bins"])

                def act(obs, mask, agent=agent, discretizer=discretizer):
                    state = discretizer(obs)
                    return agent.act(state, mask, explore=False)

            else:
                # PPO and DQN store metadata in a separate .json sidecar.
                meta = json.loads(path.with_suffix(".json").read_text())

                if meta.get("algo") == "dqn":
                    from routing.dqn import MaskedDQN

                    net = MaskedDQN.load_scorer(path)

                    @torch.no_grad()
                    def act(obs, mask, net=net):
                        q = net(torch.as_tensor(obs, dtype=torch.float32)[None])[0]
                        mask_tensor = torch.as_tensor(mask, dtype=torch.bool)
                        return int(q.masked_fill(~mask_tensor, -torch.inf).argmax())

                else:
                    model = MaskablePPO.load(path, device="cpu")

                    def act(obs, mask, model=model):
                        action, _ = model.predict(
                            obs,
                            action_masks=mask,
                            deterministic=True,
                        )
                        return int(action)

            _models[path] = (act, meta)

        return _models[path]


def run_ppo(model_path: str | Path, simulation: dict) -> dict:
    """Run one evaluation episode using a trained routing policy."""
    act, meta = load_model(model_path)

    # Start with the experiment's simulation settings, then apply the
    # model variant's settings so evaluation matches the trained variant.
    sim = {
        k: v
        for k, v in simulation.items()
        if k not in ("routing", "model", "topologyDir", "outDir", "seed")
    }
    sim.update(meta.get("variant_simulation", {}))

    env_meta = dict(meta["env"])
    if isinstance(env_meta.get("promise_factors"), list):
        env_meta["promise_factors"] = tuple(env_meta["promise_factors"])

    settings = EnvSettings(
        seeds=[int(simulation["seed"])],
        simulation=sim,
        num_sensors=int(meta.get("num_sensors", 100)),
        **env_meta,
    )

    env = WsnUavEnv(settings)
    out = REPO / simulation["outDir"]
    out.mkdir(parents=True, exist_ok=True)

    total = 0.0
    decisions = 0
    infer = []

    try:
        obs, _ = env.reset(
            options={
                "seed": int(simulation["seed"]),
                "topology": REPO / simulation["topologyDir"],
                "out": out,
            }
        )

        done = False
        while not done:
            mask = env.action_masks()

            t = time.perf_counter()
            with _lock:
                action = act(obs, mask)
            infer.append(time.perf_counter() - t)

            obs, reward, terminated, truncated, _ = env.step(int(action))
            done = bool(terminated or truncated)

            total += float(reward)
            decisions += 1

    finally:
        env.close()

    info = {
        "model": str(model_path),
        "return": round(total, 3),
        "decisions": decisions,
        "inference_ms_mean": round(1e3 * float(np.mean(infer)), 4),
        "inference_ms_p95": round(1e3 * float(np.percentile(infer, 95)), 4),
    }

    # Keep the existing filename and result structure for compatibility
    # with the experiment runner's flattened CSV output.
    (out / "ppo.json").write_text(json.dumps(info, indent=2))
    return info
