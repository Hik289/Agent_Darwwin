# EXP_DESIGN.md — agentspecies 实验执行计划

> **维护**: Anonymous artifact notes
> **阶段**: EXP_DESIGN
> **日期**: 2026-06-19 JST
> **机器**: SERVER_HOSTNAME (SERVER_HOSTNAME, 112 cores + 1TiB RAM, 4× RTX 6000 Ada — GPU 可选, 不强求)
> **存储根**: `./` (SERVER_HOSTNAME /home 92% 满, 强制 /data1)
> **LLM**: Azure gpt-5.4-mini (endpoint/key 仅写入实验代码, 不进 agent config)
> **预算**: 总 500 USD 硬上限; pilot ≤ 50 USD
> **配套文档**:
>   - `ROADMAP.md` (day-shaped milestone + abort gate 触发流程)
>   - `analysis/hypothesis.md` (5 个假设 H1-H5)
>   - `analysis/theory_draft.md` (EST v0.1, 4 定理 + L_c)
>   - `data/niche_profiles.md` (4 niche 接入 + 校准)
>   - `data/synthetic_landscape_spec.md` (toy 解析真值)
>   - `data/founder_genome_v0.{json,md}` (MAG schema + mutation operator)

⚠️ 这是**实验设计文档**, 不是实验代码。所有 pseudocode 用于约束 RUNNING 阶段 ml_engineer 的实现 + 让 Verifier 在 RUNNING 时能 catch 偏离。

---

## 0. 全局约定与符号

| 符号 | 定义 |
|---|---|
| $N$ | population size (pilot 16, main 64) |
| $T$ | generations (pilot 20, main 100) |
| $K$ | niches count (pilot 2, main 4) |
| $R$ | hybrid offspring per parent pair (pilot 8, main 16) |
| $\mu$ | mutation rate (founder 0.05) |
| $m$ | migration rate between niches (default 0.10) |
| $\beta$ | assortativity strength (default 2) |
| $\tau_v$ | viability threshold (校准而得, anchor_1) |
| $\mathcal{P}_t$ | population at generation $t$ |
| $\mathcal{A}_t$ | archive (累积保留的高 fitness agents) |
| $G_i$ | agent $i$ 的 MAG (Modular Agent Genome) |
| $F_e(G)$ | agent $G$ 在 niche $e$ 上 fitness ∈ [0,1] |
| $V(o)$ | hybrid offspring $o$ 的 viability ∈ [0,1] |
| $K(i,j)$ | pairwise compatibility, $R$ 个 hybrid 的平均 viability |
| RII | reproductive isolation index, 公式见 hypothesis.md §H_def |
| HFL | hybrid fitness loss |
| RCM | reproductive compatibility matrix ($N \times N$) |
| RCC | reproductive compatibility clustering 算法 |

**Seed 约定**: 主实验 5 seeds (42, 123, 456, 789, 1024), pilot 2 seeds (42, 123)。
**Niche 子集**: 见 niche_profiles.md §2.4/3.4/4.6/5.5。

---

## 1. 通用框架 (统一 pseudocode, 9 baselines 复用)

### 1.1 SAET evolutionary loop (Exp 1/2/3/4/5/6/7 主流程)

```text
SAET(N, T, K, niches, founder, mu, m, beta, R, eval_every=5):
    P_0 ← initialize_population(N, founder, mu_init=0.01)   # 同一 founder 加 epsilon mutation
    A   ← []                                                # archive
    lineage_tree ← LineageTree(P_0)
    rcc_history  ← []
    for t = 0 .. T-1:
        # 1. 分配 + 评估 niche fitness
        niche_assign ← assign_to_niches(P_t, K, m)
        fitness ← {i: eval_fitness(G_i, niche_assign[i]) for i in P_t}

        # 2. archive 更新
        A ← update_archive(A, P_t, fitness, max_size=2*N)

        # 3. parent selection (compatibility-aware, assortative)
        parents ← select_parents(P_t, fitness, A,
                                  K_hat=compat_predictor.predict,
                                  beta=beta)

        # 4. recombination + mutation
        offspring ← []
        for (i, j) in parents:
            if random() < 0.5:                              # 50% 内重组, 50% 外重组
                child ← typed_subgraph_crossover(G_i, G_j)
            else:
                child ← typed_subgraph_crossover(G_j, G_i)  # reciprocal
            child ← mutate(child, mu)
            child ← validate_or_repair(child)               # 三关
            offspring.append(child)

        # 5. evaluate offspring
        offspring_fit ← eval_offspring(offspring, niche_assign)

        # 6. survivor selection
        P_{t+1} ← survive_N(P_t ∪ offspring, fitness ∪ offspring_fit, N)

        # 7. migration
        P_{t+1} ← migrate(P_{t+1}, m)

        # 8. RCM + RCC every `eval_every` gen
        if (t+1) % eval_every == 0:
            rcm ← estimate_RCM(P_{t+1}, R, active_sampling=True)
            species ← RCC(rcm, tau_in, tau_out, n_min=4)
            persistence ← match_species_across_gen(species, rcc_history[-3:])
            rcc_history.append({t: t+1, rcm, species, persistence})

        # 9. compat_predictor active-learning update
        compat_predictor.update_from(rcm if rcm_just_computed else None)

        # 10. checkpoint
        if (t+1) % 10 == 0: persist_state(P_{t+1}, A, rcc_history)

    return {population: P_T, archive: A, rcc_history: rcc_history,
            lineage_tree: lineage_tree}
```

**关键不变量** (Verifier RUNNING 阶段 catch):
- `len(P_t) == N` for all t
- 每代 offspring 必须 ≥ 0.25 N (否则 evolutionary pressure 不够)
- 每代有 ≥ 1 个 reciprocal pair (typed crossover 双向必须)
- `eval_every` 不能 > 10 (否则 rcc_history 过稀, persistence 信号不可观测)

### 1.2 typed subgraph crossover

```text
typed_subgraph_crossover(G_A, G_B):
    # 1. 选同源模块类别 (7 module 之一, 或 workflow 整体)
    module_choice ← random.choice(['planner','workflow','memory','tools','verifier','communication','update_policy'])

    # 2. 从 G_A 复制 module_choice 对应的 typed subgraph Q
    Q ← extract_typed_subgraph(G_A, module_choice)

    # 3. 替换 G_B 对应 subgraph
    G_child ← replace_subgraph(G_B, module_choice, Q)

    # 4. 用 typed ports 重连
    G_child ← reconnect_typed_ports(G_child)

    # 5. 仅修复 语法 / 类型错误 (不做语义修复!)
    G_child ← syntax_fix(G_child)
    G_child ← type_check_fix(G_child)
    # ⚠️ 不调用 semantic_repair() — 否则破坏 EST 定理 2 的接口边界论证

    return G_child
```

### 1.3 RCM estimation (active sampling)

