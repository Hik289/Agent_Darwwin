# ROADMAP.md — agentspecies day-shaped milestone plan

> **作者**: ml_engineer_claude (Anonymous Lab)
> **配套**: `EXP_DESIGN.md` (frozen 实验执行计划, 本文档是其时间线视图)
> **日期**: 2026-06-19 JST
> **总时长**: ~15–20 天 (M1 → M13)
> **机器**: SERVER_HOSTNAME, 存储 `./`
> **预算**: 500 USD (per checklist 1.12)

⚠️ 这里 milestone 用 **M-编号**, 不绑定具体日期; "Day-X" 仅给参考节奏 (M1 = 启动日; Day 数为相对天). 实际跑 RUNNING 阶段时 Director 派单决定 milestone 启动顺序。

---

## 全局图 (DAG)

```
M1 (Day 0-1, infra warmup, parallel-A: code+SWE docker; parallel-B: PlanBench+WebArena+LoCoMo)
       │
       ├── M2 (Day 2, anchor_1 founder calibration on PlanBench+WebArena)
       │       │
       │       ├── M3 (Day 3, anchor_2 RII/HFL/RCC unit test on synthetic, 不依赖 LLM)
       │       │      │
       │       │      └── M4 (Day 4, anchor_3 M-family DMI on synthetic; 输出 α 估计)
       │       │              │
       │       │              └── (α + τ_v 喂给 Exp 5 finalize L-sweep design)
       │       │
       │       └── M5 (Day 5, anchor_4 single-niche negative control, 必须 PASS 才进 main)
       │              │
       │              └── M6 (Day 6, Pilot N=16 T=20, 2 seeds, 2 niche, 信号探测)
       │                     │
       │                     └── (anchor_5 cost gate; pilot RII signal OK → 解锁 M7)
       │
       └── M7+ (Day 7-19, main exp 1-7 顺序/并行, 见 §M7-M13)

      ── (Day 19) → ANALYSIS phase 启动, ml_engineer 移交 results.json 给 data_scientist
```

**关键依赖链**: M5 PASS 是 main 阶段开门; M3+M4 PASS 是 Exp 5 L_c 估计可信前提; M2 PASS 是 anchor_1 信号收集起点。

---

## M1 — Infrastructure Warmup (Day 0-1)

**目的**: 让 SERVER_HOSTNAME 从空盘到能跑 LLM API 一键 smoke test, 让 Docker 准备好等 SWE-bench Lite 数据。

### 输入依赖
- SERVER_HOSTNAME SSH 可达 (已验证 2026-06-19)
- /data1 有 9.4T (已验证, > 200GB 安全余量)
- Azure gpt-5.4-mini key 在 checklist.md §1.10 (已 Director 提供)
- Python 3.10.12 已装 (已验证)

### Tasks (并行 2 stream)

**Stream A (Docker / SWE-bench)** — 等 Anonymous docker /data1 sudo 完成 (Director 已上报 Anonymous, 等待回复)
- [ ] **A1** Anonymous (人) 完成 `/etc/docker/daemon.json` `data-root` 改 `/data1/docker` + `systemctl restart docker` (估 30 min, 一次性). **A1 完成前 A2-A4 全 hold**, 我先专注 Stream B
- [ ] **A2** 验证: `ssh SERVER_HOSTNAME "docker info | grep 'Docker Root Dir'"` 显示 `/data1/docker`
- [ ] **A3** Background: 启动 SWE-bench Lite docker image pull (`docker pull` 300 instance, 估 1–3h). 用 tmux session 后台跑, 不阻塞其他 M.
- [ ] **A4** SWE-bench Lite repo install (`pip install swebench`), smoke test 1 instance harness 跑通
- ⚠️ **Stream A 触发 fallback**: 若 M5 前 Anonymous 仍未做 → 直接走 3-niche fallback (Director Q2 决策). H1 阈值不降 (G1.5 abort gate)

**Stream B (其余 niche + LLM client)** — 与 A 并行
- [ ] **B1** `ssh SERVER_HOSTNAME "conda create -n agent_py311 python=3.11 -y"` (用 11, 比系统 10 新, 兼容 LoCoMo + latest swebench)
- [ ] **B2** 安装 base deps: `openai>=1.40, scipy, scikit-learn, networkx, statsmodels, lifelines, datasets, playwright`
- [ ] **B3** Azure gpt-5.4-mini client wrapper (`core/llm_client.py`):
  - retry on rate limit (exponential backoff, max 5 retry)
  - token usage tracker (写 `budget_tracker.json`)
  - smoke test: 5 calls, latency < 5s avg, no auth error
