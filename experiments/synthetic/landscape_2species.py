"""2-species toy landscape (per data/synthetic_landscape_spec.md §1).

Genome length L=8 binary; G^A = (1,1,1,1,0,0,0,*), G^B = (0,0,0,0,1,1,1,*).
Niches A and B; 6 epistatic edges; 1 lineage-divergent edge (1,5).

Analytical truths (per spec §1.3-1.4):
  F_A(G^A) = 1.05,  F_B(G^A) = 0.55,  F_ρ(G^A) = 0.80
  F_A(G^B) = 0.65,  F_B(G^B) = 0.85,  F_ρ(G^B) = 0.75
  E[F(hybrid)] = 0.2625
  HFL_AB = 0.661
  RII_AB = 0.661 (numerical coincidence in this toy)

Implementation must reproduce these ± 5%.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Any

import numpy as np


# ---------- 1. single-locus utility ----------
def _u_A(locus: int, val: int) -> float:
    if locus in (0, 1, 2, 3):  # 1..4 in spec, 0-indexed
        return 0.10 if val == 1 else 0.00
    if locus in (4, 5, 6):  # 5..7
        return 0.05 if val == 0 else 0.05
    return 0.0  # noise


def _u_B(locus: int, val: int) -> float:
    if locus in (0, 1, 2, 3):
        return 0.05 if val == 0 else 0.05
    if locus in (4, 5, 6):
        return 0.10 if val == 1 else 0.00
    return 0.0


# ---------- 2. epistasis edges + interactions ----------
# Spec §1.2: edges (1,2),(2,3),(3,4) — A-internal; (5,6),(6,7) — B-internal; (1,5) — divergent
# 0-indexed: (0,1),(1,2),(2,3); (4,5),(5,6); (0,4)
A_INTERNAL_EDGES = [(0, 1), (1, 2), (2, 3)]
B_INTERNAL_EDGES = [(4, 5), (5, 6)]
DIVERGENT_EDGES = [(0, 4)]


def _J_edge(edge: tuple[int, int], g_l: int, g_r: int, niche: str) -> float:
    same = (g_l == g_r)
    if edge in A_INTERNAL_EDGES:
        if niche == "A":
            return 0.15 if same else -0.20
        return 0.0  # in E_B
    if edge in B_INTERNAL_EDGES:
        if niche == "B":
            return 0.15 if same else -0.20
        return 0.0
    if edge in DIVERGENT_EDGES:
        return -0.10 if same else 0.05
    return 0.0


def fitness_niche(G: tuple[int, ...] | list[int], niche: str) -> float:
    """F_e(G) = sum_u + sum_J."""
    L = len(G)
    if niche == "A":
        u_sum = sum(_u_A(l, G[l]) for l in range(L))
    else:
        u_sum = sum(_u_B(l, G[l]) for l in range(L))
    j_sum = 0.0
    for edge in A_INTERNAL_EDGES + B_INTERNAL_EDGES + DIVERGENT_EDGES:
        l, r = edge
        j_sum += _J_edge(edge, G[l], G[r], niche)
    return u_sum + j_sum


def fitness_rho(G, rho_A: float = 0.5, rho_B: float = 0.5) -> float:
    return rho_A * fitness_niche(G, "A") + rho_B * fitness_niche(G, "B")


# ---------- 3. crossover + hybrid sampling ----------
def uniform_50_50_crossover(G_A, G_B, rng: random.Random) -> tuple[int, ...]:
    return tuple(G_A[i] if rng.random() < 0.5 else G_B[i] for i in range(len(G_A)))


def sample_hybrid_fitness(G_A, G_B, N: int = 500, seed: int = 42) -> dict[str, float]:
    rng = random.Random(seed)
    samples = []
    for _ in range(N):
        h = uniform_50_50_crossover(G_A, G_B, rng)
        samples.append(fitness_rho(h))
    return {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "n": N,
        "samples": samples,
    }


# ---------- 4. RII / HFL ----------
def hfl(G_A, G_B, hybrid_mean_fit: float) -> float:
    """HFL = 1 - E[F(hybrid)] / (0.5*(F_A + F_B))."""
    F_A = fitness_rho(G_A)
    F_B = fitness_rho(G_B)
    parent_mean = 0.5 * (F_A + F_B)
    if parent_mean <= 0:
        return 0.0
    return 1.0 - hybrid_mean_fit / parent_mean


def rii(K_AA: float, K_BB: float, K_AB: float, eps: float = 1e-9) -> float:
    return 1.0 - K_AB / (np.sqrt(K_AA * K_BB) + eps)


# Continuous viability V = (F - F_min) / (F_max - F_min) with F_min=0, F_max=1 per spec §1.4
def viability(F: float, F_min: float = 0.0, F_max: float = 1.0) -> float:
    if F_max <= F_min:
        return 0.0
    return max(0.0, min(1.0, (F - F_min) / (F_max - F_min)))


# ---------- 5. main 2-species ground truth ----------
G_A_MAIN: tuple[int, ...] = (1, 1, 1, 1, 0, 0, 0, 0)
G_B_MAIN: tuple[int, ...] = (0, 0, 0, 0, 1, 1, 1, 0)


def compute_main_case(N: int = 500, seed: int = 42) -> dict[str, Any]:
    F_A = fitness_rho(G_A_MAIN)
    F_B = fitness_rho(G_B_MAIN)
    hybrid_AB = sample_hybrid_fitness(G_A_MAIN, G_B_MAIN, N=N, seed=seed)
    # Self-cross for K_AA, K_BB (each parent crossed with a clone, V = ~F_parent)
    hybrid_AA = sample_hybrid_fitness(G_A_MAIN, G_A_MAIN, N=N, seed=seed + 1)
    hybrid_BB = sample_hybrid_fitness(G_B_MAIN, G_B_MAIN, N=N, seed=seed + 2)
    K_AA = viability(hybrid_AA["mean"])
    K_BB = viability(hybrid_BB["mean"])
    K_AB = viability(hybrid_AB["mean"])
    return {
        "F_A": F_A, "F_B": F_B,
        "E_F_hybrid": hybrid_AB["mean"],
        "E_F_hybrid_std": hybrid_AB["std"],
        "K_AA": K_AA, "K_BB": K_BB, "K_AB": K_AB,
        "HFL_AB": hfl(G_A_MAIN, G_B_MAIN, hybrid_AB["mean"]),
        "RII_AB": rii(K_AA, K_BB, K_AB),
        "n_samples": N,
    }


# ---------- 6. RCC on 12 agents (Case 6) ----------
def build_12_agent_population(seed: int = 42) -> list[tuple[int, ...]]:
    """6 A-lineage + 6 B-lineage, noise locus 8 random."""
    rng = random.Random(seed)
    A_template = list(G_A_MAIN[:7])
    B_template = list(G_B_MAIN[:7])
    pop = []
    for _ in range(6):
        pop.append(tuple(A_template + [rng.randint(0, 1)]))
    for _ in range(6):
        pop.append(tuple(B_template + [rng.randint(0, 1)]))
    return pop


def estimate_rcm(pop: list[tuple[int, ...]], R: int = 8, seed: int = 42) -> np.ndarray:
    n = len(pop)
    rng = random.Random(seed)
    rcm = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                rcm[i, j] = viability(fitness_rho(pop[i]))
                continue
            vals = []
            for r in range(R):
                child = uniform_50_50_crossover(pop[i], pop[j], rng)
                vals.append(viability(fitness_rho(child)))
            rcm[i, j] = float(np.mean(vals))
    return rcm


def rcc_cluster(rcm: np.ndarray, n_clusters: int = 2) -> np.ndarray:
    """Spectral clustering on similarity matrix (rcm)."""
    from sklearn.cluster import SpectralClustering
    sc = SpectralClustering(
        n_clusters=n_clusters,
        affinity="precomputed",
        assign_labels="kmeans",
        random_state=42,
    )
    # ensure symmetric, non-negative
    sym = 0.5 * (rcm + rcm.T)
    sym = np.clip(sym, 0.0, None)
    return sc.fit_predict(sym)


def adjusted_rand_index(labels_true: list[int], labels_pred: list[int]) -> float:
    from sklearn.metrics import adjusted_rand_score
    return float(adjusted_rand_score(labels_true, labels_pred))
