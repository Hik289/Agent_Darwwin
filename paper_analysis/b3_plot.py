"""B3 Figure 7: Pairwise compatibility distributions for K=1 vs K>=2 runs."""
import csv, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from collections import defaultdict

CSV = Path("./paper/data/raw_pairwise_compat.csv")
OUT = Path("./paper/data/figure7_raw_pairwise.png")

rows = list(csv.DictReader(open(CSV)))
by_run = defaultdict(list)
for r in rows:
    by_run[r["run_id"]].append(r)

K1_RUNS = ["Exp1.1", "Exp2_b1", "Exp2_b3", "Exp2_b4", "Exp2_b5", "v19"]
K_GE2_RUNS = ["v17.1", "v18", "Exp1.2", "Exp1.5", "Exp7C_uniform"]

fig, axes = plt.subplots(2, 1, figsize=(10, 7))

ax = axes[0]
ax.set_title("K=1 / RII=0 runs: K_within_mean trajectories (population baseline)")
for run in K1_RUNS:
    if run not in by_run: continue
    gens = []; kw = []
    for r in by_run[run]:
        if r["type"] == "K=1_population_baseline":
            try:
                gens.append(int(r["gen"]))
                kw.append(float(r["K_within_mean_gen"]))
            except (ValueError, TypeError):
                continue
    if gens:
        ax.plot(gens, kw, "-o", label=run, markersize=4)
ax.axhline(0.10, color='red', linestyle='--', alpha=0.5, label='tau_in=0.10')
ax.set_xlabel("Generation"); ax.set_ylabel("K_within_mean (RCM diagonal)")
ax.legend(loc='best', fontsize=9, ncol=2); ax.grid(True, alpha=0.3); ax.set_ylim(0, 0.55)

ax = axes[1]
ax.set_title("K>=2 runs: K_AB (between-cluster) per-pair distributions")
for run in K_GE2_RUNS:
    if run not in by_run: continue
    kab_vals = []
    for r in by_run[run]:
        if r["type"] == "cross_cluster_pair":
            try: kab_vals.append(float(r["K_AB_between"]))
            except (ValueError, TypeError): continue
    if kab_vals:
        bins = np.linspace(0, 0.5, 20)
        ax.hist(kab_vals, bins=bins, alpha=0.5, label=f"{run} (n={len(kab_vals)})")
ax.axvline(0.05, color='red', linestyle='--', alpha=0.5, label='tau_out=0.05')
ax.set_xlabel("K_AB (cross-cluster compatibility)")
ax.set_ylabel("Count (pair-gen pairs)")
ax.legend(loc='best', fontsize=9, ncol=2); ax.grid(True, alpha=0.3)

plt.suptitle("Figure 7: Raw pairwise compatibility - K=1 vs K>=2 contrast", fontsize=12)
plt.tight_layout()
plt.savefig(OUT, dpi=130, bbox_inches='tight')
print(f"Wrote {OUT}")