- [ ] **B4** PlanBench install: clone + Fast Downward build (~5-8 min) + VAL build + smoke test blocksworld 1 instance with founder genome
- [ ] **B5** WebArena: clone + `pip install -r requirements.txt` + playwright install chromium + pull 5 站点 docker (~10–15 min)
  - smoke test: shopping 站点 1 task
- [ ] **B6** LoCoMo: `datasets.load_dataset("snap-research/locomo")`, smoke test 1 conversation × 1 question
- [ ] **B7** 创建项目目录:
  ```
  ./
    benchmarks/{planbench, webarena, swebench_lite, locomo}
    archive/
    results/
    logs/
  ```
- [ ] **B8** MAG schema validator (`core/mag.py`): `schema_validate / type_check / minimal_execution_test` 三关 (per founder_genome_v0.md §5)
- [ ] **B9** typed_subgraph_crossover skeleton (`core/crossover.py`): 无 LLM, 仅 graph ops, 测 founder × founder = founder (sanity)

### Outputs
- `./` 目录创建完整
- `/data1/docker` 包含 SWE-bench docker images (≥ 80GB pulled)
- `core/llm_client.py` 通过 smoke test, 写入 `experiments/budget_tracker.json` 初始 = 0 USD
- 4 niche evaluator (`niches/{planbench, webarena, swebench_lite, locomo}.py`) 各跑通 1 task
- MAG schema validator 通过 founder genome v0

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| GA.M1.1 | /data1 free < 200GB | 暂停, 通知 Anonymous 清 |
| GA.M1.2 | docker daemon data-root 不在 /data1 | 卡 M1, 阻断 M7 (但 M2-M6 可继续, 因为 pilot 不用 SWE-bench Lite) |
| GA.M1.3 | SWE-bench Lite docker pull 3 次 fail | 触发 **EXP-DESIGN-4 plan B**: 跳 code niche, 论文写 3-niche |
| GA.M1.4 | Azure API smoke test 失败 (auth / quota) | 暂停, 通知 Anonymous 检查 key |
| GA.M1.5 | WebArena docker 5 站点任一启动失败 | 重试 3 次, 失败则上报 (pilot 仍可用 PlanBench) |

### 预算
- API cost: < $0.5 (smoke test only)
- Wallclock: 1.5 天 (A3 拉 docker 1-3h 是 long tail, B series 8-10h, 并行)

### Plan B for SWE-bench docker 不可用
**判定时机**: M1 结束 + 24h watchdog. 若到 M5 启动前仍未 unblock:
- **plan B-1**: 单刀降级为 3-niche (planning + web + memory). 修改 `experiments/exp_*/config.yaml` 的 `niches` 字段 = `["planning", "web", "memory"]`
- **影响**:
  - H1 "≥3/5 seeds stable species in 4-niche" → 改 "in 3-niche" (论文文本调整)
  - **G1 是否仍可通过?** 我的判断: **是, 仍可通过**. 理由:
    - EST 理论 (定理 4) 只要求 K≥2 niche heterogeneity 即可触发 isolation, 3 vs 4 不改变 mechanism
    - 3 niche 仍覆盖 planner / memory / tool 三大模块 specialization 方向
    - 文献先例 (Anderson & Harmon 2013 Avida 实验) 也是 3 niche 起步
    - 风险: 3 niche specialization 路径少, 可能 species count 偏低 (Exp 1 期望 2 species, 若降到 ≥1 species 仍可 frame "speciation 出现", 但 G1 voting 阈值需 Director 调整)
  - Exp 5 L-sweep 不受影响 (synthetic / 2-niche 跑)
  - Exp 7 held-out 不受影响 (用 SWE-bench Verified 改用 AgentBench DB-bench 替代, 仍 3 held-out benchmark)
- **alternative plan B-2**: 延迟 M7 等 docker 就位 (但 main exp 起步可能拖到 Day 8+, 总时长压力)
- **决策**: 由 Director 在 M5 启动前拍板; 我倾向 plan B-1 (3-niche 论文)

---

## M2 — Anchor_1 Founder Calibration (Day 2)

**目的**: 用 founder genome v0 在 PlanBench + WebArena 上跑 sanity, 校准 τ_v, 验证 anchor_1 通过。

### 输入依赖
- M1 全部 PASS
- founder_genome_v0.json 可被 MAG 类读取

### Tasks
- [ ] **M2.1** founder PlanBench 50 task (blocksworld+logistics 各 25), 5 次重复 (估计 std)
- [ ] **M2.2** founder WebArena 10 task pilot subset (per niche_profiles §3.4)
- [ ] **M2.3** founder self-cross calibration: 16 founder clone × pair × R=8 hybrid × PlanBench 50 task = ~6400 evals
  - per data_scientist niche_profiles.md §6.1 protocol