```text
estimate_RCM(P, R, active_sampling=True):
    rcm ← zeros(N, N)
    # 优先 sample pairs: (a) compat_predictor 不确定度高 (b) 候选 species boundary
    if active_sampling:
        priority_pairs ← top_K_uncertain_pairs(compat_predictor, P, k=N*(N-1)/4)
    else:
        priority_pairs ← all_pairs(P)

    for (i, j) in priority_pairs:
        hybrids ← [typed_subgraph_crossover(G_i, G_j) for _ in range(R)]
        viab    ← [V(o) for o in hybrids]
        rcm[i,j] ← mean(viab)
        rcm[j,i] ← rcm[i,j]    # 假设对称 (reciprocal hybrid 已在 SAET loop §1.1 step 4 双向跑)

    # 未覆盖的 pair: 用 compat_predictor 填补
    for (i, j) in non_priority_pairs:
        rcm[i,j] ← compat_predictor.predict(G_i, G_j)
        rcm[j,i] ← rcm[i,j]

    return rcm
```

**RCM budget rule**: 每代 RCM estimation 最多消耗 `0.5 * N * R` 个 hybrid evaluation, 防止 API budget 失控。

### 1.4 RCC clustering

```text
RCC(rcm, tau_in=0.65, tau_out=0.40, n_min=4):
    # 1. 构建 compatibility graph: vertex = agent, edge weight = rcm[i,j]
    G ← build_graph_from(rcm)

    # 2. spectral clustering on Laplacian, 自适应 K = elbow on eigengap
    K_hat ← estimate_K_eigengap(G)
    clusters ← spectral_clustering(G, K_hat)

    # 3. apply hard constraints
    valid_clusters ← []
    for S in clusters:
        K_within ← mean(rcm[S,S])
        K_between ← max([mean(rcm[S,S_other]) for S_other in clusters if S_other != S])
        if K_within >= tau_in and K_between <= tau_out and |S| >= n_min:
            valid_clusters.append({members: S, K_within, K_between})

    return valid_clusters
```

**Persistence rule**: species $S$ 在代 $t$ 被确认, 当且仅当跨 $t-L, t-L+5, \ldots, t$ ($L=10$, eval_every=5, 即 3 个 RCC 时点) 该 species 都存在且 member overlap (Jaccard) ≥ 0.6。

### 1.5 fitness eval (4 niches)

```text
eval_fitness(G, niche):
    if niche == 'planning': return planbench_eval(G, sample_30_tasks)
    if niche == 'web':      return webarena_eval(G, sample_20_tasks)
    if niche == 'code':     return swebench_lite_eval(G, sample_10_tasks)
    if niche == 'memory':   return locomo_eval(G, sample_10_tasks)
    # 每代每 agent 在所属 niche 上抽 N task 评估 (节省 API)
```

每代每 agent eval 一次, 不重复跑。

---

## 2. 9 个 Baseline (each ≤ 15 lines pseudocode)

每个 baseline 都套用 §1.1 的 SAET loop 框架, 只改 `select_parents` / `recombination` / `archive` / `niche` 4 个组件。

### 2.1 Static Founder
```text
StaticFounder(N, T, niches, founder):
    P ← clone(founder, N copies + epsilon)
    for t = 0..T-1: eval_fitness(P, niches)                  # 不 mutation, 不 recomb
    return rcm(P), rcc(P)
```
目的: 提供"无演化"基线, RII 应 ≈ 0 (no divergence).

### 2.2 Random Drift
```text
RandomDrift(N, T, niches, mu):
    P ← clone(founder, N)
    for t:
        P ← [mutate(G, mu) for G in P]                       # 随机 mutate, 不 select
        if random() < 0.5: P ← [random_pair_typed_crossover(P)]
```
目的: 检测 isolation 是否仅由遗传漂变产生 (应该 RII < 0.10).

### 2.3 Greedy Archive
```text
GreedyArchive(N, T, niches, mu):
    A ← {founder}
    for t:
        elite ← argmax_F(A)
        children ← [mutate(elite, mu) for _ in range(N)]
        A ← A ∪ {children with F > median(A)}
    P_T ← sample(A, N)
```
目的: 测试 strong selection 是否导致 single lineage 垄断 (RII 应 ≈ 0, 但 best fitness 高).

### 2.4 Tournament Evolution
```text
TournamentEvo(N, T, niches, mu, k=3):
    P ← clone(founder, N)
    for t:
        parents ← [tournament_select(P, k=3) for _ in range(N//2)]
        offspring ← [typed_crossover(p[0], p[1]) for p in parents] + [mutate(...)]
        P ← survive_N(P ∪ offspring, N)
```
目的: 标准 evolutionary baseline.

### 2.5 PBT-style
```text
PBT(N, T, niches, mu, exploit_every=5):
    P ← clone(founder, N), each in random niche
    for t:
        P ← [mutate(G, mu) for G in P]
        if t % exploit_every == 0:
            bottom_quartile ← argmin_F(P, q=0.25)
            top_quartile    ← argmax_F(P, q=0.25)
            for G in bottom_quartile:
                G ← perturb_params(random.choice(top_quartile))   # exploit + explore
```
目的: 自适应 hyperparam evolution baseline, 测试 exploit/explore 是否产生 species.

### 2.6 Novelty Search
```text
NoveltySearch(N, T, niches, mu, k_NN=15):
    P ← clone(founder, N); archive ← []
    for t:
        behavior ← [extract_behavior(G) for G in P]              # 6-dim vector: niche success rate × 4 + token cost + workflow depth
        novelty  ← [mean(top_k_NN_dist(behavior[i], archive, k_NN)) for i]
        parents  ← tournament_select_by(P, novelty, k=3)
        offspring ← [typed_crossover + mutate(parents)]
        P ← survive_N(by_novelty, P ∪ offspring, N)
        archive.extend(behavior)
```
目的: 高 behavioral diversity, 期望 RII 仍 < 0.10 (G2 反证主力).

### 2.7 MAP-Elites
```text
MAPElites(N, T, niches, mu, bins=(6,6)):
    grid ← empty(bins)        # 2-dim behavior descriptor: avg_workflow_depth × avg_tool_count
    grid[founder_cell] ← founder
    for t:
        for _ in range(N):                                        # N evals per gen
            parent ← random_cell(grid, non_empty)
            child  ← mutate(parent, mu)
            desc   ← behavior_descriptor(child)
            cell   ← discretize(desc, bins)
            if grid[cell] is None or F(child) > F(grid[cell]):
                grid[cell] ← child
    P_T ← non_empty_cells(grid)
```
目的: QD baseline, 高 coverage 但 RII 应 < 0.10 (G2 反证).

### 2.8 DGM-style Archive
```text
DGMArchive(N, T, niches, mu):
    A ← {founder}
    for t:
        for _ in range(N):
            parent ← sample_proportional_to_fitness(A)
            child  ← self_modify(parent, mu)                     # 通常无性, 自修改
            if F(child) > tau_archive:
                A ← A ∪ {child}
    P_T ← sample(A, N, recent_first)
```
目的: open-ended archive baseline, lineage_tree 应分叉但 RII < 0.10.

### 2.9 Pop-LLM-Evo
```text
PopLLMEvo(N, T, niches, mu):
    P ← clone(founder, N)
    for t:
        scores ← [eval_fitness(G, niche=random) for G in P]
        parents ← roulette_wheel_select(P, scores, N)
        offspring ← []
        for (i, j) in parents:
            child ← typed_crossover(P[i], P[j])
            child ← mutate(child, mu)
            offspring.append(child)
        P ← top_N(offspring ∪ P, scores, N)
```
目的: 标准 population-LLM evolution, vanilla baseline.

