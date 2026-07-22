# Artifact Guide

Operational notes for reproducing `Agent Species` from the public `Agent_Darwwin` repository.

## Review Path

- `experiments/`: Experiment drivers, ablations, and benchmark-specific runners.
- `data/`: Small fixtures, schemas, manifests, or data-layout notes; large data should stay outside git.
- `assets/`: README and paper-facing visual assets.
- `analysis/`: Post-processing, table, and figure-generation scripts.
- `paper_analysis/`: Post-hoc analysis scripts for paper figures and tables.

## Environment Files

- `requirements.txt`: Primary Python dependency list.
- `.env.example`: Template for local credentials or backend configuration.

## Smoke Checks

Run these checks before long jobs:

```bash
python -m compileall -q .
python -m pytest experiments/tests -q
python experiments/tests/test_m1_smoke.py
```

## Reproduction Entry Points

Main tracked entry points for paper-scale or benchmark-scale runs:

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

## Data And Outputs

- API-backed runs should read credentials from environment variables or local `.env` files only; never commit real keys or provider-specific secrets.
- Record provider endpoint, model/deployment name, sampling parameters, and execution date for every API-backed table or figure.
- Treat generated JSONL files, logs, caches, model checkpoints, and benchmark downloads as local artifacts unless explicitly tracked as fixtures.
- For stochastic experiments, record seeds, task counts, dataset splits, and the exact git commit used for the run.

## Reporting Checklist

- `git rev-parse HEAD`
- Python version and dependency-install command
- Full command line for every table, figure, or benchmark cell
- Paths to raw outputs and aggregation scripts
- External data, benchmark, or API-backed steps that were intentionally skipped
