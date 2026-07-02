"""
B3 Figure 7 v2: Faceted raw pairwise compatibility distributions (Option A).

Director directive 21:08 UTC: original figure had overlapping curves;
re-paint as multi-panel grid, one run per panel, showing K_within and
K_between density traces over generations. Clearly distinguishes
Mechanism A (Exp1.1 high K_w ~0.47, single niche generalist) from
Mechanism B (other K=1 runs low K_w ~0.10, soft mode floor).

Style: NeurIPS publication-ready, 300 dpi, white bg, sans-serif.
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

CACHE = Path("./paper/data/results_cache")
DATA = Path("./paper/data")

# Panel grid: 8 runs (4 K=1 mechanism panels + 4 K>=2 panels), 4x2 layout
PANELS = [
    # K=1 RII=0 runs
    {"id": "Exp1.1", "file": "exp1_1_prod.json",
     "title": "Exp1.1 (1-niche, no hand-seed, soft)",
     "subtitle": "K=1 forever; high K_w (Mechanism A)",
     "row": 0, "col": 0},
    {"id": "Exp2_b4", "file": "b4_prod.json",
     "title": "Exp2_b4 (hand-seed + soft)",
     "subtitle": "K=1 forever; low K_w (Mechanism B)",
     "row": 0, "col": 1},
    {"id": "Exp2_b5", "file": "b5_prod.json",
     "title": "Exp2_b5 (no hand-seed + soft)",
     "subtitle": "K=1 forever; low K_w (Mechanism B)",
     "row": 1, "col": 0},
    {"id": "Exp2_b1", "file": "b1_prod.json",
     "title": "Exp2_b1 (no-pop-crossover + soft)",
     "subtitle": "K=1 forever; low K_w (Mechanism B)",
     "row": 1, "col": 1},
    # K>=2 runs
    {"id": "v17.1", "file": "v17_prod.json",
     "title": "v17.1 (3-niche, rigid hand-seed, m=0)",
     "subtitle": "K=2-5 sustained; G1 PASS",
     "row": 2, "col": 0},
    {"id": "Exp1.2", "file": "exp1_2_prod.json",
     "title": "Exp1.2 (2-niche, rigid hand-seed)",
     "subtitle": "K=4-2 partial then K=1 (gen 20+)",
     "row": 2, "col": 1},
    {"id": "v18_fine", "file": "v18_fine_rcc.json",
     "title": "v18 fine RCC (rigid, every-gen)",
     "subtitle": "Bistability: K alternates 1/2",
     "row": 3, "col": 0},
    {"id": "Exp7C_uniform", "file": "exp7c_uniform_prod.json",
     "title": "Exp 7C (rigid + uniform crossover)",
     "subtitle": "K=2-3 early, then K=1",
     "row": 3, "col": 1},
]

# Set matplotlib style
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

fig, axes = plt.subplots(4, 2, figsize=(11, 12), sharex=False, sharey=False)

COLOR_KW = "#1f77b4"  # blue
COLOR_KB = "#d62728"  # red
COLOR_DIFF_FILL = "#9467bd"  # purple
TAU_IN = 0.10
TAU_OUT = 0.05

for panel in PANELS:
    fp = CACHE / panel["file"]
    if not fp.exists():
        continue
    p = json.load(open(fp))
    rcc = p.get("rcc_history", [])

    gens = [r["gen"] for r in rcc]
    k_w = [r.get("K_within_mean", 0.0) for r in rcc]
    k_b = [r.get("K_between_mean") if r.get("K_between_mean") is not None else 0.0 for r in rcc]
    n_clusters = [r.get("n_clusters", 1) for r in rcc]

    ax = axes[panel["row"], panel["col"]]
    # Shaded band for K_w-K_b
    ax.fill_between(gens, k_w, k_b, color=COLOR_DIFF_FILL, alpha=0.12, label="K_w − K_b gap")
    # Lines
    ax.plot(gens, k_w, "-o", color=COLOR_KW, label="K_within", markersize=4, linewidth=1.5)
    ax.plot(gens, k_b, "-s", color=COLOR_KB, label="K_between", markersize=4, linewidth=1.5)
    # Threshold lines
    ax.axhline(TAU_IN, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
    ax.axhline(TAU_OUT, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
    # Mark K>=2 generations with green tick on top
    for i, nc in enumerate(n_clusters):
        if nc >= 2:
            ax.axvline(gens[i], ymin=0.95, ymax=1.0, color='green', linewidth=2, alpha=0.7)

    # Title block
    ax.set_title(f"{panel['title']}\n{panel['subtitle']}", fontsize=8.5, loc='left', pad=4)

    # Determine y-limit based on K_w range
    y_max = max(max(k_w), max(k_b)) * 1.15 if k_w else 0.6
    y_max = max(y_max, 0.20)  # at least show tau lines
    ax.set_ylim(0, y_max)

    # X axis labels only on bottom rows
    if panel["row"] == 3:
        ax.set_xlabel("Generation")
    # Y axis labels only on left column
    if panel["col"] == 0:
        ax.set_ylabel("Pairwise compatibility K")

    # Annotations for tau lines (only first panel)
    if panel["row"] == 0 and panel["col"] == 0:
        ax.text(gens[-1] * 0.55, TAU_IN + 0.012, r"$\tau_{in}=0.10$",
                fontsize=7.5, color='gray', ha='left')
        ax.text(gens[-1] * 0.55, TAU_OUT - 0.025, r"$\tau_{out}=0.05$",
                fontsize=7.5, color='gray', ha='left')

    # Grid
    ax.grid(True, alpha=0.18, linewidth=0.5)

# Single legend on top
handles = [
    plt.Line2D([], [], color=COLOR_KW, marker='o', linewidth=1.5, label="K_within (mean pairwise within RCC cluster)"),
    plt.Line2D([], [], color=COLOR_KB, marker='s', linewidth=1.5, label="K_between (mean pairwise across clusters)"),
    plt.Rectangle((0,0), 1, 1, facecolor=COLOR_DIFF_FILL, alpha=0.25, label="K_w − K_b gap"),
    plt.Line2D([], [], color='gray', linestyle='--', linewidth=1, label=r"$\tau_{in}=0.10$ (within threshold)"),
    plt.Line2D([], [], color='gray', linestyle=':', linewidth=1, label=r"$\tau_{out}=0.05$ (between threshold)"),
    plt.Line2D([], [], color='green', linewidth=3, alpha=0.7, label="K ≥ 2 detected (green tick)"),
]
fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, 1.005),
           ncol=3, frameon=True, fontsize=8, edgecolor='black')

plt.suptitle("Figure 5: Raw pairwise compatibility distributions across runs\n"
             "K=1 panels show two mechanisms (A: Exp1.1 high K_w; B: low K_w + soft floor); K≥2 panels show K_w > K_b separation",
             fontsize=10.5, y=1.045)
plt.tight_layout()

OUT_NEW = DATA / "figure7_raw_pairwise_v2.png"
plt.savefig(OUT_NEW, dpi=300, bbox_inches='tight')
print(f"Wrote {OUT_NEW}")

# Also replace original (as Director requested)
OUT_ORIG = DATA / "figure7_raw_pairwise.png"
plt.savefig(OUT_ORIG, dpi=300, bbox_inches='tight')
print(f"Wrote {OUT_ORIG}")
plt.close()