- [ ] **M2.4** 锁定 τ_v: 扫 {0.3, 0.4, 0.5, 0.6, 0.7}, 选 self-cross binary viability ≥ 70% 的最大 τ_v
- [ ] **M2.5** 写 `experiments/calibration.json`: τ_v + founder_fitness + std

### Outputs
- `experiments/calibration.json`
- `EXPERIMENT_LOG.md` [EXP-001] founder calibration 条目

### 完成判据 (assertion)
- founder PlanBench success ≥ **0.60** (mean of 5 reps)
- founder PlanBench single-run std ≤ **0.06**
- founder WebArena success ≥ **0.20**
- founder self-cross binary viability ≥ **0.70** at some τ_v ∈ [0.30, 0.70]
- 锁定 τ_v 写入 calibration.json

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| GA.M2.1 | founder PlanBench < 60% | 上报 Director, 调整 founder (per founder_genome_v0.md §4.3 回退: verifier.samples 3→5, decomposition_style iterative_deepening, 加 1-shot example), 不进 M3 |
| GA.M2.2 | founder std > 10% | 上报, 加 task 数 50→100 或降 temperature 到 0 |
| GA.M2.3 | self-cross viability < 70% 在任意 τ_v | 上报, 怀疑 typed_subgraph_crossover 实现破坏 founder 结构 |
| GA.M2.4 | API cost > $30 in 24h | 暂停, 升级 |

### 预算
- API cost: ~$10–20 (4400 + 200 + 6400 evals × ~$0.001)
- Wallclock: 8–12h (PlanBench + WebArena 并行)

### 风险 & Plan B
- 风险 1: gpt-5.4-mini 在 PlanBench 上低于 60% → 触发 founder_genome_v0.md §4.3 回退
- 风险 2: WebArena docker 启动失败 → 只跑 PlanBench, anchor_1 部分通过 (WebArena 移到 M6 pilot 时重试)
- 风险 3: self-cross viability 怎么调都低 → 上报 Director, 怀疑 crossover 算法本身, 不是 founder 问题

---

## M3 — Anchor_2 Synthetic RII/HFL/RCC Unit Test (Day 3)

**目的**: 用 0 LLM cost 的 synthetic landscape (per data_scientist synthetic_landscape_spec.md §1) 验证 RII / HFL / RCC 实现正确。

### 输入依赖
- M1 完成 (`core/metrics.py`, `core/rcm.py`, `core/rcc.py` 可 import)
- 不依赖 M2 (无 LLM)

### Tasks
- [ ] **M3.1** 实现 `experiments/synthetic/landscape_2species.py` (per synthetic_landscape_spec.md §1)
- [ ] **M3.2** 实现 `experiments/synthetic/landscape_M_family.py` (留给 M4 用)
- [ ] **M3.3** 实现 `experiments/synthetic/test_assertions.py` (6 case)
- [ ] **M3.4** 跑 6 case, MC N=500 hybrid, 输出 `report_synthetic.json`
- [ ] **M3.5** 把 RCC 部分 (Case 6) 单独验证: 12 agent (6A + 6B) 跑 ARI

### Outputs
- `experiments/synthetic/report_synthetic.json` 含 6 case 全部数字
- `passed_anchor_2: true`

### 完成判据
- Case 1 (identical): HFL_AB ∈ [-0.05, +0.05], RII_AB ∈ [-0.05, +0.05]
- Case 2 (noise locus diff): HFL_AB ∈ [-0.05, +0.05]
- Case 3 (2-species): HFL_AB ∈ [0.628, 0.694] (即 0.661 ± 5%); RII_AB ∈ [0.628, 0.694]
- Case 4 (within-lineage): K_AA ≥ 0.95, RII_within ≤ 0.05
- Case 5 (M=1): |L_AB - 0.05| / 0.05 < 0.15
- Case 6 (RCC): clusters_found == 2, ARI ≥ 0.90

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| GA.M3.1 | Case 3 HFL/RII 偏离 > 10% | 上报 data_scientist 复核, 不进 M4. 通常是 $p_{mix}$ 实现 bug (per synthetic_landscape_spec.md §5) |
| GA.M3.2 | Case 6 RCC ARI < 0.80 | 上报 Director, 考虑换 spectral → graph community detection (NetworkX greedy_modularity) |
| GA.M3.3 | 任一 case fail | 不 silent fix, 写 trace 上报 |

### 预算
- API cost: **$0**
- Wallclock: 4–8h (单机 numpy, MC N=500)

---

## M4 — Anchor_3 M-Family DMI Verification (Day 4)

**目的**: 验证 EST 定理 1 线性律, 估出 α (DMI scaling constant), 让 Exp 5 finalize L_c 估值。

### 输入依赖
- M3 PASS (复用 synthetic landscape impl)

