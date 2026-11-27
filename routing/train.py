"""Train one or all variants of a Phase 3 config.

Usage:   python3 -m routing.train configs/phase3_ppo.toml [--variant A4] [--algo ppo|dqn]
                [--arch mlp|scoring] [--warm-start] [--timesteps N] [--n-envs 8]
Output:  models/<name>/<model>.zip|.pt     the policy (<model> = variant plus a tag, e.g. A4_dqn)
         models/<name>/<model>.json        everything needed to rebuild its environment
         models/<name>/<model>_train.monitor.csv  one row per training episode

--algo ppo:  MaskablePPO. --arch mlp is the plain MLP over the padded slots; --arch scoring is
             the per-cluster scoring network (routing/networks.py).
--algo dqn:  masked double DQN on the scoring network (routing/dqn.py).
--warm-start starts from the tour: PPO first copies the tour's choices (behaviour cloning) and
             fits its value to the tour's returns; DQN keeps tour demonstrations in replay (DQfD).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import tomllib
from pathlib import Path

import numpy as np
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import CallbackList
from stable_baselines3.common.vec_env import SubprocVecEnv, VecMonitor

from experiments.run_experiment import REPO
from routing.env import EnvSettings, make_env

ENV_KEYS = {"risk_in_obs", "beta_d", "beta_e", "beta_m", "beta_c", "beta_r",
            "promise_factors", "shaping", "k_max"}
# Variant keys for training only (routing/ppo_extras.py): time-based discount (t0 seconds),
# staying near the tour (bc_weight, bc_decay_steps), and the Phase 0 layout to train on.
TRAIN_KEYS = {"t0", "bc_weight", "bc_decay_steps", "topology_config", "areas", "networks"}


def load(config: Path) -> dict:
    with open(config, "rb") as f:
        return tomllib.load(f)


def variant_settings(cfg: dict, variant: dict, seeds: list[int]) -> EnvSettings:
    """Env settings of one [[variant]]: its sim keys go to ns-3, its ENV_KEYS to the MDP."""
    sim = {**cfg.get("simulation", {}),
           **{k: v for k, v in variant.items()
              if k != "name" and k not in ENV_KEYS and k not in TRAIN_KEYS}}
    env = {**cfg.get("reward", {}), **{k: v for k, v in variant.items() if k in ENV_KEYS}}
    topo = variant.get("topology_config", cfg["train"].get("topology_config"))
    if topo:
        env["topology_config"] = REPO / topo
    areas = tuple(variant.get("areas", cfg["train"].get("areas", ())))
    networks = tuple(variant.get("networks", cfg["train"].get("networks", ())))
    return EnvSettings(seeds=seeds, simulation=sim, num_sensors=cfg["train"]["num_sensors"],
                       gamma=cfg.get("ppo", {}).get("gamma", 0.99), t0=variant.get("t0", 15.0),
                       areas=areas, networks=networks, **env)


def train_seeds(cfg: dict) -> list[int]:
    lo, hi = cfg["train"]["train_seeds"]
    seeds = list(range(lo, hi + 1))
    assert not set(seeds) & set(cfg["train"]["eval_seeds"]), "train and eval seeds overlap"
    return seeds


def model_name(variant: str, algo: str, arch: str, warm: bool) -> str:
    tag = "dqn" if algo == "dqn" else ("" if arch == "mlp" else "ppo-scoring")
    return "_".join(x for x in (variant, tag, "ws" if warm else "") if x)


# ---- warm start for PPO

def tour_rollouts(vec, steps: int, gamma: float, t0: float | None = None):
    """Follow the tour for at least `steps` decisions, in whole episodes. Returns observations,
    masks, the tour's actions and the discounted returns that followed. With t0, each decision
    is discounted by gamma ** (dt / t0), as PPO's semi-MDP buffer does (docs/MDP.md §1)."""
    obs = vec.reset()
    traj = [[] for _ in range(vec.num_envs)]
    O, M, A, G = [], [], [], []
    while len(A) < steps:
        masks = np.array(vec.env_method("action_masks"))
        act = np.array(vec.env_method("expert_action"))
        obs2, rew, done, infos = vec.step(act)
        for i in range(vec.num_envs):
            g = gamma ** (infos[i]["dt"] / t0) if t0 else gamma
            traj[i].append((obs[i], masks[i], act[i], rew[i], g))
            if done[i]:
                ret = 0.0
                for o, m, a, r, g in reversed(traj[i]):
                    ret = r + g * ret
                    O.append(o); M.append(m); A.append(a); G.append(ret)
                traj[i] = []
        obs = obs2
    return (torch.as_tensor(np.array(O)), torch.as_tensor(np.array(M)),
            torch.as_tensor(np.array(A)), torch.as_tensor(np.array(G), dtype=torch.float32))


