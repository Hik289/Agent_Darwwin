"""B1 Figure 6: RCC sensitivity heatmap — valid cluster count and RII as function of (tau_in, tau_out)."""
import csv, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from collections import defaultdict

CSV = Path("./paper/data/rcc_sensitivity.csv")
OUT = Path("./paper/data/figure6_rcc_sensitivity.png")

rows = list(csv.DictReader(open(CSV)))
TAU_IN = sorted(set(float(r["tau_in"]) for r in rows))
TAU_OUT = sorted(set(float(r["tau_out"]) for r in rows))
RUNS = sorted(set(r["run_id"] for r in rows))

# For each run, compute "max valid count" across gens, for each (tau_in, tau_out)
# This is the strongest cluster detection signal under each threshold
max_valid = defaultdict(lambda: np.zeros((len(TAU_IN), len(TAU_OUT)), dtype=int))
mean_rii = defaultdict(lambda: np.zeros((len(TAU_IN), len(TAU_OUT))))
mean_rii_n = defaultdict(lambda: np.zeros((len(TAU_IN), len(TAU_OUT))))

for r in rows:
    run = r["run_id"]
    ti = TAU_IN.index(float(r["tau_in"]))
    to = TAU_OUT.index(float(r["tau_out"]))
    vc = int(r["valid_count_thresh"])
    max_valid[run][ti, to] = max(max_valid[run][ti, to], vc)
    rii = float(r["rii_mean"])
    mean_rii[run][ti, to] += rii
    mean_rii_n[run][ti, to] += 1

for run in RUNS:
    n = mean_rii_n[run]
    mean_rii[run] = np.where(n > 0, mean_rii[run] / np.maximum(n, 1), 0)

# Plot 4×3 grid: 4 top runs (v17.1, v18, Exp7C, Exp1.5) showing valid cluster heatmap
TOP_RUNS = ["v17.1", "v18", "Exp7C_uniform", "Exp1.5", "Exp1.2", "Exp2_b4"]
fig, axes = plt.subplots(2, 3, figsize=(13, 8))
axes = axes.flatten()

for idx, run in enumerate(TOP_RUNS):
    if idx >= len(axes):
        break
    ax = axes[idx]
    Z = max_valid[run]
    im = ax.imshow(Z, aspect='auto', cmap='viridis', origin='lower', vmin=0, vmax=4)
    ax.set_xticks(range(len(TAU_OUT)))
    ax.set_xticklabels([f"{t:.2f}" for t in TAU_OUT])
    ax.set_yticks(range(len(TAU_IN)))
    ax.set_yticklabels([f"{t:.2f}" for t in TAU_IN])
    ax.set_xlabel("τ_out")
    ax.set_ylabel("τ_in")
    ax.set_title(f"{run}: max valid clusters across gens")
    # Annotate cells
    for i in range(len(TAU_IN)):
        for j in range(len(TAU_OUT)):
            ax.text(j, i, str(Z[i, j]), ha='center', va='center',
                    color='white' if Z[i, j] < 2 else 'black', fontsize=10)
    plt.colorbar(im, ax=ax, label='max valid')

plt.suptitle("Figure 6: RCC sensitivity — max valid clusters under post-hoc (τ_in, τ_out) thresholds", fontsize=12, y=1.00)
plt.tight_layout()
plt.savefig(OUT, dpi=130, bbox_inches='tight')
print(f"Wrote {OUT}")

# Also: line plot of RII vs tau_in (fixed tau_out=0.05) per run
fig2, ax = plt.subplots(figsize=(9, 5))
for run in TOP_RUNS:
    rii_vs_tau = []
    for ti, ti_val in enumerate(TAU_IN):
        # Mean RII over gens where ≥1 valid cluster
        gen_riis = []
        for r in rows:
            if r["run_id"] == run and float(r["tau_in"]) == ti_val and float(r["tau_out"]) == 0.05:
                if int(r["valid_count_thresh"]) > 0:
                    gen_riis.append(float(r["rii_mean"]))
        rii_vs_tau.append(np.mean(gen_riis) if gen_riis else 0.0)
    ax.plot(TAU_IN, rii_vs_tau, "-o", label=run)
ax.set_xlabel("τ_in")
ax.set_ylabel("Mean RII (gens with ≥1 valid cluster)")
ax.set_title("RII robustness under τ_in (τ_out=0.05)")
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
OUT2 = Path("./paper/data/figure6b_rii_vs_tau_in.png")
plt.savefig(OUT2, dpi=130, bbox_inches='tight')
print(f"Wrote {OUT2}")