### Tasks
- [ ] **M4.1** 跑 M ∈ {2, 4, 8, 16, 32}, 每 M 跑 MC N=200 hybrid
- [ ] **M4.2** 线性回归 $\hat{\mathcal{L}}_{AB}$ vs M
- [ ] **M4.3** 估算 α: 对 founder-derived M, 用 $\alpha = 2 \hat{M}(L) / (L(L-1))$ 估计 (per Lemma 6); 给 L_sweep ∈ {3, 5, 7, 9} 加 4 个 LLM 配对算 M 实测值 (可选, 仅做粗估)
- [ ] **M4.4** 计算 L_c_theoretical 范围: 用 $\tau_v$ (来自 M2), $\bar\delta=0.10$ (synthetic), $p_{min}=0.5$, $\bar{F}=0.5$, $\alpha=$ 估值 → 得 L_c estimate
- [ ] **M4.5** 更新 EXP_DESIGN.md Exp 5 §6 的 L_c 估值 (locked-in)

### Outputs
- 更新 `experiments/synthetic/report_synthetic.json`: M_sweep + regression + α + L_c_theoretical
- 🆕 `experiments/synthetic/alpha_estimate.json` (per Director 要求 Q6): `{alpha_mean, alpha_ci_lo, alpha_ci_hi, n_bootstrap, L_c_theoretical: <closed form computed>, L_c_central_range: [L_c-2, L_c+2]}`
- M4 完成后**主动 sessions_send 给 Director** 报 α + L_c 候选区间, 等 Director 回 Exp 5 重点采样区域后再启动 M11
- `passed_anchor_3: true`

### 完成判据
- 线性回归 slope $a \in [0.0425, 0.0575]$ (即 0.05 ± 15%)
- intercept $|b| < 0.05$
- $R^2 > 0.95$
- 每个 M 残差 < 15%
- α 估值 ∈ [0.05, 0.5] (Orr 经典范围)
- L_c_theoretical 落在 [6, 18] (rough sanity)

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| GA.M4.1 | slope 偏离 0.05 > 30% | 上报, 修复 $p_{mix}$ |
| GA.M4.2 | α 估值 > 1.0 或 < 0.01 | 上报 theorist + data_scientist, 怀疑 mutation kernel 对称性破坏 (Assumption 5 fail) → 影响 Thm 4 适用性 |
| GA.M4.3 | $R^2 < 0.85$ | 加 MC samples N=200 → 500, 重跑 |

### 预算
- API cost: **$0** (synthetic only) + 可选 $5 if 加 4 LLM-based L 点
- Wallclock: 4–6h

---

## M5 — Anchor_4 Single-Niche Negative Control (Day 5)

**目的**: 验证 EST 定理 3 (single-niche → RII → 0). 这是**整个项目最关键的 negative control**, 失败 = ABORT.

### 输入依赖
- M2 PASS (founder + τ_v + Azure client ready)
- M3 PASS (RII metric impl correct)

### Tasks
- [ ] **M5.1** 跑 SAET on PlanBench only, K=1 niche, **关闭 module epistasis** (即把 typed crossover 退化为 weight-merge per Thm 3 Assumption 6), **固定 communication schema** (不允许 mutation 改), **关 assortative mating** (β=0)
- [ ] **M5.2** N=32, T=50, 3 seeds (42, 123, 456), R=8
- [ ] **M5.3** 每 5 gen 测 RII, 跟踪 50 gen 全程
- [ ] **M5.4** 主声明: RII < 0.10 持续 50 gen × 3 seeds

### Outputs
- `experiments/anchor_4/results.json`
- RII vs t 时序图 (matplotlib 简单 plot)

### 完成判据
- 3 seeds 全部 RII 始终 < 0.10 (没有任何 gen > 0.10)
- 50 gen 内不出现 ≥ 2 个 RCC valid cluster

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| **GA.M5.CRITICAL** | **任一 seed RII > 0.10 持续 ≥ 3 个 RCC 时点** | **🚨 整个项目 ABORT**, 上报 Director: 定理 3 fail, H0 不可信, single-niche 也能形成 species 说明 species detection 是 artifact (可能 RCC 算法 over-cluster, 或 founder 多 clone 不够 homogeneous) |
| GA.M5.2 | 单次 RII spike > 0.10 但 < 3 时点 | 上报 Director, 不立刻 ABORT, 但需 Director 判断是 noise 还是 systematic |
| GA.M5.3 | API cost > $40 | 暂停, 升级 (anchor_4 预算 $30, 超 33%) |

### 预算
- API cost: ~$25 (32 × 50 × 30 task × 3 seed + RCM evals ≈ 150K evals × $0.0002)
- Wallclock: 24–36h (单 niche 简单, SERVER_HOSTNAME 并行 3 seed)

---

## M6 — Pilot N=16 T=20 (Day 6)