---

## 3. Metrics (统一 schema 字段名)

| Metric | 定义 | results.json 字段 | 单位 | 期望 |
|---|---|---|---|---|
| **RII** | $1 - K_{ab}/\sqrt{K_{aa}K_{bb}}$ | `metrics.rii[species_pair]` | float [0,1] | SAET > 0.25, baseline < 0.10 |
| **HFL** | $1 - E[F(G_{a\times b})]/(0.5(F_a+F_b))$ | `metrics.hfl[species_pair]` | float [0,1] | > 0.30 if RII > 0.25 |
| **K_within** | mean(rcm[S,S]) | `metrics.k_within[species_id]` | float [0,1] | ≥ 0.65 |
| **K_between** | mean(rcm[S,S_other]) | `metrics.k_between[(s1,s2)]` | float [0,1] | ≤ 0.40 |
| **Behavioral Diversity** | mean pairwise cosine dist of behavior vectors | `metrics.behavior_div` | float [0,1] | report |
| **Coverage** | non-empty cells / total bins (MAP-Elites) | `metrics.coverage` | float [0,1] | report |
| **Persistence** | max consecutive RCC time-points with same species | `metrics.persistence[species_id]` | int generations | ≥ 10 |
| **Lineage Tree Depth** | max(node.depth) | `metrics.lineage_depth` | int | report |
| **Species Count** | len(rcc_valid_clusters) at T | `metrics.species_count` | int | ≥ 2 in 3/5 seeds |
| **best_fitness** | max_i F(G_i) | `metrics.best_fitness` | float [0,1] | report |
| **mean_fitness** | mean F over P_T | `metrics.mean_fitness` | float [0,1] | report |
| **API_cost_usd** | cumulative token cost | `cost.total_usd` | USD | per-exp budget |
| **wallclock_sec** | start to end seconds | `cost.wallclock_sec` | sec | per-exp |

**Bootstrap CI**: 所有 metric 报告 mean ± 95% CI, B = 1000 resample.

**Epistatic load** (Exp 4 主回归预测变量): 用 hybrid 中每条 lineage-divergent edge 的 $\delta_{\ell r}$ 之和。实现:
```text
L_epi(i, j) = sum over edge (l,r) in E_G of |J_i(g_l^i, g_r^i) - J_j(g_l^j, g_r^j)|
```
`metrics.epistatic_load[(i,j)]` float.

---

## 4. Statistical Protocol

### 4.1 Bootstrap CI
所有点估计 (RII, HFL, K_w, K_b, AUROC) 报 mean + 95% CI, **B = 1000** resample, 用 `scipy.stats.bootstrap`。

### 4.2 Paired t-test
对比同 seed 下 SAET vs baseline (Exp 1, 2, 6, 7), 用 paired t-test (因 5 seeds 共享 founder + 任务 subset)。
- 实现: `scipy.stats.ttest_rel`, alpha = 0.05

### 4.3 Permutation test
对比独立组 (e.g. Exp 3 RCC vs Genome Distance, Exp 5 sub-threshold vs super-threshold), 用 permutation test, **B = 10000 permutations**.
- 实现: 自写或 `scipy.stats.permutation_test`

### 4.4 Multiple comparison correction
**Holm-Bonferroni** 校正:
- 应用范围:
  - Exp 2 表 2 (9 baselines vs SAET → 9 个 paired test → Holm 校正)
  - Exp 3 表 3 (6 detector vs RCC → 6 test → Holm)
  - Exp 4 表 4B (6 module pair → 6 test → Holm)
- 实现: `statsmodels.stats.multitest.multipletests(method='holm')`
- 报告 raw p + adjusted p

### 4.5 Regression (Exp 4) — 严格分离 4 个系数
```
HFL_ij = γ_0
       + γ_epi    * L_epi(i,j)
       + γ_gd     * d_genome(i,j)       # Hamming on module categorical fields
       + γ_niche  * d_niche(i,j)        # niche-profile cosine dist
       + γ_behav  * d_behav(i,j)        # behavior embedding L2 dist
       + γ_iface  * d_interface(i,j)    # number of schema-version mismatches
       + u_seed   * Z_seed              # random effect by seed
       + u_bench  * Z_bench             # random effect by benchmark
       + ε
```
- 实现: `statsmodels.MixedLM`
- 假设 H4 通过: `|γ_epi| > |γ_gd|` and `|γ_epi| > |γ_behav|` and `p(γ_epi) < 0.01`
- 收集数据规模: 至少 200 (i,j) pair × 5 seeds = 1000 row 才允许跑回归 (VIF 检查 < 5).

### 4.6 Sample size
- 主表所有数字 ≥ 3 seeds (anchor + 部分 ablation)
- main exp 全部 5 seeds (42, 123, 456, 789, 1024)
- Exp 5 L-sweep 由于成本敏感, 各 L 点 ≥ 3 seeds, L = L_c ± 1 处必须 5 seeds

### 4.7 Pre-registration
所有 abort gate 阈值 + 假设 + 主回归公式 **写入 EXP_DESIGN.md 后 frozen**, 跑实验前不得改 (改 = 偏离 Director 派单, Verifier 会 catch)。

---

## 5. results.json schema (frozen, 下游 paper_writer / data_scientist 必读)

```json
{
  "project_id": "agentspecies",
  "experiment_id": "exp_1",
  "experiment_name": "Multi-niche speciation main",
  "timestamp": "2026-06-XX T XX:XX:XX+09:00",
  "method": "SAET",
  "config": {
    "N": 64, "T": 100, "K": 4, "R": 16, "mu": 0.05, "m": 0.10, "beta": 2.0,
    "seeds": [42,123,456,789,1024],
    "niches": ["planning","web","code","memory"],
    "tau_v": 0.55,
    "tau_in": 0.65, "tau_out": 0.40, "n_min": 4,
    "eval_every": 5,
    "founder_genome_path": "data/founder_genome_v0.json"
  },
  "environment": {
    "machine": "SERVER_HOSTNAME",
    "python": "3.10.12",
    "key_packages": {"openai": "1.x", "scipy": "1.x", "scikit-learn": "1.x", "networkx": "3.x"}
  },
  "metrics": {
    "rii":            { "(species_0, species_1)": {"mean": 0.34, "ci_lo": 0.28, "ci_hi": 0.40, "n_pairs": 30} },
    "hfl":            { "(species_0, species_1)": {"mean": 0.42, "ci_lo": 0.36, "ci_hi": 0.48} },
    "k_within":       { "species_0": {"mean": 0.71, "ci_lo": 0.66, "ci_hi": 0.76} },
    "k_between":      { "(species_0, species_1)": {"mean": 0.31, "ci_lo": 0.26, "ci_hi": 0.36} },
    "persistence":    { "species_0": 15, "species_1": 12 },
    "species_count":  { "values_by_seed": {"42": 2, "123": 3, "456": 2, "789": 1, "1024": 2}, "mean": 2.0 },
    "best_fitness":   { "by_niche": { "planning": 0.78, "web": 0.42, "code": 0.18, "memory": 0.55 } },
    "mean_fitness":   { "value": 0.48, "std": 0.04 },
    "behavior_div":   { "value": 0.38, "ci_lo": 0.34, "ci_hi": 0.42 },
    "coverage":       null,
    "epistatic_load": { "mean_inter_species": 4.2, "mean_intra_species": 0.8 },
    "lineage_depth":  { "max": 18, "mean": 12.4 }
  },
  "statistics": {
    "rii_vs_zero":          { "test": "permutation", "B": 10000, "p_value": 0.0001 },
    "saet_vs_map_elites":   { "test": "paired_t", "stat": 5.32, "p_raw": 0.001, "p_holm": 0.009 }
  },
  "rcc_history": [
    { "gen": 5,  "species_found": 1, "rcm_path": "rcm_seed42_gen5.npz" },
    { "gen": 10, "species_found": 2, "rcm_path": "rcm_seed42_gen10.npz" }
  ],
  "cost": {
    "total_usd": 32.4,
    "by_niche": {"planning": 8.1, "web": 14.2, "code": 6.5, "memory": 3.6},
    "tokens": {"prompt": 12500000, "completion": 1800000},
    "wallclock_sec": 86400
  },
  "abort_gate_status": {
    "triggered": false,
    "checks": [
      {"gate": "G1.cost_breach", "value": 32.4, "threshold": 150.0, "ok": true},
      {"gate": "G1.no_signal_by_gen30", "value_at_gen30": 0.18, "threshold": 0.15, "ok": true}
    ]
  },
  "notes": "..."
}
```

