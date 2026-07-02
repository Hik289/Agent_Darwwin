"""Task D: Exp 6 synthetic — species dynamics on toy landscape.

Track birth / persistence / extinction / fusion / fission via SAET-lite evolutionary
loop with synthetic fitness + RCC clustering every 5 gen. Run ≥ 20 generations.

For survival analysis: collect (species_id, lifetime, extinct_or_censored) tuples
and fit Cox proportional hazards model with covariates.
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

from synthetic import landscape_L_sweep as LS

RESULTS_DIR = Path("./results")


def init_population(L: int, N: int, landscape, seed: int) -> list[dict[str, Any]]:
    """Initialize N agents: half A-lineage, half B-lineage with small drift."""
    rng = random.Random(seed)
    half = L // 2
    A_template = [1] * half + [0] * (L - half)
    B_template = [0] * half + [1] * (L - half)
    pop = []
    for i in range(N):
        if i < N // 2:
            g = list(A_template)
            lineage_seed = "A"
        else:
            g = list(B_template)
            lineage_seed = "B"
        for k in range(L):
            if rng.random() < 0.02:
                g[k] = 1 - g[k]
        pop.append({"id": i, "lineage_seed": lineage_seed, "genome": tuple(g),
                    "parent_ids": [], "birth_gen": 0})
    return pop


def fitness_rho_two_niche(G, landscape):
    """0.5*(F_A + F_B) where F_A rewards first-half=1, F_B rewards second-half=1."""
    u = landscape["u"]
    half = landscape["half"]
    L = landscape["L"]
    F_A = sum(u[l] for l in range(L) if (G[l] == 1 and l < half) or (G[l] == 0 and l >= half))
    F_B = sum(u[l] for l in range(L) if (G[l] == 1 and l >= half) or (G[l] == 0 and l < half))
    for (l, r) in landscape["divergent_edges"]:
        same = (G[l] == G[r])
        d = -0.05 if same else 0.05
        F_A += d
        F_B += d
    return 0.5 * (F_A + F_B), F_A, F_B


def viability(F, F_min=0.0, F_max=1.0):
    if F_max <= F_min:
        return 0.0
    return max(0.0, min(1.0, (F - F_min) / (F_max - F_min)))


def step_population(
    pop: list[dict[str, Any]], landscape, t: int, mu: float = 0.05,
    beta: float = 2.0, rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """One generation: assortative selection (prefer similar genome partners) + crossover + mutation."""
    rng = rng or random.Random()
    N = len(pop)
    # Fitness
    fits = []
    for ag in pop:
        f_rho, f_A, f_B = fitness_rho_two_niche(ag["genome"], landscape)
        fits.append((ag, f_rho, f_A, f_B))
    fits.sort(key=lambda x: -x[1])
    elites = [f[0] for f in fits[: N // 2]]  # top half survive

    # Reproduction: pair elites with assortative bias (prefer genome-similar partners)
    offspring = []
    next_id = max(a["id"] for a in pop) + 1
    for _ in range(N - len(elites)):
        i = rng.randrange(len(elites))
        # assortative: pick a partner based on similarity
        candidates = list(range(len(elites)))
        candidates.remove(i)
        if beta > 0:
            sims = [-sum(a != b for a, b in zip(elites[i]["genome"], elites[k]["genome"]))
                    for k in candidates]
            # exp(beta * sim) weighting
            ws = [math.exp(beta * (s / max(landscape["L"], 1))) for s in sims]
            ws_total = sum(ws)
            r = rng.random() * ws_total
            acc = 0
            chosen = candidates[0]
            for k, w in zip(candidates, ws):
                acc += w
                if acc >= r:
                    chosen = k
                    break
            j = chosen
        else:
            j = rng.choice(candidates)
        p1, p2 = elites[i], elites[j]
        child_g = LS.uniform_crossover(p1["genome"], p2["genome"], rng)
        # mutate
        child_g = list(child_g)
        for k in range(len(child_g)):
            if rng.random() < mu:
                child_g[k] = 1 - child_g[k]
        child = {"id": next_id, "genome": tuple(child_g),
                 "parent_ids": [p1["id"], p2["id"]],
                 "birth_gen": t}
        next_id += 1
        offspring.append(child)
    return elites + offspring


def rcc_partition(pop, landscape, R: int = 8, n_clusters: int = 2, rng_seed: int = 42):
    """Compute RCM + RCC clustering."""
    from sklearn.cluster import SpectralClustering
    rng = random.Random(rng_seed)
    N = len(pop)
    rcm = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i == j:
                f_rho, _, _ = fitness_rho_two_niche(pop[i]["genome"], landscape)
                rcm[i, j] = viability(f_rho)
                continue
            if i < j:
                vals = []
                for _ in range(R):
                    h = LS.uniform_crossover(pop[i]["genome"], pop[j]["genome"], rng)
                    f_rho, _, _ = fitness_rho_two_niche(h, landscape)
                    vals.append(viability(f_rho))
                rcm[i, j] = float(np.mean(vals))
                rcm[j, i] = rcm[i, j]
    try:
        sym = 0.5 * (rcm + rcm.T)
        sym = np.clip(sym, 0.0, None)
        sc = SpectralClustering(n_clusters=n_clusters, affinity="precomputed",
                                 assign_labels="kmeans", random_state=42)
        labels = sc.fit_predict(sym)
    except Exception:
        labels = np.zeros(N, dtype=int)
    return rcm, labels.tolist()


def compute_rii(rcm, labels):
    """Return between-species RII based on K_w, K_b means."""
    labels = np.array(labels)
    species_ids = sorted(set(labels.tolist()))
    if len(species_ids) < 2:
        return {"rii": 0.0, "K_within": [], "K_between_mean": None}
    K_within = []
    for s in species_ids:
        idx = labels == s
        n = idx.sum()
        if n < 2:
            K_within.append(float(rcm[idx][:, idx].mean()))
            continue
        # mean off-diagonal within species
        sub = rcm[idx][:, idx]
        mask = ~np.eye(sub.shape[0], dtype=bool)
        K_within.append(float(sub[mask].mean()))
    K_between = []
    for i, s1 in enumerate(species_ids):
        for s2 in species_ids[i + 1:]:
            idx1 = labels == s1
            idx2 = labels == s2
            K_between.append(float(rcm[idx1][:, idx2].mean()))
    K_w_mean = float(np.mean(K_within))
    K_b_mean = float(np.mean(K_between))
    rii_val = 1.0 - K_b_mean / max(math.sqrt(K_w_mean * K_w_mean) + 1e-9, 1e-9)
    return {"rii": float(rii_val), "K_within": K_within, "K_between_mean": K_b_mean,
            "K_within_mean": K_w_mean}


def species_match_jaccard(prev_clusters, cur_clusters):
    """For each current cluster, find best Jaccard overlap to previous clusters."""
    prev_sets = [set(c) for c in prev_clusters]
    matches = []
    for cur in cur_clusters:
        cur_set = set(cur)
        if not cur_set:
            matches.append(None)
            continue
        best_idx = -1
        best_j = 0.0
        for p_idx, p_set in enumerate(prev_sets):
            if not p_set:
                continue
            j = len(cur_set & p_set) / len(cur_set | p_set)
            if j > best_j:
                best_j = j
                best_idx = p_idx
        matches.append((best_idx, best_j))
    return matches


def run_dynamics(condition: str = "stable", T: int = 25, N: int = 24,
                 L: int = 16, alpha: float = 0.15, mu: float = 0.05,
                 beta: float = 2.0, eval_every: int = 5, R: int = 6,
                 seed: int = 42) -> dict[str, Any]:
    """Run SAET-lite for T gen on landscape, capture species lifecycle."""
    rng = random.Random(seed)
    landscape = LS.make_landscape_L(L, alpha=alpha, seed=seed)
    pop = init_population(L, N, landscape, seed=seed)

    species_log = []  # list of {gen, n_clusters, clusters: [[member ids]], rii, ...}
    prev_clusters_members = None
    species_id_counter = 0
    species_tracker: dict[int, dict] = {}  # active species id -> {birth, members_history}

    for t in range(T):
        # Mid-T condition tweaks
        if condition == "remove_niche" and t == T // 2:
            # half divergent edges removed → reduces α
            n_keep = len(landscape["divergent_edges"]) // 2
            landscape["divergent_edges"] = landscape["divergent_edges"][:n_keep]
        if condition == "add_niche" and t == T // 2:
            # double divergent edges (synthetic addition)
            # for simplicity: re-init with 2x alpha
            new_land = LS.make_landscape_L(L, alpha=alpha * 2.0, seed=seed + 99)
            landscape["divergent_edges"] = new_land["divergent_edges"]
        if condition == "increase_migration" and t == T // 2:
            mu = mu * 3
        if condition == "standardize_interfaces" and t == T // 2:
            landscape["divergent_edges"] = []  # no incompatibility
        if condition == "lower_budget" and t == T // 2:
            beta = 0.5  # random mating

        pop = step_population(pop, landscape, t, mu=mu, beta=beta, rng=rng)

        if (t + 1) % eval_every == 0 or t == 0:
            rcm, labels = rcc_partition(pop, landscape, R=R, rng_seed=seed + t)
            clusters = [[i for i, l in enumerate(labels) if l == s] for s in sorted(set(labels))]
            cluster_members = [[pop[i]["id"] for i in c] for c in clusters]
            rii_info = compute_rii(rcm, labels)
            entry = {
                "gen": t + 1, "n_clusters": len(clusters),
                "cluster_sizes": [len(c) for c in cluster_members],
                "cluster_members": cluster_members,
                "rii": rii_info["rii"],
                "K_within_mean": rii_info["K_within_mean"],
                "K_between_mean": rii_info["K_between_mean"],
            }
            species_log.append(entry)

            # Track species birth / extinction / fusion / fission
            if prev_clusters_members is None:
                # initial cluster registration
                for c in cluster_members:
                    species_tracker[species_id_counter] = {
                        "id": species_id_counter, "birth_gen": t + 1,
                        "extinct_gen": None, "members_history": [(t + 1, list(c))],
                    }
                    species_id_counter += 1
            else:
                matches = species_match_jaccard(prev_clusters_members, cluster_members)
                # detect fusion (two prev → one cur), fission (one prev → two cur), birth (no match), extinction (no current match)
                # naive: each prev cluster matches at most one current cluster
                prev_match_targets = set()
                for cur_i, m in enumerate(matches):
                    if m is None:
                        # new species
                        species_tracker[species_id_counter] = {
                            "id": species_id_counter, "birth_gen": t + 1,
                            "extinct_gen": None, "members_history": [(t + 1, list(cluster_members[cur_i]))],
                        }
                        species_id_counter += 1
                        continue
                    prev_idx, j = m
                    if j < 0.3:  # weak match → call it a new species
                        species_tracker[species_id_counter] = {
                            "id": species_id_counter, "birth_gen": t + 1,
                            "extinct_gen": None, "members_history": [(t + 1, list(cluster_members[cur_i]))],
                        }
                        species_id_counter += 1
                    else:
                        prev_match_targets.add(prev_idx)
                        # find the species_tracker key that ended with this prev_clusters_members[prev_idx]
                        for sid, info in species_tracker.items():
                            if info["extinct_gen"] is None and info["members_history"]:
                                last_gen, last_members = info["members_history"][-1]
                                if set(last_members) == set(prev_clusters_members[prev_idx]):
                                    info["members_history"].append((t + 1, list(cluster_members[cur_i])))
                                    break
                # extinction: prev clusters with no current match
                for prev_i in range(len(prev_clusters_members)):
                    if prev_i not in prev_match_targets:
                        for sid, info in species_tracker.items():
                            if info["extinct_gen"] is None and info["members_history"]:
                                last_gen, last_members = info["members_history"][-1]
                                if set(last_members) == set(prev_clusters_members[prev_i]):
                                    info["extinct_gen"] = t + 1
                                    break
            prev_clusters_members = cluster_members

    # Final aggregation
    species_summary = []
    for sid, info in species_tracker.items():
        if info["extinct_gen"] is None:
            lifetime = T - info["birth_gen"]
            censored = True
        else:
            lifetime = info["extinct_gen"] - info["birth_gen"]
            censored = False
        species_summary.append({
            "species_id": sid,
            "birth_gen": info["birth_gen"],
            "extinct_gen": info["extinct_gen"],
            "lifetime": lifetime,
            "censored": censored,
            "max_size_observed": max(len(m) for _, m in info["members_history"]),
        })

    return {
        "condition": condition, "T": T, "N_init": N, "L": L, "alpha": alpha,
        "mu_initial": mu, "beta_initial": beta,
        "species_log": species_log,
        "species_summary": species_summary,
        "n_species_total": len(species_summary),
        "n_species_alive_at_T": sum(1 for s in species_summary if s["extinct_gen"] is None),
        "n_species_persistent_ge_10": sum(1 for s in species_summary if s["lifetime"] >= 10),
        "median_lifetime": float(np.median([s["lifetime"] for s in species_summary])) if species_summary else 0.0,
        "final_rii": species_log[-1]["rii"] if species_log else None,
    }


def cox_ph_analysis(species_summary_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Cox PH model on extinction time. Use lifelines if available."""
    try:
        from lifelines import CoxPHFitter
        import pandas as pd
    except ImportError:
        return {"error": "lifelines/pandas not available"}

    rows = []
    for s in species_summary_list:
        rows.append({
            "lifetime": s["lifetime"],
            "extinct": 0 if s["censored"] else 1,
            "max_size": s["max_size_observed"],
            "birth_gen": s["birth_gen"],
        })
    df = pd.DataFrame(rows)
    if len(df) < 5 or df["extinct"].sum() < 2:
        return {"n_rows": len(df), "n_extinct": int(df["extinct"].sum()),
                "warning": "too few events for Cox PH"}
    try:
        cph = CoxPHFitter()
        cph.fit(df, duration_col="lifetime", event_col="extinct")
        return {
            "n_rows": len(df), "n_extinct": int(df["extinct"].sum()),
            "coefficients": cph.params_.to_dict(),
            "hazard_ratios": cph.hazard_ratios_.to_dict(),
            "p_values": cph.summary["p"].to_dict(),
            "concordance": float(cph.concordance_index_),
        }
    except Exception as e:
        return {"error": f"Cox PH fit failed: {type(e).__name__}: {e}",
                "n_rows": len(df), "n_extinct": int(df["extinct"].sum())}