**目的**: 在 main exp 启动前, 用小规模快速探测 RII signal + 验证 anchor_5 cost / wallclock 上限。

### 输入依赖
- M2 + M3 + M4 + M5 全 PASS (单 niche 不形成 species 验证)
- M1 SWE-bench docker 可选 (pilot 跳过 SWE-bench Lite)

### Tasks
- [ ] **M6.1** SAET pilot, N=16, T=20, 2 seeds (42, 123), R=8, 2 niche (PlanBench + WebArena per 人类批)
- [ ] **M6.2** 每 5 gen 测 RII, 跟踪 species count
- [ ] **M6.3** budget_tracker.json 实时跟踪, hit $50 强停
- [ ] **M6.4** 比对 anchor_5 验收: cost ≤ $50, wallclock ≤ 24h
- [ ] **M6.5** 报告 pilot 信号给 Director: gen 15 RII 值 + 是否进 main

### Outputs
- `experiments/pilot/results.json`
- pilot signal report (双段格式, per SOUL.md)

### 完成判据
- anchor_5: cost ≤ $50, wallclock ≤ 24h
- **soft criterion (信号探测)**:
  - gen 15 RII > 0.10 → encouraging, 推荐 Director 进 M7 main
  - gen 15 RII ∈ [0.05, 0.10] → 边缘, 上报 Director 决定
  - gen 15 RII < 0.05 → 弱信号, 不推荐进 main, 上报检查 implementation

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| GA.M6.1 (anchor_5) | pilot cost > $50 | 强停, 升级 Director, 估算 main 是否超 500 USD |
| GA.M6.2 (anchor_5) | wallclock > 24h | 升级, 评估 SERVER_HOSTNAME 是否资源不足或代码 inefficient |
| GA.M6.3 | gen 15 RII < 0.05 (no signal) | 上报 Director, 不进 M7, 重审 implementation |
| GA.M6.4 | API rate limit 频繁触发 (> 10% calls retry) | 上报 Anonymous 查 Azure quota |

### 预算
- API cost: $30–50 (上限 50, anchor_5)
- Wallclock: 18–24h (上限 24, anchor_5)

---

## M7 — Exp 1 Multi-niche Speciation (Day 7-11)

**目的**: Exp 1 main 跑, 收集 H1 主证据.

### 输入依赖
- M6 PASS (pilot signal OK, Director 批准进 main)
- M1 SWE-bench docker ready (or plan B-1 3-niche)

### Tasks
- [ ] **M7.1** Exp 1 cell_1 (1-niche control), N=64, T=100, 5 seeds — 复用 anchor_4 部分数据
- [ ] **M7.2** Exp 1 cell_3 (4-niche main), N=64, T=100, 5 seeds — 🌟 main payload
- [ ] **M7.3** Exp 1 cell_2 (2-niche), cell_4 (alternating), cell_5 (high migration), N=32 each, T=50 — 简化辅助
- [ ] **M7.4** 5 seed 并行 (SERVER_HOSTNAME 4 niche worker pool, 估各 niche 1 worker)
- [ ] **M7.5** 实时跟 budget_tracker.json: gen 30 / gen 60 / gen 100 checkpoint cost
- [ ] **M7.6** 每 gen 写 partial results.json (避免实验崩溃丢数据)

### Outputs
- `experiments/exp_1/results.json` (5 cell × per-seed metrics)
- 每 seed RCM snapshot (每 5 gen 一个 .npz, 留 Exp 3 复用)

### 完成判据
- cell_3 4-niche: 3/5 seeds 出现 ≥ 2 stable species (RII > 0.25, K_w-K_b > 0.20, persistence ≥ 10)
- cell_1 1-niche: RII < 0.10 (confirms anchor_4)

### Abort Gate
| Gate | 触发 | 处置 |
|---|---|---|
| G1.1 | pilot signal had been < 0.10 (已在 M6 catch) | 不应到达 M7 |
| G1.2 | cell_3 单 seed gen 30 cost > $40 | 暂停, task 抽 30 → 15, 升级 |
| G1.3 | cell_1 RII > 0.10 (与 anchor_4 矛盾) | 整个 Exp 1 暂停, 同 GA.M5.CRITICAL |
| G1.4 | gen 100, < 2/5 seeds stable | 上报 H1 partial, 但 Exp 2-7 继续 |
| GA.global | 累计 cost > $400 | 暂停, 留 100 USD buffer for revision |

### 预算
- API cost: $130–180
- Wallclock: 4–5 天

---

## M8 — Exp 2 Baseline Comparison (Day 10-15, 与 M7 部分 overlap)

**目的**: 跑 8 baseline (SAET 已有 from Exp 1), 验证 G2 反证.

### Input
- Exp 1 cell_3 SAET results 可用 (M7 完成或部分完成)
- 已有 baseline (Static / MAP-Elites / Tournament / Greedy from Exp 1 中 cells) reuse

