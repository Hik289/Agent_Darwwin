"""M-family landscape: HFL ≈ M · p_min · δ̄ (Thm 1 验证).

Per data/synthetic_landscape_spec.md §2:
- L=64 binary genome
- Lineage A: locus 0..31 = 1, 32..63 = 0
- Lineage B: locus 0..31 = 0, 32..63 = 1
- Small additive utility u ∈ [0, 0.05] uniform (seed=42)
- M lineage-divergent edges (random ℓ ∈ 0..31, r ∈ 32..63), J: same-allele +0.05 → -0.05 different
  → δ_lr = 0.10 each
- 50 within-lineage filler edges (no cross-lineage interaction; don't affect L_AB)
- p_min = 0.5 (uniform 50-50 crossover)

Theoretical L_AB(M) = 0.05 · M.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import numpy as np


L = 64
M_GRID = [2, 4, 8, 16, 32]


def make_landscape(M: int, seed: int = 42) -> dict[str, Any]:
    """Build a landscape with exactly M lineage-divergent edges."""
    rng = random.Random(seed)
    # additive utility: u_l in [0, 0.05] uniform — symmetric between niches
    u = [rng.uniform(0.0, 0.05) for _ in range(L)]
    # Lineage-divergent edges: pick M distinct (l, r) with l in 0..31, r in 32..63
    cross_edges_pool = [(l, r) for l in range(32) for r in range(32, 64)]
    rng.shuffle(cross_edges_pool)
    divergent = cross_edges_pool[:M]
    # 50 within-lineage filler edges (l, r both in 0..31 or both in 32..63)
    filler_pool = ([(l, r) for l in range(32) for r in range(32) if l < r]
                   + [(l, r) for l in range(32, 64) for r in range(32, 64) if l < r])
    rng.shuffle(filler_pool)
    filler = filler_pool[:50]
    return {"M": M, "u": u, "divergent_edges": divergent, "filler_edges": filler, "seed": seed}


def fitness(G: tuple[int, ...], landscape: dict[str, Any]) -> float:
    """F(G) = sum u_l + sum_J.

    Per data/synthetic_landscape_spec.md §2.2:
      - divergent edges (M of them): J = -0.05 if same allele, +0.05 if different
        ⇒ δ_lr = 0.10, contributes to L_AB
      - 50 filler edges within-lineage: do NOT affect L_AB
        (we model them as adding the SAME constant to all genomes — i.e., they don't
        depend on G; this satisfies the spec "不影响 L_AB" exactly.)

    L_AB equals the recombination load from M divergent edges only:
      L_AB = M · p_min · δ̄ = M · 0.5 · 0.10 = 0.05·M
    """
    u = landscape["u"]
    F_val = sum(u[l] for l in range(L) if G[l] == 1)
    for (l, r) in landscape["divergent_edges"]:
        same = (G[l] == G[r])
        F_val += -0.05 if same else 0.05
    # Filler edges: contribute a constant (no lineage dependence) so they don't show in L_AB.
    # We omit them entirely from fitness — adding a constant 50*0=0 by convention.
    return F_val


def make_parent_AB() -> tuple[tuple[int, ...], tuple[int, ...]]:
    A = tuple([1] * 32 + [0] * 32)
    B = tuple([0] * 32 + [1] * 32)
    return A, B


def uniform_crossover(A, B, rng: random.Random) -> tuple[int, ...]:
    return tuple(A[i] if rng.random() < 0.5 else B[i] for i in range(L))


def estimate_L_AB(landscape: dict[str, Any], N: int = 200, seed: int = 42) -> dict[str, Any]:
    """Estimate empirical L_AB = parent_mean_F - hybrid_mean_F (recombination load)."""
    rng = random.Random(seed)
    A, B = make_parent_AB()
    F_A = fitness(A, landscape)
    F_B = fitness(B, landscape)
    parent_mean = 0.5 * (F_A + F_B)
    hybrid_fits = []
    for _ in range(N):
        h = uniform_crossover(A, B, rng)
        hybrid_fits.append(fitness(h, landscape))
    hybrid_mean = float(np.mean(hybrid_fits))
    hybrid_std = float(np.std(hybrid_fits))
    L_AB = parent_mean - hybrid_mean
    return {
        "M": landscape["M"], "F_A": F_A, "F_B": F_B, "parent_mean": parent_mean,
        "hybrid_mean": hybrid_mean, "hybrid_std": hybrid_std,
        "L_AB_measured": L_AB,
        "L_AB_predicted": 0.05 * landscape["M"],
        "residual_abs": abs(L_AB - 0.05 * landscape["M"]),
        "residual_pct": abs(L_AB - 0.05 * landscape["M"]) / max(0.05 * landscape["M"], 1e-9) * 100,
        "n_samples": N,
    }


def run_M_sweep(M_grid: list[int] | None = None, N: int = 200, seed: int = 42) -> dict[str, Any]:
    M_grid = M_grid or M_GRID
    results = []
    for M in M_grid:
        lscape = make_landscape(M, seed=seed)
        res = estimate_L_AB(lscape, N=N, seed=seed)
        results.append(res)
    return {"M_sweep": results, "N_per_M": N, "seed": seed}


def linear_regress(M_sweep: list[dict[str, Any]]) -> dict[str, Any]:
    """L_AB = a*M + b. OLS."""
    Ms = np.array([r["M"] for r in M_sweep], dtype=float)
    Ys = np.array([r["L_AB_measured"] for r in M_sweep], dtype=float)
    # least squares
    A_mat = np.vstack([Ms, np.ones_like(Ms)]).T
    slope, intercept = np.linalg.lstsq(A_mat, Ys, rcond=None)[0]
    pred = slope * Ms + intercept
    ss_res = float(np.sum((Ys - pred) ** 2))
    ss_tot = float(np.sum((Ys - np.mean(Ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    # bootstrap CI on slope (B=1000)
    rng = np.random.default_rng(42)
    boot_slopes = []
    n = len(Ms)
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        bM = Ms[idx]; bY = Ys[idx]
        Ab = np.vstack([bM, np.ones_like(bM)]).T
        if np.linalg.matrix_rank(Ab) < 2:
            continue
        s, _ = np.linalg.lstsq(Ab, bY, rcond=None)[0]
        boot_slopes.append(s)
    boot_slopes = np.array(boot_slopes)
    return {
        "slope": float(slope), "intercept": float(intercept), "R2": float(r2),
        "slope_ci_lo": float(np.quantile(boot_slopes, 0.025)),
        "slope_ci_hi": float(np.quantile(boot_slopes, 0.975)),
        "slope_ci_method": "bootstrap_1000",
    }


def alpha_estimate(slope: float, p_min: float = 0.5, delta_bar: float = 0.10) -> float:
    """slope = 2/L * p_min * delta_bar  (Lemma 6, here L = M scale)
    Actually for this M-family with fixed L=64 and M as control variable, slope = p_min * delta_bar.
    So α isn't directly estimated here — we just verify slope ≈ 0.05.
    α (Orr quadratic scaling constant) is estimated separately by varying L not M.
    Return the *theory-consistency* check: |slope - 0.05| / 0.05.
    """
    return abs(slope - 0.05) / 0.05


def compute_L_c(tau_v: float, F_bar: float, alpha: float, p_min: float = 0.5,
                delta_bar: float = 0.10) -> int:
    """Thm 4 closed-form: L_c = ceil(1/2 + sqrt(1/4 + 2*tau_v*F_bar/(alpha*p_min*delta_bar))).
    For us: alpha is the DMI scaling const (estimated externally, default 0.1 here).
    """
    import math
    if alpha * p_min * delta_bar <= 0:
        return -1
    inside = 0.25 + 2.0 * tau_v * F_bar / (alpha * p_min * delta_bar)
    return int(math.ceil(0.5 + math.sqrt(inside)))
