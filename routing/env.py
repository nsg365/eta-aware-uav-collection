"""Gymnasium environment: one episode = one ns-3 mission with --routing=external.

The ns-3 program flies the survey lap itself, then at every decision epoch writes one line on a
pipe (see ExternalPolicy in simulation/ns3/wsn-uav/routing-policy.h) and waits for the next
cluster id. This module turns that line into a fixed-size observation, an action mask and a
reward. docs/MDP.md is the specification; keep the two in sync.

Clusters are presented in slots sorted by flight time from the UAV (nearest first, the current
cluster last), padded to k_max slots (K_MAX = 40 unless a variant sets k_max). The action is a slot index, so one policy works across
topologies with different cluster counts.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import gymnasium as gym
import numpy as np

from clustering.topology import TopologyParams, build_topology, write_topology
from experiments.run_experiment import REPO, ns3_binary, sim_args

K_MAX = 40  # default slot count; old models were trained with it
SLOT_FEATURES = 13
GLOBAL_FEATURES = 3
TOTALS = 7  # delivered generated windows_missed retry_successes flight_s hover_s ch_wifi_J
CLUSTER_FIELDS = 10  # meet_x meet_y buffer rate energy since until_promise missed never late_q

# Defaults of the ns-3 program (simulation/ns3/wsn-uav/config.h) that the env needs.
SIM_DEFAULTS = {
    "simTime": 7200.0, "readingRate": 0.1, "initialEnergy": 500.0, "uavSpeed": 10.0,
    "planSpeedFactor": 0.9, "hoverBudget": 3.0, "flightPower": 150.0, "hoverPower": 170.0,
    "wakeHalfWidth": 20.0, "wifiIdleCurrent": 0.10, "supplyVoltage": 3.0, "bufferCapacity": 2000,
}


@dataclass
class EnvSettings:
    """One PPO variant. `simulation` is passed to ns-3 as --key=value, like an experiment."""
    seeds: list[int]
    simulation: dict = field(default_factory=dict)
    topology_config: Path = REPO / "configs" / "default.toml"
    num_sensors: int = 100
    k_max: int = K_MAX          # observation slots; networks with more clusters cannot be run
    areas: tuple = ()           # training: field sizes [m] to draw networks from, at the density of
                                # num_sensors per area_m^2 of topology_config; () = topology_config as is
    risk_in_obs: bool = False   # A2+: lateness quantile per cluster in the observation
    beta_d: float = 1.0         # delivered data
    beta_e: float = 0.2         # UAV flight + hover energy
    beta_m: float = 1.0         # missed scheduled meetings
    beta_c: float = 0.0         # CH Wi-Fi energy (all CH-capable nodes)
    beta_r: float = 0.0         # A4: lateness risk of the chosen cluster
    promise_factors: tuple = (1.0,)  # promise lengths (x P) the policy may choose; (1,) = fixed
    shaping: bool = False       # potential-based shaping on promises that can no longer be kept
    gamma: float = 0.99         # discount per t0 seconds, used by the shaping term
    t0: float = 15.0
    cache: Path = REPO / "results" / "rl_cache"


def network_size(s: EnvSettings, seed: int) -> tuple[int, float | None]:
    """(sensors, field size) of a training network. With `areas`, the seed picks the field size
    and the sensor count keeps the density of the base layout, so cluster counts vary."""
    if not s.areas:
        return s.num_sensors, None
    area = float(s.areas[seed % len(s.areas)])
    base = TopologyParams.from_toml(s.topology_config).area_m
    return round(s.num_sensors * (area / base) ** 2), area


def ensure_topology(s: EnvSettings, seed: int) -> Path:
    """Phase 0 output for (num_sensors, seed), built once and shared by all env processes."""
    n, area = network_size(s, seed)
    size = f"n{n}" if area is None else f"n{n}_a{area:g}"
    out = s.cache / "topologies" / Path(s.topology_config).stem / size / f"s{seed}"
    if not (out / "clusters.csv").exists():
        p = TopologyParams.from_toml(s.topology_config, num_sensors=n, seed=seed,
                                     area_m=area)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=out.parent))
        write_topology(tmp, p, *build_topology(p))
        try:
            tmp.rename(out)
        except OSError:  # another process finished first
            pass
    return out


def promise_period(meet: np.ndarray, tour: np.ndarray, sim: dict) -> float:
    """P of UavApp::PromisePeriod: one tour lap at planSpeedFactor*uavSpeed plus hoverBudget."""
    pts = meet[tour]
    legs = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    return float(np.sum(legs / (sim["planSpeedFactor"] * sim["uavSpeed"]) + sim["hoverBudget"]))


def parse(line: str) -> tuple[str, dict]:
    head, totals, *rest = line.split("|")
    h = head.split()
    msg = {"totals": np.array(totals.split(), dtype=float)}
    if h[0] == "D":
        msg.update(now=float(h[1]), current=int(h[2]), x=float(h[3]), y=float(h[4]),
                   clusters=np.array(rest[0].split(), dtype=float).reshape(-1, CLUSTER_FIELDS))
    return h[0], msg


class WsnUavEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, settings: EnvSettings, out_dir: Path | None = None):
        self.s = settings
        self.out_dir = out_dir  # keep metrics.json of every episode here (evaluation)
        self.observation_space = gym.spaces.Box(
            -np.inf, np.inf, (settings.k_max * SLOT_FEATURES + GLOBAL_FEATURES,), np.float32)
        self.nf = len(settings.promise_factors)
        self.action_space = gym.spaces.Discrete(settings.k_max * self.nf)
        self.proc: subprocess.Popen | None = None
        self.episode = 0
        self.seed_now = settings.seeds[0]

    # ---- episode control

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._close()
        options = options or {}
        self.seed_now = int(options.get("seed", self.np_random.choice(self.s.seeds)))
        self._load_topology(Path(options["topology"]) if "topology" in options
                            else ensure_topology(self.s, self.seed_now))
        self._spawn(options.get("out"))
        kind, msg = self._read()
        if kind != "D":
            raise RuntimeError("mission ended before the survey lap finished; raise simTime")
        self.prev_totals = msg["totals"]
        self.episode += 1
        return self._observe(msg), {}

    def step(self, action):
        if not self.mask[int(action)]:
            raise ValueError(f"masked action {action}")
        slot, j = divmod(int(action), self.nf)
        cluster = int(self.slot_cluster[slot])
        risk = self._risk(self.last_msg, cluster) if self.s.beta_r else 0.0
        before = self.last_msg
        factor = self.s.promise_factors[j]
        self.fact.write(f"{cluster} {factor}\n" if self.nf > 1 else f"{cluster}\n")
        self.fact.flush()
        kind, msg = self._read()
        reward, parts = self._reward(msg["totals"])
        self.prev_totals = msg["totals"]
        if self.s.beta_r:
            reward -= self.s.beta_r * risk
            parts["risk"] = risk
        now = msg.get("now", self.sim["simTime"])
        parts["dt"] = now - before["now"]
        if self.s.shaping:
            # F = gamma^(dt/t0) * Phi(s') - Phi(s), Phi = -beta_m * (promises already unkeepable).
            # Potential-based, so it does not change which policy is optimal (Ng et al. 1999);
            # it charges a broken promise when it becomes unavoidable, not when its window closes.
            phi_after = 0.0 if kind == "E" else self._potential(msg)
            f = self.s.gamma ** (parts["dt"] / self.s.t0) * phi_after - self._potential(before)
            reward += f
            parts["shaping"] = f
        if kind == "E":
            self._finish()
            return np.zeros(self.observation_space.shape, np.float32), reward, True, False, parts
        return self._observe(msg), reward, False, False, parts

    def action_masks(self) -> np.ndarray:
        return self.mask.copy()

    def expert_action(self) -> int:
        """Action of the tour here: the successor of the current cluster in tour order, with the
        standard promise (1 x P). Used as the teacher for warm-starting from the tour."""
        cur = self.last_msg["current"]
        target = self.tour[0] if cur < 0 else self.tour_next[cur]
        slot = int(np.flatnonzero(self.slot_cluster == target)[0])
        return slot * self.nf + list(self.s.promise_factors).index(1.0)

    def close(self):
        self._close()

    # ---- ns-3 process

    def _load_topology(self, topo: Path) -> None:
        self.topo = topo
        c = np.genfromtxt(topo / "clusters.csv", delimiter=",", names=True)
        self.meet = np.column_stack([c["meet_x"], c["meet_y"]])
        tour = np.empty(len(c), dtype=int)
        tour[c["tour_index"].astype(int)] = c["cluster_id"].astype(int)
        self.K = len(c)
        self.tour = tour
        self.tour_next = np.empty(self.K, dtype=int)
        self.tour_next[tour] = np.roll(tour, -1)
        if self.K > self.s.k_max:
            raise ValueError(f"{self.K} clusters > k_max={self.s.k_max}")
        n = sum(1 for _ in open(topo / "nodes.csv")) - 1
        self.sim = {**SIM_DEFAULTS, **self.s.simulation}
        self.P = promise_period(self.meet, tour, self.sim)
        self.span = float(np.abs(self.meet).max()) or 1.0
        # Readings generated network-wide during one average stop: the data scale.
        self.d_scale = n * self.sim["readingRate"] * self.P / self.K
        self.e_scale = self.sim["hoverPower"] * self.P / self.K
        # Energy of one CH listening through one fixed scheduled window (2 w idle).
        self.c_scale = (2 * self.sim["wakeHalfWidth"] * self.sim["wifiIdleCurrent"]
                        * self.sim["supplyVoltage"])

    def _spawn(self, out: Path | None) -> None:
        obs_r, obs_w = os.pipe()
        act_r, act_w = os.pipe()
        if out is None:
            out = self.out_dir / f"s{self.seed_now}" if self.out_dir else \
                self.s.cache / "episodes" / f"pid{os.getpid()}"
        sim = {**self.s.simulation, "routing": "external", "seed": self.seed_now,
               "topologyDir": str(self.topo), "outDir": str(out),
               "bridgeFdIn": act_r, "bridgeFdOut": obs_w}
        self.log = tempfile.NamedTemporaryFile("w+", prefix="wsn-uav-", suffix=".log", delete=False)
        self.proc = subprocess.Popen([str(ns3_binary())] + sim_args(sim), cwd=REPO,
                                     pass_fds=(act_r, obs_w), stdout=self.log, stderr=self.log)
        os.close(obs_w)
        os.close(act_r)
        self.fobs = os.fdopen(obs_r, "r")
        self.fact = os.fdopen(act_w, "w")

    def _read(self) -> tuple[str, dict]:
        line = self.fobs.readline()
        if not line:
            self.proc.wait()
            self.log.seek(0)
            raise RuntimeError(f"ns-3 exited ({self.proc.returncode}):\n{self.log.read()[-2000:]}")
        return parse(line)

    def _finish(self) -> None:
        self.fact.close()
        self.fobs.close()
        if self.proc.wait() != 0:
            self.log.seek(0)
            raise RuntimeError(f"ns-3 failed ({self.proc.returncode}):\n{self.log.read()[-2000:]}")
        self._close()

    def _close(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            for f in (self.fact, self.fobs, self.log):
                try:
                    f.close()
                except OSError:
                    pass
            os.unlink(self.log.name)
            self.proc = None

    # ---- MDP (docs/MDP.md)

    def _observe(self, msg: dict) -> np.ndarray:
        self.last_msg = msg
        now, x, y, cur = msg["now"], msg["x"], msg["y"], msg["current"]
        cl = msg["clusters"]
        travel = np.hypot(cl[:, 0] - x, cl[:, 1] - y) / self.sim["uavSpeed"]
        is_cur = np.arange(self.K) == cur
        order = np.lexsort((travel, is_cur))  # nearest first, current cluster last
        self.slot_cluster = np.full(self.s.k_max, -1)
        self.slot_cluster[:self.K] = order
        slot_mask = np.zeros(self.s.k_max, bool)
        slot_mask[:self.K] = ~is_cur[order]
        self.mask = np.repeat(slot_mask, self.nf)  # action = slot * nf + promise-factor index

        P = self.P
        never = cl[:, 8] > 0.5
        promised = cl[:, 6] >= 0
        slack = np.where(promised, cl[:, 6] - travel, 0.0)
        f = np.zeros((self.s.k_max, SLOT_FEATURES), np.float32)
        f[:self.K] = np.column_stack([
            np.ones(self.K),
            travel / P,
            (cl[:, 0] - x) / self.span,
            (cl[:, 1] - y) / self.span,
            np.minimum(cl[:, 2] / self.d_scale, 5.0),
            cl[:, 3] * P / self.d_scale,
            np.where(never, 1.0, cl[:, 4] / self.sim["initialEnergy"]),
            np.minimum(np.where(never, now, cl[:, 5]) / P, 5.0),
            promised,
            np.clip(slack / P, -2.0, 2.0),
            np.minimum(cl[:, 7] / 5.0, 1.0),
            never,
            cl[:, 9] / P if self.s.risk_in_obs else np.zeros(self.K),
        ])[order]
        g = np.array([now / self.sim["simTime"], x / self.span, y / self.span], np.float32)
        return np.concatenate([f.ravel(), g])

    def _reward(self, totals: np.ndarray) -> tuple[float, dict]:
        d = totals - self.prev_totals
        data = d[0] / self.d_scale
        uav = (d[4] * self.sim["flightPower"] + d[5] * self.sim["hoverPower"]) / self.e_scale
        missed = d[2]
        ch = d[6] / self.c_scale
        r = (self.s.beta_d * data - self.s.beta_e * uav - self.s.beta_m * missed
             - self.s.beta_c * ch)
        return float(r), {"data": data, "uav_energy": uav, "missed": missed, "ch_energy": ch}

    def _late_width(self, cl: np.ndarray) -> np.ndarray:
        return cl[:, 9] if self.sim.get("adaptiveWindow", True) else \
            np.full(len(cl), self.sim["wakeHalfWidth"])

    def _potential(self, msg: dict) -> float:
        """-beta_m x number of outstanding promises the UAV can no longer keep even by flying
        straight there now (arrival after the end of the CH's listening window)."""
        cl = msg["clusters"]
        travel = np.hypot(cl[:, 0] - msg["x"], cl[:, 1] - msg["y"]) / self.sim["uavSpeed"]
        lost = (cl[:, 6] >= 0) & (travel > cl[:, 6] + self._late_width(cl))
        return -self.s.beta_m * float(lost.sum())

    def _risk(self, msg: dict, k: int) -> float:
        """Lateness risk of flying to cluster k now (eq. 30 in spirit): how far a pessimistic
        arrival (flight time + lateness quantile) would fall after the end of k's listening
        window, in units of P. 0 if k has no outstanding promise. Uses only UAV-side estimates.
        With the adaptive window the late width is that same quantile, so this is the nominal
        lateness beyond the promise; with the fixed window it is the quantile beyond +w."""
        c = msg["clusters"][k]
        if c[6] < 0:
            return 0.0
        travel = np.hypot(c[0] - msg["x"], c[1] - msg["y"]) / self.sim["uavSpeed"]
        late_width = c[9] if self.sim.get("adaptiveWindow", True) else self.sim["wakeHalfWidth"]
        return float(max(0.0, travel + c[9] - (c[6] + late_width)) / self.P)


def make_env(settings: EnvSettings, rank: int = 0, out_dir: Path | None = None):
    def _init():
        return WsnUavEnv(settings, out_dir)
    return _init