### Tasks
- [ ] **M8.1** 新跑 5 baseline: Random Drift / PBT-style / Novelty Search / DGM-style / Pop-LLM-Evo
- [ ] **M8.2** 每 baseline 5 seeds × cell_3 配置 (4-niche, N=64, T=100, R=16)
- [ ] **M8.3** 计算 diversity-matched RII (MAP-Elites / Novelty 与 SAET 相同 behavior_div 切片)
- [ ] **M8.4** Holm 9 baseline vs SAET paired_t

### Output
- `experiments/exp_2/results.json` (10 method × cell_3 metrics + diversity-matched analysis)

### 完成判据
- MAP-Elites + Novelty Search behavior_div ≥ SAET, 但 RII < 0.15 → G2 confirm
- Holm 校正后 SAET vs 各 baseline RII 差异显著 p < 0.05

### Abort Gate
- G2.1: MAP-Elites/Novelty RII ≥ 0.20 → G2 fail
- G2.2: 累计 > $200 → 5 seed → 3 seed

### 预算
- API cost: $80–120
- Wallclock: 5–7 天 (与 M7 cell_3 重叠 ~2 天)

---

## M9 — Exp 3 RCC Validation (Day 13-15)

**目的**: H3 — RCC AUROC vs 6 baseline.

### Input
- Exp 1 cell_3 SAET 跑出来的 100 RCM snapshot
- 100 额外 hybrid pair × 8 hybrid 每个 RCC 时点 (后采样, reuse Exp 1 pipeline)

### Tasks
- [ ] **M9.1** 实现 6 detector: prompt_embed_kmeans, genome_dist_cluster, behavior_embed_cluster, niche_profile_cluster, lineage_tree_cut, rcm_modularity
- [ ] **M9.2** 每 RCC 时点抽 100 future hybrid 跑真实 HFL
- [ ] **M9.3** 6 detector + RCC 算 AUROC / AP / R² / Calibration ECE / Stability / FSR
- [ ] **M9.4** Holm 6 detector vs RCC

### Output
- `experiments/exp_3/results.json`

### 完成判据
- AUROC(RCC) - AUROC(best baseline) ≥ 0.10, p < 0.05 after Holm

### Abort Gate
- G3.1: 差距 < 0.05 → H3 partial
- G3.2: FSR > 0.5 → 换 community detection

### 预算
- API cost: $30–50 (主要新 hybrid)
- Wallclock: 2 天

---

## M10 — Exp 4 Causal Mechanism (Day 14-16, 与 M9 部分并行)

**目的**: H4 — `|γ_epi| > |γ_genome_dist|` p < 0.01.

### Input
- Exp 1 cell_3 SAET 的 ~64K hybrid 历史数据

### Tasks
- [ ] **M10.1** 7 干预实验: 各跑 200 hybrid (用 Exp 1 final population pair 抽)
- [ ] **M10.2** 6 module pair 分组 ANOVA
- [ ] **M10.3** 主回归 MixedLM (per EXP_DESIGN.md §4.5)

### Output
- `experiments/exp_4/results.json` (interventions + module_pairs + main_regression)

### 完成判据
- `|γ_epi| > |γ_gd|` 且 p(γ_epi) < 0.01
- 7 干预中至少 3 个显著降 HFL (semantic repair / common interface 必显著)

### Abort Gate
- G4.1: |γ_epi| ≤ |γ_gd| → H4 fail
- G4.2: γ_epi p > 0.05 → 加跑 pair 至 300
- G4.3: 干预 → HFL ↑ → 干预 bug

### 预算
- API cost: $20–35
- Wallclock: 3 天

---

## M11 — Exp 5 L_c Scaling Law (Day 15-18)

**目的**: H5 — empirical L_c vs theoretical L_c Pearson r ≥ 0.5.

### Input
- M4 完成 → α 估值 + L_c_theoretical (∈ [6, 18] 估)
- core SAET 实现 (M1)

### Tasks
- [ ] **M11.1** Finalize L-sweep: 用 M4 给的 L_c estimate, 在其 ± 1 内集中 5 seed, 其他点 3 seed
- [ ] **M11.2** 实现 L 调整 mutation operator: 给 founder L=7 加/删 hidden node 到 target L
- [ ] **M11.3** 跑 9 个 L 点 × seeds, N=32, T=50, 2 niche (Planning + Web)
- [ ] **M11.4** Segmented regression on log HFL vs log L
- [ ] **M11.5** L_c_emp vs L_c_theo Pearson r

### Output
- `experiments/exp_5/results.json`

### 完成判据
- segmented regression F-test p < 0.05 (slope break 存在)
- Pearson r ≥ 0.5

