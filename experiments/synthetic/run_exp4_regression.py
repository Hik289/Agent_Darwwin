"""Task C: Exp 4 synthetic — causal regression of HFL on multiple distance features.

Construct a toy population on the 2-species landscape, compute for each pair:
  - HFL (ground truth from spec)
  - L_epi (epistatic load) — sum of |δ_lr| over lineage-divergent edges in the pair
  - d_genome (Hamming distance)
  - d_niche (cosine distance of niche-fitness profile vector [F_A, F_B])
  - d_behavior (proxy: L2 distance of fitness vector)
  - d_interface (proxy: number of lineage-divergent edges active)

Run OLS regression:
  HFL = γ_0 + γ_epi · L_epi + γ_genome · d_G + γ_niche · d_N + γ_behavior · d_B + γ_interface · d_iface

Verify |γ_epi| > |γ_genome|, |γ_epi| > |γ_behavior| with bootstrap CI.
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from synthetic import landscape_2species as L2
from synthetic import landscape_L_sweep as LS


RESULTS_DIR = Path("./results")


def build_population_for_exp4(n_per_lineage: int = 30, L: int = 16, alpha: float = 0.15,
                               seed: int = 42) -> dict[str, Any]:
    """Build 2*n_per_lineage agents with controlled lineage-divergent edges per pair.

    Each agent: an L-bit genome with k random bit-flips from its lineage template,
    where k drawn from binomial(L, 0.05) (small drift).
    """
    rng = random.Random(seed)
    half = L // 2
    A_template = [1] * half + [0] * (L - half)
    B_template = [0] * half + [1] * (L - half)
    pop = []
    for i in range(n_per_lineage):
        g = list(A_template)
        for k in range(L):
            if rng.random() < 0.05:
                g[k] = 1 - g[k]
        pop.append({"id": f"A{i}", "lineage": "A", "genome": tuple(g)})
    for i in range(n_per_lineage):
        g = list(B_template)
        for k in range(L):
            if rng.random() < 0.05:
                g[k] = 1 - g[k]
        pop.append({"id": f"B{i}", "lineage": "B", "genome": tuple(g)})

    landscape = LS.make_landscape_L(L, alpha=alpha, seed=seed)
    return {"pop": pop, "landscape": landscape, "L": L, "alpha": alpha}


def fitness_vector(G: tuple[int, ...], landscape: dict[str, Any]) -> tuple[float, float]:
    """Return (F_A, F_B) — fitness in each niche separately. For our L-landscape,
    F_A and F_B differ via the divergent edges only; for niche-symmetry we use full F
    as F_A and the negated divergence as F_B proxy.

    Simpler: return (F_full, parent_distance) — but that conflates niches. We use
    two-niche scoring: in niche_A, locus 0..L/2 = 1 is preferred; in niche_B, locus
    L/2..L = 1 is preferred. So F_niche_e = u_sum + J_sum where u_l(g_l, e) rewards
    being a specialist in e's preferred half.
    """
    u = landscape["u"]
    half = landscape["half"]
    L = landscape["L"]
    # niche A prefers first-half=1, second-half=0
    F_A = sum(u[l] for l in range(L) if (G[l] == 1) ^ (l < half) == False)  # match A template
    F_B = sum(u[l] for l in range(L) if (G[l] == 1) ^ (l >= half) == False)  # match B template
    # epistasis common to both niches
    for (l, r) in landscape["divergent_edges"]:
        same = (G[l] == G[r])
        delta = -0.05 if same else 0.05
        F_A += delta
        F_B += delta
    return F_A, F_B


def hybrid_eval(G1, G2, landscape, N_hybrids: int = 200, seed: int = 42) -> float:
    """Mean F_rho on hybrids."""
    rng = random.Random(seed)
    fits = []
    for _ in range(N_hybrids):
        h = LS.uniform_crossover(G1, G2, rng)
        F_A, F_B = fitness_vector(h, landscape)
        fits.append(0.5 * (F_A + F_B))
    return float(np.mean(fits))


def epistatic_load_pair(G1, G2, landscape) -> float:
    """L_epi per Definition 3 of EST: sum over divergent edges (ℓ,r) of δ_lr where:
      δ_lr = (1/2)[J(g1_l,g1_r) + J(g2_l,g2_r)] - (1/2)[J(g1_l,g2_r) + J(g2_l,g1_r)]

    For our landscape: J(a,b) = -0.05 if same allele, +0.05 if different.
    """
    total = 0.0
    for (l, r) in landscape["divergent_edges"]:
        def J(a, b):
            return -0.05 if a == b else 0.05
        same_aa = J(G1[l], G1[r])
        same_bb = J(G2[l], G2[r])
        cross_ab = J(G1[l], G2[r])
        cross_ba = J(G2[l], G1[r])
        delta = 0.5 * (same_aa + same_bb) - 0.5 * (cross_ab + cross_ba)
        total += delta
    return float(total)


def hamming(G1, G2) -> float:
    return float(sum(1 for a, b in zip(G1, G2) if a != b))


def niche_distance(G1, G2, landscape) -> float:
    """Cosine distance of (F_A, F_B) niche profile."""
    f1 = np.array(fitness_vector(G1, landscape))
    f2 = np.array(fitness_vector(G2, landscape))
    n1 = np.linalg.norm(f1)
    n2 = np.linalg.norm(f2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return 1.0 - float(np.dot(f1, f2) / (n1 * n2))


def behavior_distance(G1, G2, landscape) -> float:
    """L2 distance of (F_A, F_B) — proxy for behavior diversity."""
    f1 = np.array(fitness_vector(G1, landscape))
    f2 = np.array(fitness_vector(G2, landscape))
    return float(np.linalg.norm(f1 - f2))


def interface_distance(G1, G2, landscape) -> float:
    """|∂Q| proxy: expected number of cross-lineage boundary edges exposed by uniform
    crossover. With p_mix=0.5 per edge, this is just sum of (1 if endpoints can mix to
    cross-lineage) which we approximate by counting edges where the two parents differ
    at BOTH endpoints (so a cross-from-different-parent will land on this edge).
    """
    n = 0
    for (l, r) in landscape["divergent_edges"]:
        if G1[l] != G2[l] and G1[r] != G2[r]:
            n += 1
    return float(n)


def hfl_pair(G1, G2, landscape, N_hybrids: int = 200, seed: int = 42) -> float:
    F1A, F1B = fitness_vector(G1, landscape)
    F2A, F2B = fitness_vector(G2, landscape)
    F1 = 0.5 * (F1A + F1B)
    F2 = 0.5 * (F2A + F2B)
    parent_mean = 0.5 * (F1 + F2)
    if parent_mean <= 0:
        return 0.0
    hyb = hybrid_eval(G1, G2, landscape, N_hybrids=N_hybrids, seed=seed)
    return 1.0 - hyb / parent_mean


def compute_features_for_pop(pop_data: dict[str, Any], N_hybrids: int = 200) -> dict[str, Any]:
    """For every pair in population, compute HFL + all distance features."""
    pop = pop_data["pop"]
    landscape = pop_data["landscape"]
    n = len(pop)
    rows = []
    rng_seed = 1000
    for i in range(n):
        for j in range(i + 1, n):
            G1 = pop[i]["genome"]
            G2 = pop[j]["genome"]
            hfl = hfl_pair(G1, G2, landscape, N_hybrids=N_hybrids, seed=rng_seed)
            rng_seed += 1
            rows.append({
                "i": i, "j": j,
                "lin_i": pop[i]["lineage"], "lin_j": pop[j]["lineage"],
                "between_lineage": int(pop[i]["lineage"] != pop[j]["lineage"]),
                "HFL": hfl,
                "L_epi": epistatic_load_pair(G1, G2, landscape),
                "d_genome": hamming(G1, G2),
                "d_niche": niche_distance(G1, G2, landscape),
                "d_behavior": behavior_distance(G1, G2, landscape),
                "d_interface": interface_distance(G1, G2, landscape),
            })
    return {"rows": rows}


def fit_regression(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """OLS: HFL = γ_0 + γ_epi·L_epi + γ_genome·d_G + γ_niche·d_N + γ_behavior·d_B + γ_iface·d_iface."""
    Y = np.array([r["HFL"] for r in rows])
    features = ["L_epi", "d_genome", "d_niche", "d_behavior", "d_interface"]
    X_list = [np.array([r[f] for r in rows]) for f in features]
    # Standardize features for fair coefficient comparison
    X_std = []
    means, stds = [], []
    for x in X_list:
        m = float(x.mean())
        s = float(x.std()) if x.std() > 0 else 1.0
        means.append(m)
        stds.append(s)
        X_std.append((x - m) / s)
    X = np.vstack([np.ones(len(Y))] + X_std).T
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    pred = X @ coef
    rss = float(np.sum((Y - pred) ** 2))
    tss = float(np.sum((Y - Y.mean()) ** 2))
    r2 = 1.0 - rss / tss if tss > 0 else 0.0

    # bootstrap CI on coefficients
    rng = np.random.default_rng(42)
    boot_coefs = []
    n = len(Y)
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        Xb = X[idx]
        Yb = Y[idx]
        try:
            cb, *_ = np.linalg.lstsq(Xb, Yb, rcond=None)
            boot_coefs.append(cb)
        except np.linalg.LinAlgError:
            pass
    boot_arr = np.array(boot_coefs)
    coef_ci = []
    for k in range(boot_arr.shape[1]):
        lo = float(np.quantile(boot_arr[:, k], 0.025))
        hi = float(np.quantile(boot_arr[:, k], 0.975))
        coef_ci.append((lo, hi))

    # p-value: bootstrap test if coefficient ≠ 0
    p_vals = []
    for k in range(boot_arr.shape[1]):
        b = boot_arr[:, k]
        if (b > 0).mean() > 0.5:
            p = 2 * float((b <= 0).mean())
        else:
            p = 2 * float((b >= 0).mean())
        p_vals.append(p)

    return {
        "n_pairs": len(rows),
        "features": ["intercept"] + features,
        "coefficients": {("intercept" if i == 0 else features[i - 1]): float(coef[i])
                          for i in range(len(coef))},
        "coefficient_ci_95": {("intercept" if i == 0 else features[i - 1]): coef_ci[i]
                               for i in range(len(coef))},
        "p_values_bootstrap": {("intercept" if i == 0 else features[i - 1]): float(p_vals[i])
                                for i in range(len(coef))},
        "R2": r2,
        "feature_means": dict(zip(features, means)),
        "feature_stds": dict(zip(features, stds)),
        "comparisons": {
            "abs_gamma_epi_gt_abs_gamma_genome":
                abs(coef[1]) > abs(coef[2]),
            "abs_gamma_epi_gt_abs_gamma_behavior":
                abs(coef[1]) > abs(coef[4]),
            "abs_gamma_epi_value": abs(float(coef[1])),
            "abs_gamma_genome_value": abs(float(coef[2])),
            "abs_gamma_behavior_value": abs(float(coef[4])),
        },
    }


def main():
    print("=== Task C: Exp 4 synthetic regression ===", flush=True)
    t0 = time.time()
    pop_data = build_population_for_exp4(n_per_lineage=30, L=16, alpha=0.15, seed=42)
    print(f"  Population: 60 agents (30 A + 30 B), L=16, α=0.15", flush=True)
    print(f"  Computing features for {30*60} pairs...", flush=True)
    feats = compute_features_for_pop(pop_data, N_hybrids=200)
    n_pairs = len(feats["rows"])
    print(f"  {n_pairs} pairs computed", flush=True)

    reg = fit_regression(feats["rows"])
    print(f"\n  Standardized coefficients:", flush=True)
    for f, c in reg["coefficients"].items():
        ci = reg["coefficient_ci_95"][f]
        p = reg["p_values_bootstrap"][f]
        print(f"    γ_{f:<15} = {c:>8.4f}  CI [{ci[0]:>7.4f}, {ci[1]:>7.4f}]  p={p:.4f}",
              flush=True)
    print(f"  R² = {reg['R2']:.4f}", flush=True)
    print(f"\n  H4 checks:", flush=True)
    cmp_ = reg["comparisons"]
    print(f"    |γ_epi|={cmp_['abs_gamma_epi_value']:.4f} > |γ_genome|={cmp_['abs_gamma_genome_value']:.4f}: "
          f"{cmp_['abs_gamma_epi_gt_abs_gamma_genome']}", flush=True)
    print(f"    |γ_epi|={cmp_['abs_gamma_epi_value']:.4f} > |γ_behavior|={cmp_['abs_gamma_behavior_value']:.4f}: "
          f"{cmp_['abs_gamma_epi_gt_abs_gamma_behavior']}", flush=True)
    passed = (cmp_["abs_gamma_epi_gt_abs_gamma_genome"]
              and cmp_["abs_gamma_epi_gt_abs_gamma_behavior"]
              and reg["p_values_bootstrap"]["L_epi"] < 0.01)
    print(f"  H4 PASS: {passed}", flush=True)

    out = {
        "task": "C_exp4_regression",
        "pop": {"n": len(pop_data["pop"]), "L": pop_data["L"], "alpha": pop_data["alpha"]},
        "n_pairs": n_pairs,
        "regression": reg,
        "H4_passed": passed,
        "elapsed_sec": time.time() - t0,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "exp4_synthetic_regression.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  wrote {out_path} ({out['elapsed_sec']:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
