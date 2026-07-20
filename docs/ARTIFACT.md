# Artifact Guide

This guide maps the public `Agent_Darwwin` repository to a reviewer-friendly artifact workflow for `Agent Species`. It is meant to make the release easier to inspect in the style of ICML, ICLR, NeurIPS, and similar artifact-review processes.

## What To Inspect First

- `experiments/`: Experiment drivers, ablations, and benchmark-specific runners.
- `data/`: Small fixtures, schemas, manifests, or data-layout notes; large data should stay outside git.
- `assets/`: README and paper-facing visual assets.
- `analysis/`: Post-processing, table, and figure-generation scripts.
- `paper_analysis/`: Post-hoc analysis scripts for paper figures and tables.

## Environment Files

- `requirements.txt`: Primary Python dependency list.
- `.env.example`: Template for local credentials or backend configuration.

## Minimal Verification

Run these checks in a fresh environment before launching expensive jobs:

```bash
python -m compileall -q .
python -m pytest experiments/tests -q
python experiments/tests/test_m1_smoke.py
```

## Reproduction And Analysis Entry Points

These are the main tracked files to inspect for paper-scale or benchmark-scale reproduction. Some require arguments, credentials, downloaded benchmarks, or local data paths described in the README.

- `python analysis/b1_plot.py`
- `python analysis/b1_rcc_sensitivity.py`
- `python analysis/b2_bistability.py`
- `python analysis/b3_plot.py`
- `python analysis/b3_plot_v2.py`
- `python analysis/b3_raw_pairwise.py`
- `python analysis/scripts_plot.py`
- `python experiments/core/mag.py`
- `python experiments/exp1_cell3.py`
- `python experiments/exp1_cell3_v17.py`
- `python experiments/m2_anchor1.py`
- `python experiments/m2_b0_runner.py`
- `python experiments/m5_anchor4.py`
- `python experiments/niches/planbench.py`

## Figure Assets

- `assets/figure1_saet_loop.png`
- `assets/figure2_rcm_construction.png`
- `assets/figure3_rcc_clustering.png`
- `main.pdf`

## Data, Credentials, And Generated Outputs

- API-backed runs should read credentials from environment variables or local `.env` files only; never commit real keys or provider-specific secrets.
- Record provider endpoint, model/deployment name, sampling parameters, and execution date for every API-backed table or figure.
- Treat generated JSONL files, logs, caches, model checkpoints, and benchmark downloads as local artifacts unless explicitly tracked as fixtures.
- For stochastic experiments, record seeds, task counts, dataset splits, and the exact git commit used for the run.

## Reviewer Reporting Checklist

- `git rev-parse HEAD`
- Python version and dependency-install command
- Full command line for every table, figure, or benchmark cell
- Paths to raw outputs and aggregation scripts
- External data, benchmark, or API-backed steps that were intentionally skipped
