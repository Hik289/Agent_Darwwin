"""PlanBench niche evaluator.

Expected local assets:
  - Locate PlanBench repo + Fast Downward + VAL under data/
  - Provide list_blocksworld_instances / list_logistics_instances
  - Provide DEFAULT_PILOT_SUBSET (50 task: 25 blocksworld + 25 logistics)

Full agent-based eval runs through the experiment drivers.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PLANBENCH_ROOT = Path("./data/planbench/plan-bench")
FAST_DOWNWARD = Path("./data/fast_downward")
VAL_BIN = Path("./data/val/build/linux64/Release/bin")


def env_ready() -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not PLANBENCH_ROOT.exists():
        issues.append(f"PlanBench root missing: {PLANBENCH_ROOT}")
    if not (FAST_DOWNWARD / "builds" / "release" / "bin" / "downward").exists():
        issues.append(f"Fast Downward binary missing: {FAST_DOWNWARD}/builds/release/bin/downward")
    # VAL package binary set: Parser + PlanToValStep etc. The plan validator is usually called Validate.
    val_bins = list(VAL_BIN.glob("*")) if VAL_BIN.exists() else []
    has_validate = any("validate" in p.name.lower() or "valstep" in p.name.lower() for p in val_bins)
    if not val_bins:
        issues.append(f"VAL binaries missing: {VAL_BIN}")
    elif not has_validate:
        issues.append(f"WARN: VAL binaries present but no Validate-style binary; have {[p.name for p in val_bins[:6]]}")
    return (not issues), issues


def list_blocksworld_instances() -> list[Path]:
    if not PLANBENCH_ROOT.exists():
        return []
    out = []
    for sub in ["instances/blocksworld", "instances", "data"]:
        d = PLANBENCH_ROOT / sub
        if d.exists():
            for p in d.rglob("*.pddl"):
                if "block" in p.name.lower() or "block" in str(p.parent).lower():
                    out.append(p)
    return sorted(set(out))[:200]


def list_logistics_instances() -> list[Path]:
    if not PLANBENCH_ROOT.exists():
        return []
    out = []
    for sub in ["instances/logistics", "instances", "data"]:
        d = PLANBENCH_ROOT / sub
        if d.exists():
            for p in d.rglob("*.pddl"):
                if "logistics" in p.name.lower() or "logistics" in str(p.parent).lower():
                    out.append(p)
    return sorted(set(out))[:200]


# Per niche_profiles.md §2.4 — pilot subset spec
DEFAULT_PILOT_SUBSET = {
    "blocksworld_t1_instances": list(range(1, 26)),
    "logistics_t1_instances": list(range(1, 26)),
}


def smoke_test() -> int:
    print("=== PlanBench niche smoke test ===")
    ok, issues = env_ready()
    print(f"env_ready: {ok}")
    for i in issues:
        print(f"  - {i}")
    bw = list_blocksworld_instances()
    lg = list_logistics_instances()
    print(f"blocksworld pddl instances: {len(bw)} (first 3: {[p.name for p in bw[:3]]})")
    print(f"logistics  pddl instances: {len(lg)} (first 3: {[p.name for p in lg[:3]]})")
    # Try Parser (any VAL exe) as a basic sanity (it should print usage and exit non-zero)
    for binname in ["Parser", "Validate", "Analyse"]:
        b = VAL_BIN / binname
        if b.exists():
            rc = subprocess.run([str(b)], capture_output=True, timeout=5).returncode
            print(f"VAL {binname} invocation returncode: {rc} (non-zero = usage shown = OK)")
            break
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(smoke_test())
