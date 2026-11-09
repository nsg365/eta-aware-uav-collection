"""Phase 0 (offline): sensor placement, DBSCAN clustering, CH election and survey tour.

Implements Sec. III-B of the proposal on surveyed positions. Output files are the
interface consumed by the NS-3 simulation (see docs/INTERFACES.md):

    nodes.csv     node_id,x,y,cluster_id,role          role in {primary, backup, member}
    clusters.csv  cluster_id,meet_x,meet_y,primary_id,backup_id,size,tour_index
    meta.json     parameters and clustering diagnostics

Deviations from the proposal text are recorded in docs/DESIGN_DECISIONS.md (D3-D6).
"""

from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN, KMeans


@dataclass
class TopologyParams:
    num_sensors: int = 100
    area_m: float = 500.0
    seed: int = 1
    deployment_mode: str = "uniform"  # uniform | gaussian_hotspot
    hotspot_count: int = 4
    hotspot_std_m: float = 25.0
    sensor_range_m: float = 60.0  # R_s: 802.15.4 member-to-CH range
    dbscan_kappa: float = 0.8  # eps = kappa * R_s  (kappa <= 1)
    dbscan_min_samples: int = 3
    uav_range_m: float = 80.0  # R_UAV: horizontal CH-to-meeting-point coverage radius
    alpha: float = 0.5  # CH score weight on residual energy
    min_candidates: int = 2  # primary + backup (proposal says 3; see D4)
    depot_x: float = 0.0
    depot_y: float = 0.0

    @classmethod
    def from_toml(cls, path: Path, **overrides) -> "TopologyParams":
        with open(path, "rb") as f:
            section = tomllib.load(f).get("topology", {})
        section.update({k: v for k, v in overrides.items() if v is not None})
        unknown = set(section) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown [topology] keys in {path}: {sorted(unknown)}")
        return cls(**section)


@dataclass
class Cluster:
    members: np.ndarray  # sensor indices
    meet: np.ndarray  # meeting point p_k (centroid), eq. (1)
    primary: int = -1
    backup: int = -1


# def generate_positions(p: TopologyParams) -> np.ndarray:
#     rng = np.random.default_rng(p.seed)
#     return rng.uniform(0.0, p.area_m, size=(p.num_sensors, 2))

def generate_positions(p: TopologyParams) -> np.ndarray:
    """Generate uniform or Gaussian-hotspot sensor positions."""
    rng = np.random.default_rng(p.seed)

    if p.deployment_mode == "uniform":
        return rng.uniform(0.0, p.area_m, size=(p.num_sensors, 2))

    if p.deployment_mode == "gaussian_hotspot":
        if p.hotspot_count < 1:
            raise ValueError("hotspot_count must be at least 1")
        if p.hotspot_std_m <= 0:
            raise ValueError("hotspot_std_m must be positive")

        centers = rng.uniform(
            0.0, p.area_m, size=(p.hotspot_count, 2)
        )

        assignments = rng.integers(
            0, p.hotspot_count, size=p.num_sensors
        )

        pos = centers[assignments] + rng.normal(
            loc=0.0,
            scale=p.hotspot_std_m,
            size=(p.num_sensors, 2)
        )

        # Keep all sensors inside the deployment area.
        return np.clip(pos, 0.0, p.area_m)

    raise ValueError(
        f"Unknown deployment mode: {p.deployment_mode}"
    )

def feasible_candidates(pos: np.ndarray, members: np.ndarray, meet: np.ndarray,
                        p: TopologyParams) -> np.ndarray:
    """Eq. (2): reach every member over 802.15.4 and be reachable from p_k by the UAV."""
    pts = pos[members]
    pairwise = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    ok = (pairwise.max(axis=1) <= p.sensor_range_m) & (
        np.linalg.norm(pts - meet, axis=1) <= p.uav_range_m)
    return members[ok]


def ch_score(pos: np.ndarray, cand: np.ndarray, meet: np.ndarray, energy: np.ndarray,
             e_max: float, p: TopologyParams) -> np.ndarray:
    """Eq. (3) with the distance term normalised to [0, 1] (decision D3)."""
    d = np.linalg.norm(pos[cand] - meet, axis=1)
    return p.alpha * energy[cand] / e_max + (1.0 - p.alpha) * (1.0 - d / p.uav_range_m)


def _attach_noise(pos: np.ndarray, labels: np.ndarray, p: TopologyParams) -> np.ndarray:
    """Noise joins the cluster of its nearest clustered sensor if within R_s, else a singleton."""
    labels = labels.copy()
    next_label = labels.max() + 1
    clustered = np.flatnonzero(labels >= 0)
    for i in np.flatnonzero(labels < 0):
        if clustered.size:
            d = np.linalg.norm(pos[clustered] - pos[i], axis=1)
            j = int(np.argmin(d))
            if d[j] <= p.sensor_range_m:
                labels[i] = labels[clustered[j]]
                continue
        labels[i] = next_label
        next_label += 1
    return labels