### Abort Gate
- G5.1: F-test p > 0.10 → H5 fail
- G5.2: r < 0.3 → H5 fail
- G5.3: 跑 5/9 L > $40 → 降 T=50 → T=30

### 预算
- API cost: $40–60
- Wallclock: 3–4 天

---

## M12 — Exp 6 Species Dynamics (Day 16-19, 与 M11 部分并行)

**目的**: G6 — ≥ 1 species pair persistence ≥ 20 gen + survival analysis.

### Input
- Exp 1 cell_3 数据 (condition 1 stable niches)
- core SAET 实现 (M1)

### Tasks
- [ ] **M12.1** 5 new condition × 1 seed × N=32 × T=100
- [ ] **M12.2** 跟 lineage_tree birth / extinction event
- [ ] **M12.3** Cox PH survival regression

### Output
- `experiments/exp_6/results.json`

### 完成判据
- 至少 1 species pair persistence ≥ 20 gen 在 stable niches
- Cox PH 各 covariate 至少 1 个 hazard ratio CI 不跨 1.0

### Abort Gate
- G6.1: 无 species pair ≥ 10 gen → 升级 (与 G1.4 同)
- G6.2: > $80 在 3/6 condition → 暂停

### 预算
- API cost: $40–60
- Wallclock: 4–5 天

---

## M13 — Exp 7 Transfer + Cross-model (Day 18-20)

**目的**: G7 — ≥ 1 held-out benchmark RII > 0.15; Part B 降级; Part C 4 crossover.

### Input
- Exp 1 cell_3 final population, 选 top 2 species 各 4 agent

### Tasks
- [ ] **M13.1** Part A: 4 held-out benchmark eval — SWE-bench Verified (if available) / AgentBench DB / PlanBench held-out (depots+mystery_bw) / LoCoMo held-out
- [ ] ~~M13.2 Part B~~: **删 (Director Q3 决策, 2026-06-19 13:21 UTC)**. 论文 Limitations / Future Work 节明示 "cross-model reproduction reserved for future work due to operational LLM API constraint"
- [ ] **M13.3** Part C: 4 crossover 类型 × 50 hybrid 比较 HFL

### Output
- `experiments/exp_7/results.json`

### 完成判据
- 至少 1/4 benchmark RII > 0.15
- Part C: typed_subgraph > weight-merge (per H0.lit_B2 prediction)

### Abort Gate
- G7.1: 全 4 benchmark RII < 0.10 → G7 fail
- G7.2: SWE-bench Verified docker fail → 3 benchmark
- G7.3: 某 crossover 100% invalid → 跳过

### 预算
- API cost: $30–50
- Wallclock: 2–3 天

---

## EXP-DESIGN-4: SWE-bench Lite 决策汇总 (Director 拍板用)

**1. Pilot 阶段 (M6)**: ✅ **跳过 SWE-bench Lite** (per 人类批准, checklist §1.8)
- pilot 只跑 PlanBench + WebArena, 2 niche, 信号探测足够

**2. Main 阶段 docker warmup 时机**:
- **必须 M5 完成前 docker ready** (即 Day 5 前). 理由:
  - M7 (Exp 1) cell_3 4-niche 需要 SWE-bench Lite 评估
  - Docker pull 1-3h (300 instance, 80–150GB) 是 wall-clock long tail
  - 必须 M1 启动时 background pull (`tmux nohup docker pull` × 300 instance)
- **具体时间线**:
  - M1 (Day 0-1): docker daemon `data-root=/data1` ready (Anonymous 操作, 30 min) + 启动 background pull
  - M1 Day 1 end: 至少 50% instance pulled
  - M5 (Day 5) end: 100% instance pulled + smoke test 1 instance harness 跑通
  - M7 (Day 7+): 正式启用 SWE-bench Lite eval

**3. Anonymous docker /data1 sudo 没做的 plan B**:
- **触发条件**: M1 Day 1 结束仍未完成 `daemon.json` 改 + docker restart
- **plan B-1 (推荐)**: **整个 SWE-bench Lite 跳过, 全程 3-niche (planning + web + memory)**
  - 论文 §4 改为 "code niche reserved for future work; current experiments cover 3 ecological niches"
  - 影响 H1 文本: "4-niche" → "3-niche"
  - **G1 通过门槛是否变?** **我的判断: 不变, 仍可通过**.
    - EST 理论 (定理 4 + Prop 1) 只要求 K ≥ 2 niche heterogeneity 触发 isolation; 3 vs 4 niche 不变 mechanism
    - 文献先例 (Anderson & Harmon 2013) 也是 3 niche 起步
    - 风险: 3 niche specialization 路径减 25%, 可能 stable species count 降低 (Exp 1 期望 2 species → 实际可能 1.5 平均). 若降到 < 2 species, G1 partial fail
    - 应对: 若 3-niche cell_3 平均 species count < 2, 论文 frame 调整为 "single stable species pair 涌现", 仍满足 H0 主张 (有 reproductive isolation), 只是 species count 降级.
  - **Director 判断点**: 是否接受 G1 在 3-niche 下"≥3/5 seeds 至少 1 stable species pair (RII > 0.25)" 的降级门槛? 我建议: 接受 (论文核心论点不受影响, 只是 quantitative weaker)
