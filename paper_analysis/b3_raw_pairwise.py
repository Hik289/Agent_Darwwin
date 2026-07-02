"""
B3: Raw pairwise compatibility distributions for K=1 RII=0 runs.

Since pre-clustering RCM matrices are NOT persisted in result jsons, we use the
next-best available data:
- K_within_mean (mean of RCM diagonal — self-cross viability across population)
- For K=1 runs: no K_between data → use K_within as baseline only
- For K>=2 runs: K_AB from rii_pairs as cross-cluster contrast

For RCC K=1 runs (b1, b3, b4, b5, Exp1.1, v19), we report:
- K_within_mean trajectory (baseline)
- Notes: spectral clustering found no separable structure, so K_b not computed

Output: ./paper/data/raw_pairwise_compat.csv
"""
import json, csv
from pathlib import Path

CACHE = Path("./paper/data/results_cache")
OUT_CSV = Path("./paper/data/raw_pairwise_compat.csv")

RUNS = [
    ("v17.1", "v17_prod.json", "rigid hand-seed m=0 G1=PASS"),
    ("v18", "v18_prod.json", "rigid hand-seed m=0.05 partial G1"),
    ("v19", "v19_prod.json", "rigid hand-seed m=0.02 K=1 throughout"),
    ("Exp7C_uniform", "exp7c_uniform_prod.json", "rigid uniform hand-seed partial G1"),
    ("Exp1.1", "exp1_1_prod.json", "1-niche null baseline"),
    ("Exp1.2", "exp1_2_prod.json", "2-niche rigid hand-seed partial G1"),
    ("Exp1.5", "exp1_5_prod.json", "3-niche m=0.40 partial G1"),
    ("Exp2_b1", "b1_prod.json", "no-pop-crossover soft K=1"),
    ("Exp2_b3", "b3_prod.json", "no-mutation soft K=1"),
    ("Exp2_b4", "b4_prod.json", "no-rigid soft K=1"),
    ("Exp2_b5", "b5_prod.json", "no-handseed soft K=1"),
]

rows = []
for run_id, fname, description in RUNS:
    fp = CACHE / fname
    if not fp.exists():
        continue
    p = json.load(open(fp))
    for entry in p.get("rcc_history", []):
        gen = entry["gen"]
        n_clusters = entry.get("n_clusters", 1)
        K_w_mean = entry.get("K_within_mean", 0.0)
        K_b_mean = entry.get("K_between_mean", None)
        rii_mean = entry.get("rii_mean", 0.0)
        rii_pairs = entry.get("rii_pairs", []) or []
        # Per-pair raw values
        if rii_pairs:
            for pair in rii_pairs:
                rows.append({
                    "run_id": run_id, "gen": gen, "k_total": n_clusters,
                    "pair_label": f"({pair['pair'][0]},{pair['pair'][1]})",
                    "K_AA_within": pair["K_AA"],
                    "K_BB_within": pair["K_BB"],
                    "K_AB_between": pair["K_AB"],
                    "rii_pair": pair["rii"],
                    "rii_mean_gen": rii_mean,
                    "K_within_mean_gen": K_w_mean,
                    "K_between_mean_gen": K_b_mean,
                    "n_clusters": n_clusters,
                    "type": "cross_cluster_pair",
                    "description": description,
                })
        else:
            # K=1 → no rii_pairs, K_b_mean=None
            rows.append({
                "run_id": run_id, "gen": gen, "k_total": n_clusters,
                "pair_label": "K=1_no_pairs",
                "K_AA_within": K_w_mean,  # population self-cross baseline
                "K_BB_within": K_w_mean,
                "K_AB_between": None,
                "rii_pair": None,
                "rii_mean_gen": rii_mean,
                "K_within_mean_gen": K_w_mean,
                "K_between_mean_gen": None,
                "n_clusters": n_clusters,
                "type": "K=1_population_baseline",
                "description": description,
            })

with open(OUT_CSV, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"Wrote {len(rows)} rows to {OUT_CSV}")

# Summary: distinguishing "no cluster" vs "high compat" for K=1 runs
import collections
print()
print("=== K=1 RII=0 runs — distinguishing 'no cluster' vs 'high compat' ===")
print("If K_within_mean is uniformly LOW (~0.05-0.15), even within population")
print("agents have low pairwise compat → no clusters because all agents incompatible")
print("If K_within_mean is HIGH (~0.5+), agents are uniformly compatible → no clusters")
print("because there's no separation.")
print()
print("Run                  | K_w_mean range  | Interpretation")
print("-" * 80)
for run_id, fname, _ in RUNS:
    fp = CACHE / fname
    if not fp.exists():
        continue
    p = json.load(open(fp))
    k_w_vals = [e.get("K_within_mean", 0.0) for e in p.get("rcc_history", []) if e.get("n_clusters", 1) == 1]
    if k_w_vals:
        lo = min(k_w_vals); hi = max(k_w_vals)
        mean = sum(k_w_vals) / len(k_w_vals)
        interp = "HIGH compat" if mean > 0.4 else "LOW compat" if mean < 0.2 else "MID compat"
        print(f"{run_id:20s} | {lo:.3f}-{hi:.3f} ({mean:.3f}) | {interp}")
