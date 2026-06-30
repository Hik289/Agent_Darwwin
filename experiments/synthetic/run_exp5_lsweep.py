"""Task A + Task B: synthetic L-sweep + full Exp 5.

Output:
  - results/synthetic_lsweep.json  (Task A: quick L-sweep with α fit)
  - results/exp5_synthetic_full.json (Task B: full Exp 5 with reps, F-test, Pearson r)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from synthetic.landscape_L_sweep import (
    estimate_L_AB_at_L, fit_alpha, compute_L_c_with_alpha,
    segmented_regression_break, empirical_L_c_from_tau,
)


RESULTS_DIR = Path("./results")


L_GRID = [4, 6, 8, 10, 12, 16, 20, 24, 32]


def ascii_lsweep_plot(L_sweep, alpha_hat, predicted_curve):
    """Plot empirical L_AB vs L + predicted quadratic curve."""
    lines = ["", "  L_AB vs L (Thm 4 quadratic verification)",
             "  -------------------------------------------"]
    L_vals = [r["L"] for r in L_sweep]
    Y_vals = [r["L_AB_mean"] for r in L_sweep]
    Y_pred = predicted_curve
    y_max = max(max(Y_vals), max(Y_pred)) * 1.1
    height = 14

    def L_to_col(L):
        # crude log scale: L=4→1, L=8→3, L=16→5, L=32→7
        import math
        return int(math.log2(L) - 1) * 2

    for row in range(height, -1, -1):
        y = y_max * row / height
        s = f"  {y:5.3f} |"
        cols = [" "] * 16
        for L, Y in zip(L_vals, Y_vals):
            c = L_to_col(L)
            if 0 <= c < len(cols) and abs(Y - y) < y_max / (height * 2):
                cols[c] = "*"
        for L, Y in zip(L_vals, Y_pred):
            c = L_to_col(L)
            if 0 <= c < len(cols) and abs(Y - y) < y_max / (height * 2) and cols[c] == " ":
                cols[c] = "."
        lines.append(s + "".join(cols))
    lines.append("        +" + "-" * 16)
    lines.append("           4  6  8 10 12 16 20 24 32  L  (log-spaced cols)")
    lines.append(f"    * = measured; . = predicted (α_hat = {alpha_hat:.3f})")
    return "\n".join(lines)


def task_a_lsweep(alpha_true: float = 0.10, N_draws: int = 10, N_hybrids: int = 2000) -> dict:
    """Quick L-sweep at fixed α_true to verify quadratic scaling + estimate α_hat."""
    print(f"[Task A] L-sweep α_true={alpha_true}, L ∈ {L_GRID}, draws/L={N_draws}, hybrids/draw={N_hybrids}",
          flush=True)
    t0 = time.time()
    sweep = []
    for L in L_GRID:
        r = estimate_L_AB_at_L(L, alpha=alpha_true, N_landscape_draws=N_draws,
                               N_hybrids=N_hybrids, seed=42)
        sweep.append(r)
        print(f"  L={L}: M={r['M_used']:>4}, L_AB={r['L_AB_mean']:.4f} ± {r['L_AB_std']:.4f} "
              f"(pred {r['L_AB_predicted_thm4_quadratic']:.4f})", flush=True)

    fit = fit_alpha(sweep, p_min=0.5, delta_bar=0.10)
    print(f"  α_hat={fit['alpha_hat']:.4f} (95% CI [{fit['alpha_ci_lo']:.4f}, {fit['alpha_ci_hi']:.4f}])",
          flush=True)
    print(f"  R²_quadratic={fit['R2_quadratic']:.4f}", flush=True)

    # L_c with α_hat
    L_c_theo = compute_L_c_with_alpha(fit["alpha_hat"], tau_v=0.20, F_bar=0.31,
                                       p_min=0.5, delta_bar=0.10)
    L_c_emp = empirical_L_c_from_tau(sweep, tau_v=0.20, F_bar=0.31)

    seg = segmented_regression_break(sweep, L_c_candidate=L_c_theo, tau_v=0.20, F_bar=0.31)
    print(f"  L_c theoretical (α_hat)={L_c_theo}, L_c empirical (first HFL≥τ_v)={L_c_emp}", flush=True)
    print(f"  segmented slope below={seg.get('slope_below_L_c')}, above={seg.get('slope_above_L_c')}",
          flush=True)

    pred_vals = [r["L_AB_predicted_thm4_quadratic"] for r in sweep]
    plot = ascii_lsweep_plot(sweep, fit["alpha_hat"], pred_vals)
    print(plot, flush=True)

    elapsed = time.time() - t0
    return {
        "task": "A_lsweep",
        "alpha_true": alpha_true,
        "L_grid": L_GRID,
        "sweep": sweep,
        "fit": fit,
        "L_c_theoretical": L_c_theo,
        "L_c_empirical": L_c_emp,
        "segmented_regression": seg,
        "ascii_plot": plot,
        "elapsed_sec": elapsed,
    }


def task_b_full_exp5(alpha_true_values=(0.05, 0.10, 0.15, 0.20),
                      N_draws: int = 10, N_hybrids: int = 2000) -> dict:
    """Full Exp 5 synthetic: vary α_true, verify slope break correlates with theoretical L_c."""
    print(f"\n[Task B] full Exp 5: α_true ∈ {alpha_true_values}, "
          f"L_grid={L_GRID}", flush=True)
    t0 = time.time()
    all_sweeps = {}
    L_c_pairs = []

    for alpha_true in alpha_true_values:
        print(f"\n  --- α_true = {alpha_true} ---", flush=True)
        sweep = []
        for L in L_GRID:
            r = estimate_L_AB_at_L(L, alpha=alpha_true, N_landscape_draws=N_draws,
                                   N_hybrids=N_hybrids, seed=42)
            sweep.append(r)
        fit = fit_alpha(sweep, p_min=0.5, delta_bar=0.10)
        L_c_theo = compute_L_c_with_alpha(alpha_true, tau_v=0.20, F_bar=0.31,
                                           p_min=0.5, delta_bar=0.10)
        L_c_emp = empirical_L_c_from_tau(sweep, tau_v=0.20, F_bar=0.31)
        seg = segmented_regression_break(sweep, L_c_candidate=L_c_theo, tau_v=0.20, F_bar=0.31)
        print(f"    α_hat={fit['alpha_hat']:.4f} (true {alpha_true}), L_c_theo={L_c_theo}, "
              f"L_c_emp={L_c_emp}", flush=True)
        all_sweeps[f"alpha_{alpha_true}"] = {
            "alpha_true": alpha_true, "sweep": sweep, "fit": fit,
            "L_c_theo": L_c_theo, "L_c_emp": L_c_emp, "segmented": seg,
        }
        if L_c_emp is not None:
            L_c_pairs.append((L_c_theo, L_c_emp))

    # Pearson correlation between theoretical and empirical L_c (across alpha values)
    pearson_r = None
    pearson_p = None
    if len(L_c_pairs) >= 3:
        Xs = np.array([p[0] for p in L_c_pairs], dtype=float)
        Ys = np.array([p[1] for p in L_c_pairs], dtype=float)
        if Xs.std() > 0 and Ys.std() > 0:
            from scipy import stats
            r, p = stats.pearsonr(Xs, Ys)
            pearson_r = float(r)
            pearson_p = float(p)

    print(f"\n  Pearson r (L_c_theo vs L_c_emp across α): "
          f"{pearson_r} (p={pearson_p})", flush=True)

    elapsed = time.time() - t0
    return {
        "task": "B_full_exp5",
        "alpha_true_values": list(alpha_true_values),
        "all_sweeps": all_sweeps,
        "L_c_pairs": L_c_pairs,
        "pearson_r_Lc_theo_vs_emp": pearson_r,
        "pearson_p": pearson_p,
        "passed_H5": (pearson_r is not None and pearson_r >= 0.5
                     and (pearson_p is not None and pearson_p < 0.05)),
        "elapsed_sec": elapsed,
    }


def main():
    out_a = RESULTS_DIR / "synthetic_lsweep.json"
    out_b = RESULTS_DIR / "exp5_synthetic_full.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Task A
    a = task_a_lsweep(alpha_true=0.10, N_draws=10, N_hybrids=2000)
    out_a.write_text(json.dumps(a, indent=2, default=str))
    print(f"\n[Task A] wrote {out_a} ({a['elapsed_sec']:.1f}s)", flush=True)

    # Task B
    b = task_b_full_exp5(alpha_true_values=(0.05, 0.10, 0.15, 0.20),
                         N_draws=10, N_hybrids=2000)
    out_b.write_text(json.dumps(b, indent=2, default=str))
    print(f"\n[Task B] wrote {out_b} ({b['elapsed_sec']:.1f}s)", flush=True)

    print(f"\n=== TASK A+B DONE ===", flush=True)


if __name__ == "__main__":
    main()
