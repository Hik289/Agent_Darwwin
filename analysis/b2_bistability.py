"""
B2 follow-up: bistability figure + stats + retroactive check on v17.1, v19, Exp7C.

Tasks:
  2. Fig 8: RII trajectory gen 1-25 with HOT/cold pattern
  3. bistability_stats.csv: HOT fraction, mean RII when HOT, K_w-K_b comparison
  4. Retroactive: check v17.1, v19, Exp7C 4-sample RCC for alternating pattern
"""
import json, csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CACHE = Path("./paper/data/results_cache")
DATA = Path("./paper/data")

# ============ Load B2 fine-grained data ============
fine = json.load(open(CACHE / "v18_fine_rcc.json"))
rcc = fine["rcc_history"]

# Build per-gen series
gens = [r["gen"] for r in rcc]
rii = [r.get("rii_mean", 0.0) for r in rcc]
n_clusters = [r.get("n_clusters", 1) for r in rcc]
k_w = [r.get("K_within_mean", 0.0) for r in rcc]
k_b = [r.get("K_between_mean", 0.0) if r.get("K_between_mean") is not None else 0.0 for r in rcc]
k_diff = [k_w[i] - k_b[i] for i in range(len(rcc))]

# HOT = RII > 0.5, cold = RII <= 0.5
hot_mask = [r > 0.5 for r in rii]

# ============ Task 2: Fig 8 bistability ============
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

# Top: RII trajectory
ax = axes[0]
colors = ["#2ca02c" if h else "#d62728" for h in hot_mask]  # green=HOT, red=cold
ax.bar(gens, rii, color=colors, edgecolor='black', linewidth=0.5, width=0.7)
ax.axhline(0.5, color='gray', linestyle='--', alpha=0.7, label='HOT threshold (RII=0.5)')
ax.set_ylabel("RII mean", fontsize=11)
ax.set_ylim(0, 1.05)
ax.set_xticks(range(1, 26))
ax.set_xlim(0.5, 25.5)
ax.grid(True, alpha=0.3, axis='y')

# Mark original v18 sample points (gen 5, 10, 15, 20, 25)
v18_orig_gens = [5, 10, 15, 20, 25]
for g in v18_orig_gens:
    if g <= 25:
        idx = g - 1
        ax.scatter(g, rii[idx] + 0.05, marker='v', color='blue', s=80, zorder=5,
                   edgecolor='black', linewidth=1)
ax.scatter([], [], marker='v', color='blue', s=80, edgecolor='black', linewidth=1,
           label='Original v18 sampling (eval_every=5)')

ax.set_ylim(0, 1.30)  # leave room for annotations above bars
# Place one annotation top-left, one top-right, no overlap with bars
ax.annotate("Original v18 (5-gen sample) saw\ngen 15/20/25 as cold → claimed 'collapse'",
            xy=(20, 0.04), xytext=(0.7, 1.14),
            fontsize=8.5, ha='left',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='blue', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='blue', lw=0.8))
ax.annotate("Fine-grained RCC: HOT/cold\nalternation gen 12+ (bistability)",
            xy=(16, 1.00), xytext=(13.5, 1.14),
            fontsize=8.5, ha='left',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='green', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='green', lw=0.8))

ax.set_title("Figure 8: Bistability in v18 - fine-grained RCC reveals HOT/cold alternation, not permanent collapse",
             fontsize=10.5)
ax.legend(loc='center left', fontsize=8, framealpha=0.9, bbox_to_anchor=(0.0, 0.55))

# Bottom: K_w and K_b traces
ax = axes[1]
ax.plot(gens, k_w, "-o", color="#1f77b4", label="K_within_mean", markersize=4)
ax.plot(gens, k_b, "-s", color="#ff7f0e", label="K_between_mean", markersize=4)
ax.fill_between(gens, k_w, k_b, alpha=0.15, color='gray')
ax.axhline(0.10, color='red', linestyle='--', alpha=0.5, label='τ_in=0.10')
ax.axhline(0.05, color='purple', linestyle='--', alpha=0.5, label='τ_out=0.05')
ax.set_xlabel("Generation", fontsize=11)
ax.set_ylabel("K (within/between)", fontsize=11)
ax.set_xticks(range(1, 26))
ax.set_xlim(0.5, 25.5)
ax.legend(loc='best', fontsize=9, ncol=2)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig8_out = DATA / "figure8_bistability.png"
plt.savefig(fig8_out, dpi=130, bbox_inches='tight')
print(f"Wrote {fig8_out}")
plt.close()

# ============ Task 3: bistability_stats.csv ============
# Pre-stable phase: gen 1-11 (continuous HOT)
# Post-stable bistability: gen 12-25 (alternating)
phase1_idx = [i for i, g in enumerate(gens) if g <= 11]
phase2_idx = [i for i, g in enumerate(gens) if g >= 12]

