"""Checks behind the Phase 3 conclusion "the tour is hard to beat here" (docs/handoff/phase3.md §6).

Runs policies side by side on held-out networks (seeds 1-5 by default) with one model's MDP and
simulator settings, and prints return, PDR, overflow, on-time meetings and CH energy:

    python3 -m routing.redteam models/phase3_fixes/C_ppo-scoring_ws.zip tour model
    python3 -m routing.redteam models/phase3_fixes/D_ppo-scoring_ws.zip tour model agreement \\
        buffer:0.7 buffer:9 short:9

Policies:
- tour            the tour successor with the standard promise (expert_action)
- model           the trained policy, deterministic
- agreement       the trained policy, also printing how often it picks the tour's action
- buffer:THETA    tour order, but detour to any cluster whose estimated buffer on arrival is at
                  least THETA x bufferCapacity, then resume the tour where it left off
- short:THETA     buffer:THETA, plus clusters that can overflow within one lap get 0.75 x P
                  promises and are visited as soon as their promise is due

Networks come from the model's topology config (uniform, or the hotspot layout for model D).
Returns leave out the shaping term, so models trained with and without shaping are comparable.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from experiments.run_experiment import REPO
from routing.env import EnvSettings, WsnUavEnv, ensure_topology
from routing.evaluate import load_model


class BufferRule:
    def __init__(self, env: WsnUavEnv, theta: float, short: bool):
        self.env, self.theta, self.short = env, theta, short
        self.resume = None

    def reset(self):
        self.resume = None

    def __call__(self, obs, mask) -> int:
        env, m = self.env, self.env.last_msg
        cl, cur = m["clusters"], m["current"]
        travel = np.hypot(cl[:, 0] - m["x"], cl[:, 1] - m["y"]) / env.sim["uavSpeed"]
        fill = cl[:, 2] + cl[:, 3] * travel
        cap = env.sim["bufferCapacity"]
        prone = cl[:, 3] * env.P > 0.8 * cap
        if cur < 0 or self.resume is None:
            self.resume = env.tour[0] if cur < 0 else env.tour_next[cur]
        elif cur == self.resume:
            self.resume = env.tour_next[cur]
        urgent = (np.arange(env.K) != cur) & (fill >= self.theta * cap)
        if self.short:
            urgent |= (np.arange(env.K) != cur) & prone & (cl[:, 6] >= 0) & (cl[:, 6] < travel)
        urgent[self.resume] = False
        target = int(np.argmax(np.where(urgent, fill, -np.inf))) if urgent.any() else self.resume
        factor = 0.75 if self.short and prone[target] else 1.0
        slot = int(np.flatnonzero(env.slot_cluster == target)[0])
        return slot * env.nf + list(env.s.promise_factors).index(factor)


def run(model: str, policies: list[str], seeds: list[int], out: Path) -> None:
    act, meta = load_model(model)
    topo = meta.get("training", {}).get("topology_config")
    settings = EnvSettings(seeds=seeds, simulation=meta["simulation"], **meta["env"],
                           **({"topology_config": REPO / topo} if topo else {}))
    env = WsnUavEnv(settings)
    for name in policies:
        kind, _, arg = name.partition(":")
        rule = BufferRule(env, float(arg), kind == "short") if kind in ("buffer", "short") else None
        total, same, decisions, metrics = 0.0, 0, 0, []
        for seed in seeds:
            run_dir = out / name.replace(":", "_") / f"s{seed}"
            obs, _ = env.reset(options={"seed": seed, "out": run_dir,
                                        "topology": ensure_topology(settings, seed)})
            if rule:
                rule.reset()
            done = False
            while not done:
                if kind == "tour":
                    a = env.expert_action()
                elif rule:
                    a = rule(obs, env.action_masks())
                else:
                    a = act(obs, env.action_masks())
                    same += a == env.expert_action()
                obs, r, done, _, parts = env.step(a)
                total += r - parts.get("shaping", 0.0)
                decisions += 1
            metrics.append(json.loads((run_dir / "metrics.json").read_text()))
        mean = lambda f: float(np.mean([f(x) for x in metrics]))
        met = mean(lambda x: x["wake"]["windows_met"])
        missed = mean(lambda x: x["wake"]["windows_missed"])
        line = (f"{name:12} return {total / len(seeds):7.1f}  PDR {mean(lambda x: x['data']['pdr']):.3f}"
                f"  overflow {100 * mean(lambda x: x['data']['overflow'] / x['data']['generated']):4.1f}%"
                f"  on-time {100 * met / (met + missed):4.1f}%"
                f"  CH J {mean(lambda x: x['energy']['primary_ch_mean_J']):4.0f}"
                f"  decisions {decisions / len(seeds):4.0f}")
        if kind == "agreement":
            line += f"  same as tour {100 * same / decisions:5.1f}%"
        print(line, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="trained model (.zip or .pt); its .json gives the settings")
    ap.add_argument("policies", nargs="+")
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--out", type=Path, default=None, help="run folders (default: a temp folder)")
    a = ap.parse_args()
    out = a.out or Path(tempfile.mkdtemp(prefix="redteam_"))
    run(a.model, a.policies, [int(s) for s in a.seeds.split(",")], out)


if __name__ == "__main__":
    main()