**多个 sub-run (e.g. seed 间) 合并方法**:
- 单 experiment = 单 results.json
- 内部 metrics 报 mean + per-seed values_by_seed dict
- 若必须分文件 (e.g. RCC 历史矩阵), 用相对路径 `rcm_seedXX_genYY.npz`

---

## 6. Exp 1–7 spec (每个 Exp 列 (a)-(g) 七项)

---

### Exp 1 — Multi-niche Speciation Emergence

> **目的**: H1 主验证 — 4-niche SAET 出现稳定 RII > 0.25 species
> **对应假设**: H1
> **对应表**: AI_Agent_Speciation.md Table 1

#### (a) Inputs
- founder: `data/founder_genome_v0.json` (固定)
- niche subsets:
  - PlanBench main: 300 task, 每代 sample 30 (見 niche_profiles.md §2.5)
  - WebArena main: 100 task, 每代 sample 20
  - SWE-bench Lite: 100 task, 每代 sample 10
  - LoCoMo: 100 task, 每代 sample 10
- N = 64, T = 100, R = 16, K = 4
- seeds: [42, 123, 456, 789, 1024] (5 seeds)
- niche assignment 配置:
  - cell_1: PlanBench only (homogeneous control)
  - cell_2: PlanBench + Code (2-niche)
  - cell_3: 4-niche (main)
  - cell_4: alternating (T=20 切换 niche)
  - cell_5: 4-niche + migration m=0.20 (vs default 0.10)

#### (b) Method
- SAET (§1.1) — main method
- Static Founder (§2.1), MAP-Elites (§2.7), Tournament (§2.4), Greedy (§2.3) — 4 baselines for control rows in Table 1
- 仅在 cell_3 (4-niche main) 上跑全部 9 baseline (主表移到 Exp 2), 这里 Exp 1 只跑 5 niche configuration × {Static, MAP-Elites, SAET} = 15 run

#### (c) Metrics
- 主指标: RII (per species pair), HFL, K_w, K_b, persistence
- 辅指标: species_count, best_fitness, behavior_div, mean_fitness
- 全部按 §3 schema 写入 results.json

#### (d) Statistical protocol
- 5 seeds → 报 mean + 95% CI bootstrap B=1000
- SAET vs Static Founder paired_t (各 niche config 内部)
- SAET 4-niche vs SAET 1-niche permutation test, B=10000
- alpha = 0.05, **Holm 校正 5 个 cell × 3 方法的 15 comparison**

#### (e) Results JSON schema
按 §5 通用 schema; `experiment_id = "exp_1"`, `cells: [cell_1, ..., cell_5]` 每个 cell 一个嵌套 metric block.

#### (f) Budget & Wallclock
- 单 run cost (cell_3, N=64, T=100, R=16, 4 niches, 5 seeds):
  - PlanBench evals: 30 task × 64 agent × 100 gen × 5 seed = 960K evals, ~ 800 tokens/eval ~ 0.77B input tokens
  - WebArena: 20 × 64 × 100 × 5 = 640K evals × ~4K tokens = 2.56B tokens (主成本来源!)
  - SWE-bench Lite: 10 × 64 × 100 × 5 = 320K evals × ~3K tokens = 0.96B tokens
  - LoCoMo: 10 × 64 × 100 × 5 = 320K eval × ~4K tokens = 1.28B tokens
  - hybrid evals (RCM): 0.5 * 64 * 16 * 20 RCM 时点 * 5 seed = 51200 hybrid × 4 niche × ~1K avg eval = ~0.20B token
  - **gpt-5.4-mini Azure 价格估**: ~$0.15/1M input, ~$0.60/1M output, 8:1 input:output → **per Exp 1 cell_3 cost ≈ $80–130 USD**
- 其他 cell 较便宜 (1-niche cell_1 ≈ $8, 2-niche cell_2 ≈ $20)
- **Exp 1 total budget**: $130–180 USD (含所有 5 cell × {SAET, Static, MAP-Elites})
- Wallclock: 4 niche 并行 (SERVER_HOSTNAME 112 cores), SAET 5 seeds 并行 → 约 4–5 天

#### (g) Abort gate
**G1.1** (no signal pilot): 若 pilot (N=16, T=20) cell_3 在 gen 15 RII < 0.10 (no signal) → 升级 Director 检查 founder + crossover 实现, 不进 main
**G1.2** (cost breach): 若 cell_3 单 seed 跑到 gen 30 已 > $40 → 暂停, 降 task 抽样到一半, 升级 Director
**G1.3** (assertion violation): 若 anchor_4 single-niche cell_1 RII > 0.10 (违反定理 3) → 整个 Exp 1 暂停, 通知 Director
**G1.4** (H1 partial fail): main 跑完, 4-niche cell_3 在 < 2/5 seeds 出现 stable species → 上报 H1 partial, 但 Exp 2-7 继续

---

### Exp 2 — Baseline Comparison (Diversity ≠ Species)

> **目的**: H2 G2 反证 — diversity baselines 在相同 diversity 下 RII < 0.10
> **对应表**: Table 2 (9 baseline)

#### (a) Inputs
- 同 Exp 1 cell_3 (4-niche main)
- 9 baselines: §2.1–§2.9 各一次跑 + SAET = 10 runs × 5 seeds = 50 runs
- ⚠️ 部分 baseline 已经在 Exp 1 跑过 (Static, MAP-Elites, Tournament, Greedy), 这里 **reuse 已跑 results, 只补跑 5 新 baseline** (Random Drift, PBT, Novelty Search, DGM-style, Pop-LLM-Evo)

#### (b) Method
- 9 baseline 各按 §2 pseudocode 跑
- 全部跑 N=64, T=100, 4-niche, 5 seeds, R=16

