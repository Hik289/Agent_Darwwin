# Agent Species

Code release for **Detectable Reproductive Isolation in LLM Agent Populations Requires Hard Interface Incompatibility**.

This repository contains the Synthetic Agent Evolution Testbed (SAET), Modular Agent Genome (MAG) utilities, reproductive-compatibility measurement code, synthetic validation experiments, and plotting scripts used to study whether LLM-agent populations develop species-like reproductive boundaries.

## Overview

The testbed evolves populations of modular LLM agents across planning, long-context memory, and retrieval-style niches. It measures reproductive compatibility by crossing agent genomes, evaluating hybrid offspring, and clustering the resulting compatibility matrix.

The main empirical finding supported by these scripts is that ecological pressure alone did not produce a stable, detectable species boundary in the tested settings. Detectable reproductive isolation appears only when hard interface incompatibility is introduced. With fine-grained RCC measurement, those hard boundaries can become spectrally bistable: the underlying incompatibility remains, while cluster validity can flicker as within-lineage signal crosses the threshold.

Key terms:

- **MAG**: Modular Agent Genome, a typed representation of an LLM-agent workflow.
- **SAET**: Synthetic Agent Evolution Testbed, the evolutionary loop and evaluation harness.
- **RCM**: Reproductive Compatibility Matrix, measuring ordered parent-pair hybrid viability.
- **RCC**: Reproductive Compatibility Clustering, spectral clustering over the RCM with validity filters.
- **RII**: Reproductive Isolation Index, comparing between-lineage and within-lineage compatibility.

## Repository Layout

```text
.
├── analysis/                    # Post-hoc analysis and figure-generation scripts
├── data/                        # Bundled founder genomes
├── experiments/
│   ├── core/                    # MAG, crossover, SAET loop, LLM client, agent runner
│   ├── niches/                  # PlanBench, LoCoMo, and HotpotQA evaluators
│   ├── synthetic/               # API-free synthetic validation experiments
│   ├── tests/                   # Lightweight smoke tests
│   ├── exp1_cell3.py            # Spontaneous multi-niche baseline
│   ├── exp1_cell3_v17.py        # Hand-seeded controls and ablations
│   ├── m2_anchor1.py            # Founder calibration anchor
│   ├── m2_b0_runner.py          # Founder baseline runner
│   ├── m5_anchor4.py            # Single-niche negative control
│   └── calibration.json         # Calibration constants used by experiment runners
├── .env.example                 # Environment-variable template
├── requirements.txt
└── README.md
```

Generated outputs are written to `results/` or `paper/data/` and are ignored by git.

## Installation

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The synthetic experiments use only local Python dependencies. The LLM-agent experiments additionally require an OpenAI-compatible Azure endpoint and external benchmark assets.

## API Configuration

Copy the environment template and fill in your credentials:

```bash
cp .env.example .env
```

Then export the variables before running LLM experiments:

```bash
set -a
source .env
set +a
```

Required variables:

```bash
AZURE_ENDPOINT=https://YOUR_RESOURCE.openai.azure.com/openai/v1
AZURE_API_KEY=YOUR_AZURE_API_KEY
AZURE_MODEL=gpt-5.4-mini
```

The client reads these variables in `experiments/core/llm_client.py`. You may use a different OpenAI-compatible model, but that should be treated as a new experimental condition.

## External Benchmark Assets

This release includes the code and founder genomes, but not large external benchmark repositories or raw result caches. Place external assets under `data/` before running the full LLM experiments:

```text
data/
├── planbench/plan-bench/
├── val/build/linux64/Release/bin/Validate
├── locomo/snap_locomo/data/locomo10.json
└── ...
```

The API-free synthetic experiments do not require these assets.

## Quick Checks

Run the smoke tests from the repository root:

```bash
python experiments/tests/test_m1_smoke.py
```

Run the synthetic validation experiments:

```bash
python experiments/synthetic/run_exp4_regression.py
python experiments/synthetic/run_exp5_lsweep.py
python experiments/synthetic/run_exp6_dynamics.py
```

These commands write JSON summaries under `results/`.