def build_clusters(pos: np.ndarray, p: TopologyParams) -> tuple[list[Cluster], dict]:
    eps = p.dbscan_kappa * p.sensor_range_m
    labels = DBSCAN(eps=eps, min_samples=p.dbscan_min_samples).fit_predict(pos)
    n_noise = int((labels < 0).sum())
    labels = _attach_noise(pos, labels, p)

    # Split any cluster with too few feasible CH candidates (2-means, recursively).
    # Terminates: a singleton is always feasible (its own centroid, zero diameter).
    pending = [np.flatnonzero(labels == lab) for lab in np.unique(labels)]
    clusters: list[Cluster] = []
    n_splits = 0
    while pending:
        members = pending.pop()
        meet = pos[members].mean(axis=0)
        need = min(p.min_candidates, len(members))
        if len(feasible_candidates(pos, members, meet, p)) >= need:
            clusters.append(Cluster(members=members, meet=meet))
            continue
        km = KMeans(n_clusters=2, n_init=10, random_state=p.seed).fit(pos[members])
        pending += [members[km.labels_ == 0], members[km.labels_ == 1]]
        n_splits += 1

    clusters.sort(key=lambda c: int(c.members.min()))  # deterministic cluster ids
    diag = {"dbscan_eps_m": eps, "dbscan_noise_points": n_noise, "feasibility_splits": n_splits}
    return clusters, diag


def elect(pos: np.ndarray, clusters: list[Cluster], p: TopologyParams) -> None:
    """Initial election with full batteries: the energy term is equal, so distance decides."""
    energy = np.ones(len(pos))
    for c in clusters:
        cand = feasible_candidates(pos, c.members, c.meet, p)
        order = cand[np.argsort(-ch_score(pos, cand, c.meet, energy, 1.0, p), kind="stable")]
        c.primary = int(order[0])
        c.backup = int(order[1]) if len(order) > 1 else -1


def survey_tour(depot: np.ndarray, points: np.ndarray) -> tuple[list[int], float]:
    """Closed depot->clusters->depot tour: nearest neighbour followed by 2-opt."""
    k = len(points)
    nodes = np.vstack([depot, points])  # index 0 is the depot
    dist = np.linalg.norm(nodes[:, None] - nodes[None, :], axis=-1)
    tour, left = [0], set(range(1, k + 1))
    while left:
        nxt = min(left, key=lambda j: dist[tour[-1], j])
        tour.append(nxt)
        left.remove(nxt)
    tour.append(0)

    improved = True
    while improved:
        improved = False
        for i in range(1, len(tour) - 2):
            for j in range(i + 1, len(tour) - 1):
                a, b, c, d = tour[i - 1], tour[i], tour[j], tour[j + 1]
                if dist[a, c] + dist[b, d] < dist[a, b] + dist[c, d] - 1e-9:
                    tour[i:j + 1] = reversed(tour[i:j + 1])
                    improved = True
    length = float(sum(dist[tour[i], tour[i + 1]] for i in range(len(tour) - 1)))
    return [t - 1 for t in tour[1:-1]], length


def build_topology(p: TopologyParams) -> tuple[np.ndarray, list[Cluster], list[int], dict]:
    pos = generate_positions(p)
    clusters, diag = build_clusters(pos, p)
    elect(pos, clusters, p)
    order, length = survey_tour(np.array([p.depot_x, p.depot_y]),
                                np.array([c.meet for c in clusters]))
    diag.update(num_clusters=len(clusters), tour_length_m=length,
                clusters_without_backup=sum(c.backup < 0 for c in clusters))
    return pos, clusters, order, diag


def write_topology(out: Path, p: TopologyParams, pos, clusters, order, diag) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cluster_of = np.empty(len(pos), dtype=int)
    for k, c in enumerate(clusters):
        cluster_of[c.members] = k
    role = np.array(["member"] * len(pos), dtype=object)
    for c in clusters:
        role[c.primary] = "primary"
        if c.backup >= 0:
            role[c.backup] = "backup"
    with open(out / "nodes.csv", "w") as f:
        f.write("node_id,x,y,cluster_id,role\n")
        for i, (x, y) in enumerate(pos):
            f.write(f"{i},{x:.3f},{y:.3f},{cluster_of[i]},{role[i]}\n")
    tour_index = {k: idx for idx, k in enumerate(order)}
    with open(out / "clusters.csv", "w") as f:
        f.write("cluster_id,meet_x,meet_y,primary_id,backup_id,size,tour_index\n")
        for k, c in enumerate(clusters):
            f.write(f"{k},{c.meet[0]:.3f},{c.meet[1]:.3f},{c.primary},{c.backup},"
                    f"{len(c.members)},{tour_index[k]}\n")
    (out / "depot.csv").write_text(f"depot_x,depot_y\n{p.depot_x:.3f},{p.depot_y:.3f}\n")
    (out / "meta.json").write_text(json.dumps({"params": asdict(p), **diag}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--num-sensors", type=int)
    a = ap.parse_args()
    p = TopologyParams.from_toml(a.config, seed=a.seed, num_sensors=a.num_sensors)
    pos, clusters, order, diag = build_topology(p)
    write_topology(a.out, p, pos, clusters, order, diag)
    print(json.dumps(diag))


if __name__ == "__main__":
    main()