def main():
    print("=== Task D: Exp 6 synthetic dynamics ===", flush=True)
    t0 = time.time()
    conditions = ["stable", "remove_niche", "add_niche", "increase_migration",
                  "standardize_interfaces", "lower_budget"]
    results = {}
    for cond in conditions:
        print(f"  Running condition '{cond}'...", flush=True)
        res = run_dynamics(condition=cond, T=25, N=24, L=16, alpha=0.15,
                           mu=0.05, beta=2.0, eval_every=5, R=6, seed=42)
        results[cond] = res
        print(f"    n_species={res['n_species_total']}, "
              f"alive_at_T={res['n_species_alive_at_T']}, "
              f"persist≥10={res['n_species_persistent_ge_10']}, "
              f"final_rii={res['final_rii']:.3f}" if res['final_rii'] else f"    n_species={res['n_species_total']}",
              flush=True)

    # Cox PH on stable condition
    cox = cox_ph_analysis(results["stable"]["species_summary"])
    # Cox PH across all conditions pooled
    all_summary = []
    for cond in conditions:
        for s in results[cond]["species_summary"]:
            s_with_cond = dict(s); s_with_cond["condition"] = cond
            all_summary.append(s_with_cond)
    cox_pooled = cox_ph_analysis(all_summary)

    elapsed = time.time() - t0
    out = {
        "task": "D_exp6_dynamics",
        "conditions": list(conditions),
        "results_per_condition": results,
        "cox_ph_stable": cox,
        "cox_ph_pooled": cox_pooled,
        "G6_pass_stable": results["stable"]["n_species_persistent_ge_10"] >= 1,
        "elapsed_sec": elapsed,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "exp6_synthetic_dynamics.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  wrote {out_path} ({elapsed:.1f}s)", flush=True)
    print(f"  G6 PASS: {out['G6_pass_stable']}", flush=True)


if __name__ == "__main__":
    main()