## Main LLM Experiments

Run all commands from the repository root.

### Spontaneous Multi-Niche Baseline

```bash
python experiments/exp1_cell3.py \
  --niches planbench_blocksworld locomo hotpotqa \
  --N 24 --T 30 --eval-every 5 \
  --R-rcm 3 --rcm-eval-tasks 2 --pop-eval-tasks 4 \
  --mu 0.05 --beta 5.0 --m-migration 0.05 \
  --lambda-c 0.1 --tau-in 0.10 --tau-out 0.05 \
  --mismatch-mode soft \
  --founder data/founder_genome_v4_typed.json \
  --out results/spontaneous_baseline.json \
  --progress results/spontaneous_baseline_progress.json
```

### Hand-Seeded Positive Control

This setting introduces strict typed interface boundaries and verifies that RCM/RCC detects reproductive isolation when hybrid viability is mechanically suppressed by incompatible interfaces.

```bash
python experiments/exp1_cell3_v17.py \
  --niches planbench_blocksworld locomo hotpotqa \
  --N 24 --T 30 --eval-every 5 \
  --R-rcm 3 --rcm-eval-tasks 2 --pop-eval-tasks 4 \
  --mu 0.05 --beta 5.0 --m-migration 0.0 \
  --lambda-c 0.1 --tau-in 0.10 --tau-out 0.05 \
  --mismatch-mode rigid --mutate-type-weight 0.0 \
  --hand-seed --seed 50 --budget 50 \
  --founder data/founder_genome_v4_typed.json \
  --out results/positive_control.json \
  --progress results/positive_control_progress.json
```

### Mild-Evolution Hand-Seeded Setting

```bash
python experiments/exp1_cell3_v17.py \
  --niches planbench_blocksworld locomo hotpotqa \
  --N 24 --T 30 --eval-every 5 \
  --R-rcm 3 --rcm-eval-tasks 2 --pop-eval-tasks 4 \
  --mu 0.10 --beta 5.0 --m-migration 0.05 \
  --lambda-c 0.1 --tau-in 0.10 --tau-out 0.05 \
  --mismatch-mode rigid --mutate-type-weight 0.05 \
  --hand-seed --seed 51 --budget 50 \
  --founder data/founder_genome_v4_typed.json \
  --out results/mild_evolution.json \
  --progress results/mild_evolution_progress.json
```

### Fine-Grained RCC Measurement

Use `--eval-every 1` to measure RCC every generation.

```bash
python experiments/exp1_cell3_v17.py \
  --niches planbench_blocksworld locomo hotpotqa \
  --N 24 --T 25 --eval-every 1 \
  --R-rcm 3 --rcm-eval-tasks 2 --pop-eval-tasks 4 \
  --mu 0.05 --beta 5.0 --m-migration 0.05 \
  --lambda-c 0.1 --tau-in 0.10 --tau-out 0.05 \
  --mismatch-mode rigid --mutate-type-weight 0.05 \
  --hand-seed --seed 51 --budget 50 \
  --founder data/founder_genome_v4_typed.json \
  --out results/fine_rcc.json \
  --progress results/fine_rcc_progress.json
```

## Analysis Scripts

The scripts in `analysis/` expect result JSON files to be available under `paper/data/results_cache/`. This repository does not bundle raw cached API outputs.

Typical workflow:

```bash
mkdir -p paper/data/results_cache
# copy or symlink completed result JSON files into paper/data/results_cache/
python analysis/b1_rcc_sensitivity.py
python analysis/b1_plot.py
python analysis/b3_raw_pairwise.py
python analysis/b3_plot_v2.py
python analysis/b2_bistability.py
```

## Notes on Cost and Reproducibility

LLM experiments are API-cost sensitive. The RCM parameter `--R-rcm` controls the number of hybrid offspring evaluated per ordered parent pair; increasing it improves compatibility estimates but increases cost approximately linearly.

Synthetic experiments are deterministic up to the provided random seeds and should run without external services. LLM experiments depend on model version, endpoint behavior, benchmark asset versions, and API availability, so results from another provider or model should be reported as a separate condition.