def phase_stats(idxs, label):
    rii_vals = [rii[i] for i in idxs]
    hot_idxs = [i for i in idxs if hot_mask[i]]
    cold_idxs = [i for i in idxs if not hot_mask[i]]
    return {
        "phase": label,
        "n_gens": len(idxs),
        "hot_count": len(hot_idxs),
        "cold_count": len(cold_idxs),
        "hot_fraction": len(hot_idxs) / max(len(idxs), 1),
        "mean_rii_all": float(np.mean(rii_vals)) if rii_vals else 0.0,
        "mean_rii_hot": float(np.mean([rii[i] for i in hot_idxs])) if hot_idxs else None,
        "mean_K_w_hot": float(np.mean([k_w[i] for i in hot_idxs])) if hot_idxs else None,
        "mean_K_w_cold": float(np.mean([k_w[i] for i in cold_idxs])) if cold_idxs else None,
        "mean_K_b_hot": float(np.mean([k_b[i] for i in hot_idxs])) if hot_idxs else None,
        "mean_K_b_cold": float(np.mean([k_b[i] for i in cold_idxs])) if cold_idxs else None,
        "mean_K_diff_hot": float(np.mean([k_diff[i] for i in hot_idxs])) if hot_idxs else None,
        "mean_K_diff_cold": float(np.mean([k_diff[i] for i in cold_idxs])) if cold_idxs else None,
    }

stats = [
    phase_stats(list(range(len(gens))), "all_25_gens"),
    phase_stats(phase1_idx, "gen_1_11_pre_stable"),
    phase_stats(phase2_idx, "gen_12_25_bistable"),
]

stats_csv = DATA / "bistability_stats.csv"
with open(stats_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(stats[0].keys()))
    w.writeheader()
    w.writerows(stats)
print(f"Wrote {stats_csv}")
print()
print("=== Bistability stats summary ===")
for s in stats:
    print(f"\n{s['phase']}: {s['n_gens']} gens")
    print(f"  HOT: {s['hot_count']} / {s['n_gens']} = {s['hot_fraction']:.2%}")
    print(f"  mean RII (all): {s['mean_rii_all']:.3f}")
    if s['mean_rii_hot']:
        print(f"  mean RII (HOT only): {s['mean_rii_hot']:.3f}")
    def fmt(v):
        return f"{v:.3f}" if v is not None else "n/a"
    print(f"  K_w HOT/cold: {fmt(s['mean_K_w_hot'])} / {fmt(s['mean_K_w_cold'])}")
    print(f"  K_b HOT/cold: {fmt(s['mean_K_b_hot'])} / {fmt(s['mean_K_b_cold'])}")
    print(f"  K_w-K_b HOT/cold: {fmt(s['mean_K_diff_hot'])} / {fmt(s['mean_K_diff_cold'])}")

# ============ Task 4: Retroactive bistability check ============
print()
print()
print("=== Task 4: Retroactive bistability in 5-gen sampled runs ===")
print()
print("Check if 4-6 sample points show alternating HOT/cold pattern.")
print()

RUNS_TO_CHECK = [
    ("v17.1", "v17_prod.json"),
    ("v19", "v19_prod.json"),
    ("Exp7C_uniform", "exp7c_uniform_prod.json"),
    ("v18 (original 5-gen)", "v18_prod.json"),
    ("Exp1.2", "exp1_2_prod.json"),
    ("Exp1.5", "exp1_5_prod.json"),
]

retro_rows = []
for run_id, fname in RUNS_TO_CHECK:
    fp = CACHE / fname
    if not fp.exists():
        continue
    p = json.load(open(fp))
    rcc_list = p.get("rcc_history", [])
    gen_arr = [r["gen"] for r in rcc_list]
    rii_arr = [r.get("rii_mean", 0.0) for r in rcc_list]
    k_clust = [r.get("n_clusters", 1) for r in rcc_list]
    hot_seq = [1 if r > 0.5 else 0 for r in rii_arr]
    # alternation = # transitions (HOT->cold or cold->HOT) / # possible
    transitions = sum(1 for i in range(1, len(hot_seq)) if hot_seq[i] != hot_seq[i-1])
    alternation = transitions / max(len(hot_seq) - 1, 1)
    pattern = "".join("H" if h else "C" for h in hot_seq)
    retro_rows.append({
        "run_id": run_id,
        "n_checkpoints": len(rcc_list),
        "pattern": pattern,
        "transitions": transitions,
        "alternation_rate": alternation,
        "hot_count": sum(hot_seq),
        "cold_count": len(hot_seq) - sum(hot_seq),
        "max_rii": max(rii_arr) if rii_arr else 0,
        "final_rii": rii_arr[-1] if rii_arr else 0,
    })
    print(f"  {run_id:25s}: pattern={pattern} transitions={transitions}/{len(hot_seq)-1} alt={alternation:.2f} max_rii={max(rii_arr):.3f}")

# Compare to B2 fine
b2_pattern = "".join("H" if h else "C" for h in hot_mask)
b2_transitions = sum(1 for i in range(1, len(hot_mask)) if hot_mask[i] != hot_mask[i-1])
print()
print(f"  B2 v18 fine (25 gen):   pattern={b2_pattern} transitions={b2_transitions}/{len(hot_mask)-1} alt={b2_transitions/(len(hot_mask)-1):.2f}")

retro_csv = DATA / "retroactive_bistability.csv"
with open(retro_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(retro_rows[0].keys()))
    w.writeheader()
    w.writerows(retro_rows)
print(f"\nWrote {retro_csv}")