#### (c) Metrics
- Table 2 全部列: best_fit, mean_fit, coverage (仅 MAP-Elites 适用, 其他 null), behavior_div, RII, HFL, species_count, cost
- 关键 cross-baseline 计算: **diversity-matched 子集** — 找 RII < 0.10 的 baseline 中 behavior_div 最高的, 与 SAET 同等 behavior_div 切片对比 RII

#### (d) Statistical protocol
- SAET vs 每个 baseline paired_t, **Holm 校正 9 comparison**
- 主声明: SAET RII > baseline RII + 0.15 (p < 0.05 after Holm)
- 若 MAP-Elites / Novelty 的 behavior_div ≥ SAET 但 RII < 0.10 → G2 confirm

#### (e) Results JSON schema
`experiment_id = "exp_2"`, `methods: [...]` array of 10 method blocks.

#### (f) Budget & Wallclock
- 新跑 5 baseline × 5 seed × cell_3 cost ≈ $80–120 USD
- Wallclock: 5 baseline × 5 seed 并行, ~5–7 天 (与 Exp 1 部分 overlap)

#### (g) Abort gate
**G2.1**: 若 MAP-Elites / Novelty 的 RII ≥ 0.20 → G2 反证失败, 上报 (H2 需重 frame)
**G2.2** (cost): 累计跑 > $200 → 暂停, 降低 5 seed → 3 seed, 升级

---

### Exp 3 — Species Definition + RCC Validation

> **目的**: H3 — RCC AUROC ≥ best_non_compat_detector + 0.10
> **对应表**: Table 3 (7 detector)

#### (a) Inputs
- **Source data**: 跑 Exp 1 cell_3 SAET 5 seed × T=100 收集的所有 RCM 矩阵, 累计 ~20 RCC 时点 × 5 seed = 100 RCM snapshot
- Detector 6 baselines:
  - Prompt embedding K-means (用 text-embedding-3-small 编码 system_prompt + planner family)
  - Genome distance clustering (Hamming on MAG categorical fields)
  - Behavior embedding clustering (轨迹 6-dim)
  - Niche profile clustering (4-niche success-rate vector)
  - Lineage tree cut (祖先深度切)
  - RCM modularity (NetworkX greedy modularity)
- **Held-out hybrid set**: 在每个 RCC 时点之后再额外跑 100 个 parent pair 的 hybrid

#### (b) Method
- 训练: 在 gen $t$ 用 detector 预测 cluster → 在 gen $t+1..t+5$ 抽 100 parent pair (其中 30 个被 detector 标 "between-cluster", 30 "within-cluster", 40 random) 跑真实 hybrid, 测 HFL
- 评估: detector 二分类 "low-compat" (HFL > 0.40) → AUROC / AP
- HFL prediction $R^2$: detector cluster label 作为 categorical predictor, linear regress HFL