def behaviour_clone(model: MaskablePPO, settings: EnvSettings, n_envs: int, ws: dict,
                    t0: float | None = None):
    demo = SubprocVecEnv([make_env(settings) for _ in range(n_envs)])
    demo.seed(10_000)
    O, M, A, G = tour_rollouts(demo, ws.get("demo_steps", 50_000), model.gamma, t0)
    demo.close()
    policy = model.policy
    opt = torch.optim.Adam(policy.parameters(), lr=ws.get("lr", 1e-3))
    n, bs = len(A), ws.get("batch_size", 256)
    for epoch in range(ws.get("epochs", 10)):
        perm = torch.randperm(n)
        for k in range(0, n, bs):
            idx = perm[k:k + bs]
            _, logp, _ = policy.evaluate_actions(O[idx], A[idx], action_masks=M[idx].numpy())
            values = policy.predict_values(O[idx]).squeeze(1)
            loss = -logp.mean() + 0.5 * torch.nn.functional.mse_loss(values, G[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
    with torch.no_grad():
        dist = policy.get_distribution(O[:4096], action_masks=M[:4096].numpy())
        agree = (dist.distribution.probs.argmax(1) == A[:4096]).float().mean().item()
    return {"demo_transitions": n, "tour_agreement": round(agree, 4)}, (O, M, A)


# ---- training

def train(cfg: dict, variant: dict, algo: str, arch: str, warm: bool, timesteps: int,
          n_envs: int) -> Path:
    name = cfg["train"]["name"]
    out = REPO / "models" / name
    out.mkdir(parents=True, exist_ok=True)
    mname = model_name(variant["name"], algo, arch, warm)
    settings = variant_settings(cfg, variant, train_seeds(cfg))
    torch.set_num_threads(2)
    extra = {}
    t0 = time.time()
    if algo == "ppo":
        vec = VecMonitor(SubprocVecEnv([make_env(settings) for _ in range(n_envs)]),
                         filename=str(out / f"{mname}_train"))
        vec.seed(0)
        ppo = dict(cfg.get("ppo", {}))
        net_arch = ppo.pop("net_arch", [256, 256])
        if arch == "scoring":
            from routing.networks import ClusterScoringPolicy
            policy, kwargs = ClusterScoringPolicy, {}
        else:
            policy, kwargs = "MlpPolicy", {"net_arch": net_arch}
        callbacks = []
        if "t0" in variant:
            from routing.ppo_extras import DtCallback, SemiMdpRolloutBuffer
            ppo.update(rollout_buffer_class=SemiMdpRolloutBuffer,
                       rollout_buffer_kwargs={"t0": variant["t0"]})
            callbacks.append(DtCallback())
        model = MaskablePPO(policy, vec, seed=0, verbose=0, policy_kwargs=kwargs, **ppo)
        if warm:
            extra["warm_start"], demos = behaviour_clone(model, settings, n_envs,
                                                         cfg.get("warm_start", {}),
                                                         variant.get("t0"))
            if variant.get("bc_weight"):
                from routing.ppo_extras import DemoRegularizer
                callbacks.append(DemoRegularizer(*demos, weight=variant["bc_weight"],
                                                 decay_steps=variant.get("bc_decay_steps",
                                                                         timesteps)))
        model.learn(total_timesteps=timesteps, progress_bar=False,
                    callback=CallbackList(callbacks) if callbacks else None)
        vec.close()
        model.save(out / mname)
        path = out / f"{mname}.zip"
    else:
        from routing.dqn import MaskedDQN
        vec = SubprocVecEnv([make_env(settings) for _ in range(n_envs)])
        vec.seed(0)
        dqn = dict(cfg.get("dqn", {}))
        if warm:
            dqn.setdefault("demo_steps", cfg.get("warm_start", {}).get("demo_steps", 50_000))
        agent = MaskedDQN(vec.observation_space.shape[0],
                          arch={"n_out": vec.action_space.n // settings.k_max}, **dqn)
        agent.learn(vec, timesteps, log_path=out / f"{mname}_train.monitor.csv")
        vec.close()
        path = out / f"{mname}.pt"
        agent.save(path)
    wall = time.time() - t0
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()
    meta = {"variant": variant["name"], "algo": algo, "arch": "scoring" if algo == "dqn" else arch,
            "warm_start": warm, "num_sensors": settings.num_sensors, "areas": list(settings.areas),
            "networks": list(settings.networks),
            "simulation": settings.simulation,
            # sim keys that define the variant; evaluation applies them on top of its own
            "variant_simulation": {k: v for k, v in variant.items()
                                   if k != "name" and k not in ENV_KEYS and k not in TRAIN_KEYS},
            "env": {k: getattr(settings, k) for k in sorted(ENV_KEYS | {"gamma", "t0"})},
            "training": {k: v for k, v in variant.items() if k in TRAIN_KEYS},
            "train_seeds": cfg["train"]["train_seeds"], "eval_seeds": cfg["train"]["eval_seeds"],
            "hyperparameters": cfg.get(algo, {}), "timesteps": timesteps, "n_envs": n_envs,
            "train_wall_s": round(wall, 1), "git_commit": commit, **extra}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(f"{name}/{mname}: {timesteps} steps in {wall / 60:.1f} min -> {path.relative_to(REPO)}"
          + (f"  {extra}" if extra else ""), flush=True)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("--variant", help="train only this variant (default: all)")
    ap.add_argument("--algo", choices=["ppo", "dqn"], default="ppo")
    ap.add_argument("--arch", choices=["mlp", "scoring"], default="mlp")
    ap.add_argument("--warm-start", action="store_true")
    ap.add_argument("--timesteps", type=int)
    ap.add_argument("--n-envs", type=int)
    a = ap.parse_args()
    cfg = load(a.config)
    variants = [v for v in cfg["variant"] if a.variant in (None, v["name"])]
    if not variants:
        raise SystemExit(f"no variant {a.variant!r} in {a.config}")
    for v in variants:
        train(cfg, v, a.algo, a.arch, a.warm_start, a.timesteps or cfg["train"]["timesteps"],
              a.n_envs or cfg["train"]["n_envs"])


if __name__ == "__main__":
    main()