- **plan B-2**: 延迟 M7 等 docker ready
  - 缺点: 总时长可能拖到 20+ 天, revision buffer 缩水
  - 不推荐, 除非 Anonymous 承诺 Day 3 前能完成

**4. SWE-bench Lite docker 拉取部分失败 (e.g. 250/300 instance pull 成功)**:
- 可接受, 用 stratified sample 80 instance 而不是 100 instance (per niche_profiles.md §4.6)
- 论文报告 "100 task subset from successfully pulled instances"

**5. 我对 Director 的具体询问**:
- ❓ 是否同意上述 plan B-1 (3-niche fallback)?
- ❓ 是否同意 3-niche 下 G1 门槛降级为 "≥3/5 seeds 至少 1 stable species pair" (而不是 "≥ 2 stable species")?
- ❓ Anonymous 何时能完成 docker daemon 改? 这决定 M7 启动时间.

---

## 总体时间盘 (理想 vs 保守)

| 阶段 | 理想 | 保守 (1.5x buffer) |
|---|---:|---:|
| M1 infra | 1 天 | 2 天 |
| M2 anchor_1 | 0.5 天 | 1 天 |
| M3 anchor_2 | 0.5 天 | 1 天 |
| M4 anchor_3 | 0.5 天 | 1 天 |
| M5 anchor_4 | 1 天 | 2 天 |
| M6 pilot | 1 天 | 1.5 天 |
| M7 Exp 1 | 4-5 天 | 6 天 |
| M8 Exp 2 | overlap | 1-2 day net |
| M9 Exp 3 | 2 天 | 3 天 |
| M10 Exp 4 | overlap | 1 day net |
| M11 Exp 5 | 3-4 天 | 5 天 |
| M12 Exp 6 | overlap | 1 day net |
| M13 Exp 7 | 2-3 天 | 4 天 |
| **总** | **~17 天** | **~28 天** |

**与 checklist §1.12 估值 (15-20 天) 对照**: 我的理想路径 17 天落在区间内; 保守 28 天超 8 天, 需要削减 (见 EXP_DESIGN §9 trade-off).

---

## 全局风险总结 (按 severity 排序)

| 风险 | Severity | Mitigation |
|---|---:|---|
| anchor_4 single-niche RII > 0.10 (定理 3 fail) | 🚨 Critical | 整个项目 ABORT, 必须先于 main 跑 |
| API 累计成本超 500 USD | 🚨 High | budget_tracker.json 实时跟踪, GA.global 自动停 |
| SWE-bench docker 不 ready 卡 M7 | High | plan B-1 (3-niche) |
| founder 在 PlanBench < 60% | High | founder_genome_v0.md §4.3 回退方案 |
| RCC AUROC 不达标 (H3 fail) | Medium | 论文降级 "competitive" framing |
| L_c slope break 不可观测 (H5 fail) | Medium | 论文 H5 → future work |
| MAP-Elites RII > 0.20 (G2 fail) | Medium | 重 frame H2 |
| WebArena docker 5 站点不稳 | Medium | 用 shopping/reddit 替代 gitlab/map |
| SERVER_HOSTNAME SSH 断连 | Low | nohup + checkpoint 每 10 gen |
| Azure rate limit | Low | client.py 5 retry + exponential backoff |

---

## 给 Director 的 RUNNING 阶段每日 checklist (建议)

**每日 standup (Director 视角)**:
1. 当前活跃 milestone 是哪个? cost 累计?
2. 任何 abort gate 触发?
3. 当前 hypothesis tree status (哪些 anchor pending / confirmed)?
4. ml_engineer 是否有 hold-up 需 Director 介入?

**每日 ml_engineer 自检**:
1. `cat ./experiments/budget_tracker.json` (cost check)
2. `ssh SERVER_HOSTNAME "df -h /data1"` (storage check)
3. `ssh SERVER_HOSTNAME "ps aux | grep python | wc -l"` (active job count)
4. EXPERIMENT_LOG.md 当日有更新

---

**ROADMAP.md 锁定**. 实际跑 M7+ 时, Director 需根据 M2-M6 结果可能 micro-adjust Exp 1-7 配置 (e.g. niche 数, seed 数), 任何调整都要 update 本文档对应 milestone 节。

— ml_engineer_claude, 2026-06-19 JST
