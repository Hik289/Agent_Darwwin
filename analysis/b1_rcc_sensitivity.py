"""
B1: RCC sensitivity sweep — re-analyze existing RCM/RCC data with different
post-hoc tau_in / tau_out validity thresholds.

Definitions:
- For each cluster c with K_within[c] and K_between[c]:
  - cluster_valid(tau_in, tau_out) := K_within > tau_in AND K_between < tau_out
- valid_K(run, gen, tau_in, tau_out) := count of clusters passing
- RII unchanged (depends on labels, not on tau)

Output: ./paper/data/rcc_sensitivity.csv
"""
import json, csv
from pathlib import Path

CACHE = Path("./paper/data/results_cache")
OUT_CSV = Path("./paper/data/rcc_sensitivity.csv")

# Sweep grid
TAU_IN_SWEEP = [0.05, 0.10, 0.15, 0.20]
TAU_OUT_SWEEP = [0.02, 0.05, 0.10]

RUNS = [
    ("v17.1", "v17_prod.json", "3-niche rigid hand-seed m=0"),
    ("v18", "v18_prod.json", "3-niche rigid hand-seed m=0.05 mild evo"),
    ("v19", "v19_prod.json", "3-niche rigid hand-seed m=0.02 mu=0.05"),
    ("Exp7C_uniform", "exp7c_uniform_prod.json", "3-niche rigid uniform crossover"),
    ("Exp1.1", "exp1_1_prod.json", "1-niche HotpotQA spontaneous baseline"),
    ("Exp1.2", "exp1_2_prod.json", "2-niche rigid hand-seed 2 lineages"),
    ("Exp1.5", "exp1_5_prod.json", "3-niche rigid hand-seed m=0.40 high mig"),
    ("Exp2_b1", "b1_prod.json", "no-pop-crossover hand-seed soft"),
    ("Exp2_b3", "b3_prod.json", "no-mutation hand-seed soft"),
    ("Exp2_b4", "b4_prod.json", "no-rigid hand-seed soft"),
    ("Exp2_b5", "b5_prod.json", "no-handseed soft pure baseline"),
]

rows = []
for run_id, fname, description in RUNS:
    fp = CACHE / fname
    if not fp.exists():
        print(f"WARN: missing {fname}")
        continue
    p = json.load(open(fp))
    for entry in p.get("rcc_history", []):
        gen = entry["gen"]
        rii_mean = entry.get("rii_mean", 0.0)
        n_clusters = entry.get("n_clusters", 1)
        # Per-cluster valid analysis under each (tau_in, tau_out)
        valid_clusters = entry.get("valid_clusters", []) or []
        for tau_in in TAU_IN_SWEEP:
            for tau_out in TAU_OUT_SWEEP:
                # Count valid under post-hoc threshold
                valid_count = sum(
                    1 for c in valid_clusters
                    if c.get("K_within", 0) > tau_in
                    and c.get("K_between", 1e9) < tau_out
                )
                rows.append({
                    "run_id": run_id,
                    "gen": gen,
                    "tau_in": tau_in,
                    "tau_out": tau_out,
                    "n_clusters_spectral": n_clusters,
                    "valid_count_thresh": valid_count,
                    "rii_mean": rii_mean,
                    "K_w_mean": entry.get("K_within_mean", 0.0),
                    "K_b_mean": entry.get("K_between_mean", None),
                    "description": description,
                })

# Write CSV
with open(OUT_CSV, "w", newline="") as f:
    if not rows:
        print("ERROR: no rows generated")
        exit(1)
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"Wrote {len(rows)} rows to {OUT_CSV}")
# Summary
import collections
print()
print("Summary (gen across all runs, default tau_in=0.10 tau_out=0.05):")
counter = collections.Counter()
for r in rows:
    if r["tau_in"] == 0.10 and r["tau_out"] == 0.05:
        counter[r["run_id"]] += (r["valid_count_thresh"] > 0)
for run, cnt in sorted(counter.items()):
    print(f"  {run}: {cnt} gens with ≥1 valid cluster (tau_in=0.10, tau_out=0.05)")
