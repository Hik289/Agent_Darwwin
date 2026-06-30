"""L-sweep landscape: HFL ∝ L² (Thm 4 quadratic accumulation).

Per Lemma 6 (Orr 1995) + Thm 4: E[M(L)] = α · L(L-1)/2 + O(L), so
E[L_AB(L)] = α · L(L-1)/2 · p_min · δ̄.

Implementation:
  - For each L: build a landscape with α-fraction of all pairwise cross-lineage edges
    as divergent. With lineage A = [1]*half + [0]*half, B = [0]*half + [1]*half,
    cross-lineage edges = half * half. We set M(L) = α * half * (half - 1) / 2,
    capped at the pool size.
  - But to faithfully implement Lemma 6 (M = α · L(L-1)/2), we use:
        M(L) = floor(α · L · (L - 1) / 2)
    and pick M(L) divergent edges (with the half-half cross constraint), keeping α
    as a free landscape parameter we can later vary or fit.
  - Hybrid generated via uniform 50-50 crossover.

For α estimation: with fixed α_true, slope of L_AB on L(L-1)/2 should equal
α_true · p_min · δ̄ = α_true · 0.5 · 0.10 = 0.05 · α_true. So measuring slope and
dividing by 0.05 gives α_hat.

For L_c detection: per Thm 4, L_c is the threshold where E[HFL] crosses τ_v.
HFL(L) = E[L_AB(L)] / F_bar. We compute empirical break point by segmented
regression on log(L_AB) vs log(L), checking for non-trivial slope > 1.5 (signaling
super-linear growth above L_c).
"""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np


def make_landscape_L(
    L: int,
    alpha: float = 0.1,
    seed: int = 42,
    delta: float = 0.10,
) -> dict[str, Any]:
    """Build an L-genome landscape with M = floor(alpha · L(L-1)/2) divergent edges.

    Lineage layout:
        first half (locus 0..L/2-1):  A = 1, B = 0
        second half (locus L/2..L-1): A = 0, B = 1
    Divergent edges pool = cross-lineage pairs (one in first half × one in second half).
    """
    rng = random.Random(seed)
    half = L // 2
    if half < 1:
        half = 1
    M_target = max(int(math.floor(alpha * L * (L - 1) / 2.0)), 1)
    cross_pool = [(l, r) for l in range(half) for r in range(half, L)]
    rng.shuffle(cross_pool)
    M = min(M_target, len(cross_pool))
    divergent = cross_pool[:M]
    # Each divergent edge: same-allele J = -0.05 (specialist mismatch), diff-allele J = +0.05
    # → δ_lr = 0.10
    # Single-locus utility: small uniform [0, 0.05] for symmetry
    u = [rng.uniform(0.0, 0.05) for _ in range(L)]
    return {"L": L, "M": M, "alpha_used": alpha, "half": half, "u": u,
            "divergent_edges": divergent, "delta": delta, "seed": seed}


def fitness_L(G: tuple[int, ...], landscape: dict[str, Any]) -> float:
    """F(G) = sum u_l (only u(1) counts) + sum_J(divergent_edges)."""
    u = landscape["u"]
    half = landscape["half"]
    L = landscape["L"]
    F_val = sum(u[l] for l in range(L) if G[l] == 1)
    for (l, r) in landscape["divergent_edges"]:
        same = (G[l] == G[r])
        F_val += -0.05 if same else 0.05
    return F_val


