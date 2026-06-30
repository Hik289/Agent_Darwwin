"""Smoke tests that run without LLM calls (pure unit tests for MAG + crossover)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# allow running from `experiments/` root
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent))  # add agentspecies/ to path
sys.path.insert(0, str(HERE))

from core import mag, crossover  # noqa: E402

DATA = HERE.parent / "data"
FOUNDER_PATH = DATA / "founder_genome_v0.json"


def test_load_founder():
    assert FOUNDER_PATH.exists(), f"founder genome missing at {FOUNDER_PATH}"
    g = mag.load_mag(FOUNDER_PATH)
    assert isinstance(g, dict)
    assert "modules" in g
    return g


def test_full_validate_founder():
    g = mag.load_mag(FOUNDER_PATH)
    ok, viol = mag.full_validate(g)
    if not ok:
        print("Validation report:")
        for cat, vs in viol.items():
            print(f"  {cat}:")
            for v in vs:
                print(f"    - {v}")
    assert ok, "founder failed full_validate"


def test_extract_replace_idempotent():
    g = mag.load_mag(FOUNDER_PATH)
    for mk in mag.MODULE_KEYS:
        Q = mag.extract_typed_subgraph(g, mk)
        child = mag.replace_subgraph(g, mk, Q)
        assert child["modules"] == g["modules"], f"replace({mk}) not idempotent"


def test_self_crossover_identity():
    g = mag.load_mag(FOUNDER_PATH)
    assert crossover.sanity_self_crossover_identity(g)


def test_cross_module_returns_independent_copy():
    g = mag.load_mag(FOUNDER_PATH)
    child = crossover.typed_subgraph_crossover(g, g, module_choice="planner")
    # mutating child must not affect parent
    child["modules"]["planner"]["depth"] = 999
    assert g["modules"]["planner"]["depth"] != 999, "shared reference: deep copy missing"


TESTS = [
    ("load_founder", test_load_founder),
    ("full_validate_founder", test_full_validate_founder),
    ("extract_replace_idempotent", test_extract_replace_idempotent),
    ("self_crossover_identity", test_self_crossover_identity),
    ("cross_module_returns_independent_copy", test_cross_module_returns_independent_copy),
]


def main() -> int:
    fail = 0
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            fail += 1
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {name}: {type(e).__name__}: {e}")
            fail += 1
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
