"""Run a trained Phase 3 policy (PPO or DQN) as an ordinary experiment variant.

experiments/run_experiment.py calls run_ppo() for every variant with routing = "ppo", e.g.

    [[variant]]
    name = "er_ppo"
    routing = "ppo"
    model = "models/phase3_ppo/A4.zip"

The model's <name>.json says how its observation and reward were built and which simulator
settings define the variant (e.g. adaptiveWindow = false for A1/A2); those are applied on top of
the experiment's [simulation] table. The policy acts deterministically (most likely action).
Besides the usual ns-3 outputs, each run writes ppo.json: return, decisions and inference time.
"""

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
    """(act(obs, mask) -> action, meta) for a MaskablePPO .zip or a masked-DQN .pt."""
    path = (REPO / path).resolve()
    with _lock:
        if path not in _models:
            torch.set_num_threads(1)  # many runs in parallel; each inference is tiny
            meta = json.loads(path.with_suffix(".json").read_text())
            if meta.get("algo") == "dqn":
                from routing.dqn import MaskedDQN
                net = MaskedDQN.load_scorer(path)

                @torch.no_grad()
                def act(obs, mask, net=net):
                    q = net(torch.as_tensor(obs, dtype=torch.float32)[None])[0]
                    return int(q.masked_fill(~torch.as_tensor(mask), -torch.inf).argmax())
            else:
                model = MaskablePPO.load(path, device="cpu")

                def act(obs, mask, model=model):
                    return int(model.predict(obs, action_masks=mask, deterministic=True)[0])
            _models[path] = (act, meta)
        return _models[path]


def run_ppo(model_path: str | Path, simulation: dict) -> dict:
    """One evaluation episode. `simulation` is the job's ns-3 table (topologyDir, outDir, seed...)."""
    act, meta = load_model(model_path)
    sim = {k: v for k, v in simulation.items()
           if k not in ("routing", "model", "topologyDir", "outDir", "seed")}
    sim.update(meta.get("variant_simulation", {}))
    settings = EnvSettings(seeds=[int(simulation["seed"])], simulation=sim, **meta["env"])
    env = WsnUavEnv(settings)
    out = REPO / simulation["outDir"]
    obs, _ = env.reset(options={"seed": int(simulation["seed"]),
                                "topology": REPO / simulation["topologyDir"], "out": out})
    total, decisions, infer, done = 0.0, 0, [], False
    while not done:
        t = time.perf_counter()
        with _lock:  # the models are shared between threads
            action = act(obs, env.action_masks())
        infer.append(time.perf_counter() - t)
        obs, reward, done, _, _ = env.step(int(action))
        total += reward
        decisions += 1
    info = {"model": str(model_path), "return": round(total, 3), "decisions": decisions,
            "inference_ms_mean": round(1e3 * float(np.mean(infer)), 4),
            "inference_ms_p95": round(1e3 * float(np.percentile(infer, 95)), 4)}
    (out / "ppo.json").write_text(json.dumps(info, indent=2))
    return info