def parents_L(L: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    half = L // 2
    if half < 1:
        half = 1
    A = tuple([1] * half + [0] * (L - half))
    B = tuple([0] * half + [1] * (L - half))
    return A, B


def uniform_crossover(A, B, rng: random.Random) -> tuple[int, ...]:
    return tuple(A[i] if rng.random() < 0.5 else B[i] for i in range(len(A)))


def estimate_L_AB_at_L(
    L: int,
    alpha: float = 0.1,
    N_landscape_draws: int = 10,
    N_hybrids: int = 2000,
    seed: int = 42,
    delta: float = 0.10,
) -> dict[str, Any]:
    """For one L value: average L_AB over multiple landscape draws (different placements
    of M(L) divergent edges)."""
    L_AB_per_draw = []
    M_used = None
    for draw in range(N_landscape_draws):
        lscape = make_landscape_L(L, alpha=alpha, seed=seed + draw * 1000, delta=delta)
        M_used = lscape["M"]
        A, B = parents_L(L)
        F_A = fitness_L(A, lscape)
        F_B = fitness_L(B, lscape)
        parent_mean = 0.5 * (F_A + F_B)
        rng = random.Random(seed + draw * 1000 + 1)
        hybrid_fits = [fitness_L(uniform_crossover(A, B, rng), lscape) for _ in range(N_hybrids)]
        L_AB = parent_mean - float(np.mean(hybrid_fits))
        L_AB_per_draw.append(L_AB)
    arr = np.array(L_AB_per_draw)
    return {
        "L": L, "M_used": M_used,
        "L_AB_mean": float(arr.mean()),
        "L_AB_std": float(arr.std()),
        "L_AB_ci_lo": float(np.quantile(arr, 0.025)),
        "L_AB_ci_hi": float(np.quantile(arr, 0.975)),
        "L_AB_per_draw": L_AB_per_draw,
        "L_AB_predicted_thm4_quadratic": alpha * L * (L - 1) / 2 * 0.5 * 0.10,
        "alpha_used": alpha,
        "N_landscape_draws": N_landscape_draws,
        "N_hybrids": N_hybrids,
    }


def fit_alpha(L_sweep: list[dict[str, Any]], p_min: float = 0.5,
              delta_bar: float = 0.10) -> dict[str, Any]:
    """Fit L_AB = (α · p_min · δ̄) · L(L-1)/2 via least squares (no intercept).

    Returns alpha estimate + bootstrap CI.
    """
    Ls = np.array([r["L"] for r in L_sweep], dtype=float)
    Ys = np.array([r["L_AB_mean"] for r in L_sweep], dtype=float)
    X = Ls * (Ls - 1) / 2.0  # design vector
    # OLS without intercept: slope = sum(X*Y) / sum(X*X)
    slope = float(np.sum(X * Ys) / np.sum(X * X))
    alpha_hat = slope / (p_min * delta_bar)
    pred = slope * X
    ss_res = float(np.sum((Ys - pred) ** 2))
    ss_tot = float(np.sum((Ys - np.mean(Ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # bootstrap CI over the per-draw L_AB values
    rng = np.random.default_rng(42)
    boot_alphas = []
    # use per-draw values for proper bootstrap
    per_draw_pool = [(r["L"], v) for r in L_sweep for v in r["L_AB_per_draw"]]
    n_pool = len(per_draw_pool)
    for _ in range(1000):
        idx = rng.integers(0, n_pool, size=n_pool)
        sample = [per_draw_pool[i] for i in idx]
        L_vals = np.array([s[0] for s in sample], dtype=float)
        Y_vals = np.array([s[1] for s in sample], dtype=float)
        X_v = L_vals * (L_vals - 1) / 2.0
        denom = np.sum(X_v * X_v)
        if denom <= 0:
            continue
        sl = np.sum(X_v * Y_vals) / denom
        boot_alphas.append(sl / (p_min * delta_bar))
    boot_alphas = np.array(boot_alphas)
    return {
        "slope": slope,
        "alpha_hat": alpha_hat,
        "alpha_ci_lo": float(np.quantile(boot_alphas, 0.025)),
        "alpha_ci_hi": float(np.quantile(boot_alphas, 0.975)),
        "R2_quadratic": r2,
    }


def compute_L_c_with_alpha(alpha: float, tau_v: float = 0.20, F_bar: float = 0.31,
                            p_min: float = 0.5, delta_bar: float = 0.10) -> int:
    """Thm 4 closed-form L_c."""
    if alpha * p_min * delta_bar <= 0:
        return -1
    inside = 0.25 + 2.0 * tau_v * F_bar / (alpha * p_min * delta_bar)
    return int(math.ceil(0.5 + math.sqrt(inside)))


def segmented_regression_break(
    L_sweep: list[dict[str, Any]], L_c_candidate: int, tau_v: float = 0.20,
    F_bar: float = 0.31,
) -> dict[str, Any]:
    """Fit slope of log(L_AB) vs log(L) below vs above L_c, F-test.

    A clear super-linear regime exists when slope above L_c > slope below L_c.
    """
    Ls = np.array([r["L"] for r in L_sweep], dtype=float)
    Ys = np.array([r["L_AB_mean"] for r in L_sweep], dtype=float)
    HFLs = Ys / F_bar  # HFL = L_AB / F_bar

    log_L = np.log(Ls)
    log_LAB = np.log(np.maximum(Ys, 1e-9))

    below_idx = Ls < L_c_candidate
    above_idx = Ls >= L_c_candidate

    def _slope(xs, ys):
        if len(xs) < 2:
            return None, None, None
        A = np.vstack([xs, np.ones_like(xs)]).T
        slope, intercept = np.linalg.lstsq(A, ys, rcond=None)[0]
        pred = slope * xs + intercept
        ss_res = float(np.sum((ys - pred) ** 2))
        ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
        return float(slope), float(intercept), r2

    s_below, i_below, r2_below = _slope(log_L[below_idx], log_LAB[below_idx])
    s_above, i_above, r2_above = _slope(log_L[above_idx], log_LAB[above_idx])

    # Joint fit
    s_joint, i_joint, r2_joint = _slope(log_L, log_LAB)

    # F-test for two-segment vs single
    n = len(Ls)
    # RSS_full: two segments
    pred_full = np.where(below_idx, s_below * log_L + i_below, s_above * log_L + i_above) if s_below is not None and s_above is not None else log_LAB
    rss_full = float(np.sum((log_LAB - pred_full) ** 2)) if s_below is not None and s_above is not None else None
    pred_joint = s_joint * log_L + i_joint
    rss_joint = float(np.sum((log_LAB - pred_joint) ** 2))
    F_stat = None
    p_val = None
    if rss_full is not None and rss_full > 0 and (rss_joint - rss_full) > 0 and n - 4 > 0:
        # ΔRSS / k vs RSS_full / (n - p)
        F_stat = ((rss_joint - rss_full) / 2) / (rss_full / (n - 4))
        from scipy import stats
        p_val = 1.0 - stats.f.cdf(F_stat, 2, n - 4)

    return {
        "L_c_candidate": L_c_candidate,
        "slope_below_L_c": s_below, "intercept_below": i_below, "R2_below": r2_below,
        "slope_above_L_c": s_above, "intercept_above": i_above, "R2_above": r2_above,
        "joint_slope": s_joint, "joint_R2": r2_joint,
        "F_test_stat": F_stat, "F_test_p": p_val,
        "n_below": int(below_idx.sum()), "n_above": int(above_idx.sum()),
        "expected_below": "slope ≤ 1 (sub-threshold, sparse cross-lineage)",
        "expected_above": "slope ≥ 1.5 (super-threshold, near quadratic 2)",
    }


def empirical_L_c_from_tau(
    L_sweep: list[dict[str, Any]], tau_v: float = 0.20, F_bar: float = 0.31,
) -> int | None:
    """First L at which mean HFL = L_AB/F_bar exceeds tau_v."""
    for r in L_sweep:
        hfl = r["L_AB_mean"] / F_bar
        if hfl >= tau_v:
            return r["L"]
    return None