#### (c) Metrics
Table 3 全部列: Low-Compat AUROC, AP, HFL $R^2$, Calibration Error (ECE), Temporal Stability (Jaccard 跨 5 gen), False Species Rate (FSR = # spurious cluster / # total cluster).

#### (d) Statistical protocol
- 100 RCM snapshot bootstrap CI, B=1000
- RCC vs best baseline AUROC: paired bootstrap (DeLong's test), **Holm 6 comparison**
- 主声明: AUROC(RCC) - AUROC(best baseline) ≥ 0.10, p < 0.05 after Holm

#### (e) Results JSON schema
`experiment_id = "exp_3"`, `detectors: [...]` 7 detector block.

#### (f) Budget & Wallclock
- 额外 hybrid evals: 100 pair × 8 hybrid × 20 RCC 时点 × 5 seed × 4 niche eval = 320K evals
- ⚠️ 大部分 detector 计算无 LLM, 重用 Exp 1 RCM 数据
- Cost: ~$30–50 USD
- Wallclock: 2 天

#### (g) Abort gate
**G3.1**: RCC AUROC - best baseline AUROC < 0.05 → H3 partial fail, 论文重 frame "RCC competitive"
**G3.2**: RCC 的 FSR > 0.5 → RCC 算法 bug, 考虑换 graph community detection

---

### Exp 4 — Causal Mechanism of Hybrid Incompatibility

> **目的**: H4 — `|γ_epi| > |γ_genome_dist|` p < 0.01
> **对应表**: Table 4A + Table 4B

#### (a) Inputs
- **Source data**: Exp 1 cell_3 SAET 的所有 hybrid (~ 5 seed × 100 gen × 32 offspring/gen × 4 niche = 64K hybrid 数据点)
- 干预 interventions (Table 4A 7 行):
  1. Unrepaired cross (default)
  2. Repair Planner-Executor (强制 planner.output_port.type ≡ tools.input_port.type)
  3. Common memory schema
  4. Common tool interface
  5. Common verifier contract
  6. Universal communication
  7. Full semantic repair (全部 cross_module_constraints 强制满足)

#### (b) Method
- 干预 1-7 各跑 200 hybrid (从 inter-species pair 中均匀抽), 测 HFL 变化
- Table 4B: 对 6 个 module pair, 按"是否在该 pair 上 cross"分组测 HFL share, 跑 ANOVA
- 主回归 (§4.5 公式) on all 64K hybrid, MixedLM

#### (c) Metrics
- Table 4A: Hybrid Fitness, HFL, Invalid Actions, Tool Errors, Communication Accuracy
- Table 4B: Epistasis Score, Frequency, Hybrid-Loss Share, Significance
- 主回归输出: γ_epi, γ_gd, γ_niche, γ_behav, γ_iface 各自 estimate + SE + p

#### (d) Statistical protocol
- MixedLM 主回归 (§4.5)
- 7 干预 vs unrepaired paired_t, **Holm 7 comparison**
- 6 module pair ANOVA, Holm 6
- 主声明: γ_epi 系数显著, 且 |γ_epi| > |γ_gd| ratio test (bootstrap CI on ratio not crossing 1)

#### (e) Results JSON schema
`experiment_id = "exp_4"`, `interventions: [...]`, `module_pairs: [...]`, `main_regression: { coefficients: {...}, formula: "..." }`.

#### (f) Budget & Wallclock
- 7 干预 × 200 hybrid × 4 niche eval ≈ 5.6K eval × ~3K avg token = $20–35 USD
- 主回归用 Exp 1 现成数据, $0
- Wallclock: 3 天

#### (g) Abort gate
**G4.1**: |γ_epi| ≤ |γ_gd| → H4 fail. 上报 Director
**G4.2**: γ_epi p > 0.05 → 加跑 hybrid 至 N pair=300
**G4.3**: 干预 → HFL 上升 (违反逻辑) → 干预实现 bug

---

### Exp 5 — Complexity Threshold L_c Scaling Law

> **目的**: H5 — L_c 经验 vs 理论 closed-form 相关 r ≥ 0.5
> **对应表**: Table 5A + Table 5B

#### (a) Inputs
**L-sweep**: $L \in \{4, 6, 8, 10, 12, 16, 20, 24, 32\}$ (9 个点, 比 hypothesis.md 原 4 点加密)
- 每个 L 值: 通过 mutation "add/delete workflow_node" 把 founder L=7 调整到目标 L
  - L < 7: 删 leaf workflow node
  - L > 7: 加 hidden processing node (e.g. critic / reflexion / refiner)
- interaction degree d: 默认 d=3 (founder), 不变
- crossover fraction: 默认 0.5, 不变

每个 L 点: **3 seeds for L != L_c±1**, **5 seeds for L = L_c-1, L_c, L_c+1** (重点采样在 transition 区域)

#### (b) Method
- **预估 L_c 范围**: 用 theorist Thm 4 公式 $L_c = \lceil 0.5 + \sqrt{0.25 + 2\tau_v\bar{F}/(\alpha p_{min}\bar\delta)} \rceil$, 代入 anchor_3 测出的 $\alpha$, $\bar\delta = 0.10$, $\tau_v$ ≈ 0.55, $p_{min} = 0.5$, $\bar{F} \approx 0.5$ → **L_c 估值 8–14 之间** (待 anchor_3 跑出 α 后 finalize)
- 每个 L 点: 跑 SAET N=32 (减半节省成本), T=50 dev gen, 2 niche (PlanBench + WebArena), 5/3 seeds
- 测每个 L 的 HFL_inter (inter-species hybrid)
- 跑 segmented regression on $\log\mathrm{HFL}$ vs $\log L$, 寻找 slope break

#### (c) Metrics
- Table 5A: L, Interface Std?, Species Count, Best Fitness, RII, HFL, Persistence, Critical?
- Table 5B: Predictor (L, d, q, $\bar\delta$, Interface Std), Coefficient, SE, p, Incremental R²

#### (d) Statistical protocol
- Segmented regression on $\log\mathrm{HFL}$ vs $\log L$
- 比较: linear regression vs segmented regression by F-test (slope break 显著性)
- L_c_empirical (segmented break point) vs L_c_theoretical (Thm 4 公式) Pearson r
- 主声明: r ≥ 0.5 with p < 0.05

#### (e) Results JSON schema
`experiment_id = "exp_5"`, `L_sweep: [...]` 9 个 L 点; `L_c_theoretical`, `L_c_empirical`, `pearson_r`, `segmented_regression: {break_point, slope_below, slope_above, F_stat, p}`.

#### (f) Budget & Wallclock
- 9 L × (3 or 5 seeds) × N=32 × T=50 × 2 niche ≈ $40–60 USD
- Wallclock: 9 L 部分并行 (4 worker on SERVER_HOSTNAME), ~3–4 天

#### (g) Abort gate
**G5.1**: 9 L 点 HFL vs L 是纯线性 (F-test p > 0.10) → H5 fail, 论文 H5 改 future work
**G5.2**: r < 0.3 → H5 fail
**G5.3** (cost): 跑 5/9 L 已 > $40 → 暂停后续, 降 T=50 → T=30

---

### Exp 6 — Species Dynamics

> **目的**: G6 — ≥ 1 species pair persistence ≥ 20 generations
> **对应表**: Table 6A + Table 6B

#### (a) Inputs
- **Source**: Exp 1 cell_3 SAET 跑到 T=100, 已经有 20 RCC 时点 → 直接用作 condition 1
- 6 condition (各跑 1 seed × T=100):
  1. Stable Niches (default, 用 Exp 1 数据)
  2. Remove Niche (gen 50 后停 LoCoMo)
  3. Add Niche (gen 50 后加 PlanBench mystery_bw)
  4. Increase Migration (m: 0.10 → 0.40)
  5. Standardize Interfaces (gen 50 后强制 all schema_id 重置)
  6. Lower Resource Budget (token budget × 0.5)

#### (b) Method
- 5 个新 condition (2-6) 各跑 1 seed × T=100, N=32
- 跟踪 lineage_tree, species birth/extinction event
- 计算 introgression rate IR_{A→B}

#### (c) Metrics
- Table 6A: Species Births, Median Lifetime, Extinctions, Fusions, Fissions, Introgression Rate, Final RII
- Table 6B: Cox PH survival regression on extinction time

#### (d) Statistical protocol
- Survival analysis (Cox PH model via `lifelines`)
- 6 condition 间 final RII 用 Kruskal-Wallis (small sample)

#### (e) Results JSON schema
`experiment_id = "exp_6"`, `conditions: [...]`, `survival_model: {coefficients, hazard_ratios}`.

#### (f) Budget & Wallclock
- 5 new condition × 1 seed × N=32 × T=100 × 4 niche ≈ $40–60 USD
- Wallclock: 5 condition 并行 ~ 4–5 天

#### (g) Abort gate
**G6.1**: Stable Niches condition 无任何 species pair ≥ 10 gen → 升级, 怀疑 RCC regression
**G6.2** (cost): 跑 3/6 condition 已 > $80 → 暂停后续

---

### Exp 7 — Cross-benchmark Transfer + Cross-model Reproduction

> **目的**: G7 — ≥ 1 species pair 在 held-out benchmark 上 RII > 0.15
> **对应表**: Table 7A + Table 7B + Part C

#### (a) Inputs
- **Source**: Exp 1 cell_3 SAET final population, 选 top 2 species 的 representative (各 4 agent), 共 8 agent
- Held-out benchmarks (必含 ≥ 1 个 pilot/main 完全没用过的):
  - **SWE-bench Verified** (50 task) — Verified 是 SWE-bench full 手工 curated subset, 与 Lite 0% 重叠
  - **AgentBench DB-bench** (30 task) — 完全没在 pilot/main 出现过 ✅
  - **PlanBench held-out domains** (depots + mystery_bw, 50 task) — 与 main 的 blocksworld/logistics 不重叠
  - **LoCoMo held-out streams** (30 个 main 没用过的 conversation)

#### (b) Method
- 8 agent × 4 held-out benchmark = 32 eval/agent 配置
- inter-species hybrid (R=8 per species pair, 2 species → 1 pair × 8 hybrid) × 4 benchmark eval
- ~~Part B 跨模型~~ **Part B 已删 (Director 决策 Q3, 2026-06-19 13:21 UTC)**: 由于 Anonymous 明确禁止非 Azure gpt-5.4-mini LLM, 跨模型实验无法做; temperature-sweep 不能当 cross-model (审稿人一眼看穿). 论文 Limitations / Future Work 节明示, Part A + C 保留。
- Part C 跨 crossover: typed subgraph vs one-module swap vs workflow-edge crossover vs LLM semantic merge — 4 种各跑 50 hybrid × 1 benchmark = 200 hybrid

#### (c) Metrics
- Table 7A: per benchmark, within-A offspring fit, within-B offspring fit, cross fit, HFL, RII_retained
- ~~Table 7B~~: 删 (Part B 删, Q3)
- Part C: 4 crossover × HFL_mean

#### (d) Statistical protocol
- 单 seed 但 8 agent + 8 hybrid → 跑 paired bootstrap CI B=1000
- 主声明: 至少 1/4 held-out benchmark 上 RII > 0.15

#### (e) Results JSON schema
`experiment_id = "exp_7"`, `benchmarks: [...]`, `crossover_comparison: [...]`. (no `temperature_robustness` — Part B 删)

#### (f) Budget & Wallclock
- 32 agent-benchmark eval × ~20 task avg = 640 evals × ~3K token = $5
- inter-species hybrid: 8 × 4 = 32 hybrid × 4 benchmark eval = 128 eval × $0.01 = $5–10
- Part C: 200 hybrid × 4 benchmark eval = 800 eval = $20
- ~~Part B~~: 删, 省 $3
- **Exp 7 total: $30–45 USD** (Part B 删后), Wallclock 2 天

#### (g) Abort gate
**G7.1**: 全部 4 benchmark RII < 0.10 → G7 fail, 论文 frame "in-distribution only"
**G7.2** (SWE-bench Verified docker fail): 用 3 benchmark, 论文 limitation
**G7.3** (Part C bug): 某 crossover 100% invalid → 跳过

---

## 7. Pilot (M6) — N=16, T=20, K=2

> 此 pilot 不是 Exp 1-7 之一, 是 main exp 启动前的可行性 + 信号探测。

- **配置**: N=16, T=20, K=2 (PlanBench + WebArena per 人类批), R=8, 2 seeds (42, 123)
- **目的**:
  - 验证 SAET 实现可在 24h 内跑完 (anchor_5 hold)
  - 验证 cost ≤ $50 (anchor_5)
  - 验证 founder PlanBench ≥ 60%, WebArena ≥ 20% (anchor_1)
  - 在小规模看 RII signal: 若 gen 15 RII > 0.10 → encouraging, 进 main; 若 RII < 0.05 → 升级
- **abort gate**: 见 ROADMAP.md M6

---

## 8. Cross-Exp 资源 reuse 矩阵 (避免重复跑)

| Source data | Reused by |
|---|---|
| Exp 1 cell_3 SAET 5 seed × T=100 hybrid log + RCM | Exp 2 (SAET 行) + Exp 3 (RCC 训练数据) + Exp 4 (主回归数据) + Exp 6 condition 1 + Exp 7 source population |
| Exp 1 cell_1 single-niche | anchor_4 negative control 复用 |
| anchor_2/3 synthetic landscape | 不进 main exp, 独立 0-cost |
| pilot M6 founder calibration | anchor_1 τ_v 锁定后, main exp 直接读 |

**潜在节省**: 复用让 Exp 2-7 的 cost 估算 ~ 30-50% lower than 独立跑。

---

## 9. 总预算估算 (per Exp)

| Exp | API cost (USD) | Wallclock (天) | 关键风险 |
|---|---:|---:|---|
| anchor_1 (founder calibration, M2) | 15 | 0.5 | gpt-5.4-mini 性能不达 60% |
| anchor_2 (RII/HFL/RCC unit test, M3) | 0 | 0.5 | typed crossover 实现 bug |
| anchor_3 (M-family DMI, M4) | 0 | 0.5 | $\alpha$ 估计漂移 |
| anchor_4 (single niche control, M5) | 25 | 1 | 实测 RII > 0.10 (定理 3 fail) |
| anchor_5 (pilot cost gate, M6) | 50 | 1 | API rate limit |
| **Pilot (M6 N=16, T=20)** | **(included in anchor_5)** | (above) | RII no signal |
| Exp 1 (multi-niche main, M7) | 130–180 | 4–5 | WebArena docker 不稳定 |
| Exp 2 (baseline comparison) | 80–120 (新跑 5 baseline) | 5–7 | G2 反证失败 |
| Exp 3 (RCC validation) | 30–50 | 2 | detector AUROC 不达标 |
| Exp 4 (causal regression) | 20–35 | 3 | $|\gamma_{epi}|$ 不显著 |
| Exp 5 (L_c scaling) | 40–60 | 3–4 | slope break 不可观测 |
| Exp 6 (species dynamics) | 40–60 | 4–5 | extinction rate 过高 |
| Exp 7 (transfer) | 30–50 | 2–3 | SWE-bench Verified docker fail |
| **Subtotal** | **460–645** | **24–32** | |
| Revision buffer (after submit) | 50–100 | 2–3 | reviewer 要求补 ablation |

**🚨 预算 trade-off (460–645 vs 500 USD 上限)**:

- **场景 A (顺利, 460 USD)**: 所有 lower-bound 估算成立, 无重跑, 留 40 USD revision buffer → **可行**
- **场景 B (中等, 550 USD)**: 略超 50 USD → 砍 Exp 2 中 PBT-style 和 Pop-LLM-Evo (合并 1 个跑, 节省 30 USD), 砍 Exp 6 lower budget condition (合并到 default, 节省 10 USD) → 拉回 510 USD
- **场景 C (糟糕, 645 USD)**: 超 145 USD → 升级 Director, **三个削减方案**:
  - 削减 Exp 1 cell_4 (alternating niche) + cell_5 (high migration) → 节省 50 USD, 但 Exp 1 cell 数从 5 → 3
  - 削减 Exp 5 L-sweep 从 9 → 6 个 L 点 → 节省 25 USD, 但 L_c 估计 CI 变宽
  - 降 Exp 1 5 seed → 3 seed → 节省 70 USD, 但 H1 voting 阈值"3/5"自动变"2/3" (statistical power 略降)

⚠️ **Director 需拍板**: 是否同意场景 C 的削减次序? **建议次序**: 先砍 cell_4/cell_5, 然后 L-sweep 加密度, 最后才动 seed 数。

---

## 10. Abort Gate Matrix (汇总, RUNNING 阶段 ml_engineer 必查)

| Gate ID | 触发条件 | 处置 |
|---|---|---|
| **GA.M1** | SERVER_HOSTNAME /data1 free < 200GB | 暂停, 通知 Anonymous 清理 |
| **GA.M1** | docker daemon data-root 不在 /data1 | 卡 M1, 不进 M2 |
| **GA.M1** | SWE-bench Lite docker pull 失败 (3 次 retry) | 触发 EXP-DESIGN-4 plan B: 跳过 code niche, 论文降 3-niche |
| **GA.M2** | founder PlanBench < 60% on 50 task | 上报 Director, 不进 M3, 调整 founder design (见 founder_genome_v0.md §4.3) |
| **GA.M2** | founder self-cross viability < 0.70 | 上报 Director, 怀疑 typed crossover 破坏 founder, 修复或调 τ_v |
| **GA.M2** | Azure API 单 day spend > $30 (pilot 阶段) | 暂停, 升级 Director |
| **GA.M3** | RII/HFL 解析值偏离 > 10% | 上报 Director, 不进 M4 |
| **GA.M3** | RCC ARI < 0.80 on 2-species toy | 升级 Director, 考虑换 spectral → graph community detection |
| **GA.M4** | $\alpha$ 与 Orr 理论数量级偏差 > 10x | 上报 Director, 怀疑 mutation kernel 对称性破坏 |
| **GA.M4** | M-family slope 偏离 0.05 > 30% | 上报 Director, 修复 $p_{mix}$ 实现 |
| **GA.M5** | single-niche RII > 0.10 持续 50 gen | **🚨 严重**: 定理 3 fail, 整个项目 ABORT, 上报 Director |
| **GA.M6 / G1.1** | pilot gen 15 cell_3 RII < 0.10 | 升级 Director, 不进 main |
| **GA.M6 / anchor_5** | pilot cost > $50 OR wallclock > 24h | 升级 Director, 估算 main 成本 |
| **G1.2** | Exp 1 cell_3 单 seed gen 30 cost > $40 | 暂停, task 抽样 /2, 升级 |
| **G1.3** | Exp 1 cell_1 RII > 0.10 在 main 阶段 | 整个 Exp 1 暂停, 升级 (与 GA.M5 同症) |
| **G1.4** | Exp 1 main 4-niche, < 2/5 seeds stable species | 上报, H1 partial, 但 Exp 2-7 继续 |
| **G1.5** | **3-niche fallback 下 4-niche main run 仍 < 2/5 stable species** | **上报 Director, 候选 ABORT (不靠降门槛掩盖). 理由: Prop 1 + Thm 4 在 K=3 仍预测 ≥2 species; K=3 跑不出 ≥2 = EST niche separation 假设在 LLM agent 设定下不成立, 这是有意义的 negative result, 不该靠降阈值掩盖. 论文路径走 negative result 投稿 (or ABORT)** |
| **G2.1** | Exp 2 中 MAP-Elites / Novelty RII ≥ 0.20 | 上报, G2 fail, H2 重 frame |
| **G2.2** | Exp 2 累计 > $200 USD | 暂停, 5 seed → 3 seed |
| **G3.1** | RCC AUROC - best baseline < 0.05 | 上报, H3 partial |
| **G3.2** | RCC FSR > 0.5 | 上报, 换 community detection |
| **G4.1** | $|\gamma_{epi}| \leq |\gamma_{gd}|$ | 上报, H4 fail, 论文重 frame |
| **G4.2** | $\gamma_{epi}$ p > 0.05 | 上报, 加跑 hybrid |
| **G4.3** | 干预 → HFL 上升 | 干预实现 bug, 修复 |
| **G5.1** | 9 L 点纯线性 (F-test p > 0.10) | 上报, H5 fail, 论文降 future work |
| **G5.2** | r < 0.3 | 上报, H5 fail |
| **G5.3** | Exp 5 跑 5/9 L 已 > $40 | 暂停后续, 降 T=50 → T=30 |
| **G6.1** | Stable Niches condition 无 species 持续 ≥ 10 gen | 升级, 怀疑 RCC regression |
| **G6.2** | Exp 6 跑 3/6 condition 已 > $80 | 暂停 |
| **G7.1** | 全部 held-out benchmark RII < 0.10 | 上报, G7 fail, 论文 frame "in-distribution only" |
| **G7.2** | SWE-bench Verified docker 不可用 | 替代为 3 个 benchmark, 论文 limitation |
| **G7.3** | Exp 7 Part C 某 crossover 100% invalid | 跳过该 crossover |
| **GA.global** | 累计 API cost > $400 USD | 暂停所有 active job, 升级 Director |
| **GA.global** | 累计 API cost > $450 USD | 强制停所有 job, 必须升级 |
| **GA.global** | SERVER_HOSTNAME SSH 断 > 30 min | 联系 Anonymous, 不重启 |

---

## 11. 需要 Director 拍板的关键决策点

1. **预算 trade-off 次序** (§9 场景 C): 削减 Exp 1 cell_4/5 → Exp 5 L 点 → seed 数. 是否接受? 若不接受, 给替代次序。
2. **SWE-bench Lite docker plan B** (§EXP-DESIGN-4 / ROADMAP M1): Anonymous docker root sudo 截止 M5 前完成是 critical path. 若未完成, plan B = 跳过 code niche, 论文写 3-niche. 但: 4-niche 减为 3-niche 后, H1 的 "≥3/5 seeds stable species" 门槛是否仍 hold? **我的判断: 仍 hold** — 3-niche (planning + web + memory) 已足够产生 niche heterogeneity, EST 理论上 K≥2 即可触发 isolation; G1 通过门槛可调整为 "≥1 stable species pair" 而不是 "≥2 stable species", 论文核心论点不受影响。
3. **Exp 7 Part B 跨模型** (人类禁用其他 LLM): 我把它降级为 temperature-sweep, 是否同意? 还是该 Part 整个删, 论文中明确说 cross-model 留 future work?
4. **Pilot 阶段 single-niche control** (anchor_4): 应在 M5 单独跑, 还是合并到 pilot M6 同时跑? **我建议 M5 单独跑 30 USD**, 因为 anchor_4 fail = 整个项目 ABORT, 必须先确认, 不能与 pilot 信号探测混淆。
5. **Exp 5 加密 L-sweep** (4 → 9 个 L 点): 是否同意? 加密成本 +25 USD, 但 slope break detection 显著提升。若拒绝, 用原 {4,8,16,32} 4 个 L 点, $-20$ USD。
6. **L_c 理论值需 anchor_3 跑完才能定** (estimate range 8–14): 推迟到 M4 结束后再 finalize Exp 5 的 5-seed 集中区域. 是否同意 M4 完成前不锁 Exp 5 design 细节?

---

## 12. RUNNING 阶段交付物清单

```
experiments/
├── EXP_DESIGN.md             (本文档, frozen)
├── ROADMAP.md                (配套 milestone doc)
├── synthetic/                (anchor_2/3, M3+M4 产出)
│   ├── landscape_2species.py
│   ├── landscape_M_family.py
│   ├── test_assertions.py
│   ├── report_synthetic.json
├── core/                     (SAET + MAG + RCM + RCC 实现, M1-M6 完成)
│   ├── mag.py                (Modular Agent Genome 类)
│   ├── crossover.py          (typed subgraph crossover)
│   ├── mutation.py           (8 类 mutation operator)
│   ├── saet.py               (evolutionary loop)
│   ├── rcm.py                (RCM estimation + active sampling)
│   ├── rcc.py                (RCC clustering)
│   ├── compat_predictor.py   (active-learning predictor)
│   ├── metrics.py            (RII/HFL/persistence)
│   ├── stats.py              (bootstrap CI / paired_t / Holm / MixedLM)
│   ├── llm_client.py         (Azure gpt-5.4-mini wrapper + retry + rate limit)
├── niches/                   (4 niche evaluator, M1 完成)
│   ├── planbench.py
│   ├── webarena.py
│   ├── swebench_lite.py
│   └── locomo.py
├── baselines/                (9 baseline 实现, M7 前完成)
│   ├── static_founder.py
│   ├── random_drift.py
│   ├── greedy_archive.py
│   ├── tournament.py
│   ├── pbt_style.py
│   ├── novelty_search.py
│   ├── map_elites.py
│   ├── dgm_archive.py
│   └── pop_llm_evo.py
├── exp_1/ exp_2/ ... exp_7/  (每个 Exp 的 config + results.json)
│   └── config.yaml + results.json + logs/
├── EXPERIMENT_LOG.md         (人类可读, 每跑完一批立刻更新)
├── calibration.json          (anchor_1 τ_v 校准结果)
└── budget_tracker.json       (累计 cost 实时跟踪, GA.global 触发依据)
```

---

**EXP_DESIGN.md 锁定**. 任何后续偏离 (新加 Exp / 改 metric / 改回归公式 / 改 abort gate 阈值) 必须 Director 显式批准后 update 文档 + bump version。

— anonymous artifact authors, 2026-06-19 JST
