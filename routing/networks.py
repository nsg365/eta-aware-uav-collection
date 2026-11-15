"""Per-cluster scoring networks (attention-style) for the Phase 3 policies.

The plain MLP policy reads the padded slots as one long vector, so it has to learn the same
rule ("go where the promise is due") separately for every slot position. Here every slot is
encoded by the same small network, one self-attention layer lets each cluster see the others,
and the same head scores each slot. The output does not depend on slot order or cluster count.
Used by PPO (ClusterScoringPolicy) and DQN (routing/dqn.py, as the Q-network).
"""

from __future__ import annotations

import torch
from torch import nn
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy

from routing.env import GLOBAL_FEATURES, SLOT_FEATURES


def slot_count(obs_dim: int) -> int:
    return (obs_dim - GLOBAL_FEATURES) // SLOT_FEATURES


def split(obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Flat observation -> slot features (B, K, F), global features (B, G), padding mask."""
    k = slot_count(obs.shape[1])
    slots = obs[:, :k * SLOT_FEATURES].reshape(-1, k, SLOT_FEATURES)
    return slots, obs[:, k * SLOT_FEATURES:], slots[..., 0] < 0.5


class ClusterEncoder(nn.Module):
    def __init__(self, d: int = 64, heads: int = 4, layers: int = 1):
        super().__init__()
        self.embed = nn.Sequential(nn.Linear(SLOT_FEATURES + GLOBAL_FEATURES, d), nn.ReLU(),
                                   nn.Linear(d, d))
        self.attn = nn.ModuleList(
            nn.TransformerEncoderLayer(d, heads, 2 * d, dropout=0.0, batch_first=True)
            for _ in range(layers))

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        slots, g, pad = split(obs)
        h = self.embed(torch.cat([slots, g[:, None, :].expand(-1, slots.shape[1], -1)], dim=-1))
        for layer in self.attn:
            h = layer(h, src_key_padding_mask=pad)
        return h, g, pad


def score_head(d: int, n_out: int = 1) -> nn.Sequential:
    head = nn.Sequential(nn.Linear(d, d), nn.ReLU(), nn.Linear(d, n_out))
    nn.init.uniform_(head[-1].weight, -1e-3, 1e-3)  # start close to uniform over clusters
    nn.init.zeros_(head[-1].bias)
    return head


class ClusterScorer(nn.Module):
    """n_out scores per slot (one per promise factor), flattened slot-major to match the env's
    action = slot * n_out + factor index: PPO logits or DQN Q-values."""

    def __init__(self, d: int = 64, heads: int = 4, layers: int = 1, n_out: int = 1):
        super().__init__()
        self.encoder = ClusterEncoder(d, heads, layers)
        self.head = score_head(d, n_out)

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        h, _, _ = self.encoder(obs)
        return self.head(h).flatten(1)


class ActorCriticExtractor(nn.Module):
    """SB3 mlp_extractor: latent_pi is already the k slot scores; latent_vf a pooled code."""

    def __init__(self, k: int, d: int = 64, heads: int = 4, layers: int = 1, n_out: int = 1):
        super().__init__()
        self.actor = ClusterScorer(d, heads, layers, n_out)
        self.critic_encoder = ClusterEncoder(d, heads, layers)
        self.critic = nn.Sequential(nn.Linear(d + GLOBAL_FEATURES, d), nn.ReLU())
        self.latent_dim_pi = k * n_out
        self.latent_dim_vf = d

    def forward(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.forward_actor(features), self.forward_critic(features)

    def forward_actor(self, features: torch.Tensor) -> torch.Tensor:
        return self.actor(features)

    def forward_critic(self, features: torch.Tensor) -> torch.Tensor:
        h, g, pad = self.critic_encoder(features)
        keep = (~pad).unsqueeze(-1).float()
        pooled = (h * keep).sum(1) / keep.sum(1).clamp(min=1.0)
        return self.critic(torch.cat([pooled, g], dim=-1))


class ClusterScoringPolicy(MaskableActorCriticPolicy):
    """MaskablePPO policy whose action logits are the per-slot scores (no final linear layer)."""

    def __init__(self, *args, d: int = 64, heads: int = 4, layers: int = 1, **kwargs):
        self._arch = {"d": d, "heads": heads, "layers": layers}
        kwargs["ortho_init"] = False
        super().__init__(*args, **kwargs)

    def _build_mlp_extractor(self) -> None:
        k = slot_count(self.observation_space.shape[0])
        self.mlp_extractor = ActorCriticExtractor(k, **self._arch, n_out=self.action_space.n // k)

    def _build(self, lr_schedule) -> None:
        super()._build(lr_schedule)
        self.action_net = nn.Identity()
        self.optimizer = self.optimizer_class(self.parameters(), lr=lr_schedule(1),
                                              **self.optimizer_kwargs)

    def _get_constructor_parameters(self) -> dict:
        return {**super()._get_constructor_parameters(), **self._arch}
