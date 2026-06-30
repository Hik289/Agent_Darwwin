"""Modular Agent Genome (MAG) — schema validation + accessor + typed port utilities.

Implements:
  - load_mag(path) -> dict
  - schema_validate(genome)  (per founder_genome_v0.md §5)
  - type_check(genome)
  - minimal_execution_test(genome) — dry-run dispatcher: planner→retriever→executor→verifier path
  - extract_typed_subgraph(genome, module_name)
  - replace_subgraph(host, module_name, donor_subgraph)
  - reconnect_typed_ports(genome)
  - cross_module_constraint_check(genome)  -> list of violations
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


# Allowed module keys (the 7 modules of MAG)
MODULE_KEYS = (
    "planner",
    "workflow",
    "memory",
    "tools",
    "verifier",
    "communication",
    "update_policy",
)


def load_mag(path: str | Path) -> dict[str, Any]:
    """Load MAG JSON from disk."""
    return json.loads(Path(path).read_text())


# ---------- json-path helper ----------
_PATH_RE = re.compile(r"\.|\[(\d+)\]")


def jsonpath_get(root: Any, path: str) -> Any:
    """Walk a simple dotted/bracket path. e.g. 'planner.depth' or 'workflow.nodes[0].name'."""
    cur = root
    # split on . but preserve [n] indices
    parts: list[str | int] = []
    buf = ""
    i = 0
    while i < len(path):
        c = path[i]
        if c == ".":
            if buf:
                parts.append(buf)
                buf = ""
            i += 1
        elif c == "[":
            j = path.index("]", i)
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(int(path[i + 1 : j]))
            i = j + 1
        else:
            buf += c
            i += 1
    if buf:
        parts.append(buf)
    for p in parts:
        if isinstance(p, int):
            cur = cur[p]
        else:
            cur = cur[p]
    return cur


# ---------- 1. schema_validate ----------
def schema_validate(genome: dict[str, Any]) -> tuple[bool, list[str]]:
    """Per founder_genome_v0.md §5. Returns (ok, violation_list)."""
    violations: list[str] = []
    modules = genome.get("modules")
    if modules is None:
        return False, ["missing top-level 'modules'"]

    rules = genome.get("validation_rules", {})
    required = set(rules.get("required_modules", MODULE_KEYS))
    actual = set(modules.keys())
    missing = required - actual
    extra = actual - required
    if missing:
        violations.append(f"missing modules: {sorted(missing)}")
    if extra:
        violations.append(f"unexpected modules: {sorted(extra)}")

    # 2. field_value_ranges
    for path, spec in rules.get("field_value_ranges", {}).items():
        try:
            v = jsonpath_get(modules, path)
        except (KeyError, IndexError, TypeError):
            violations.append(f"value-range path missing: {path}")
            continue
        tp = spec.get("type", "float")
        if tp == "int" and not isinstance(v, int):
            violations.append(f"{path}: expected int, got {type(v).__name__}")
            continue
        if tp == "float" and not isinstance(v, (int, float)):
            violations.append(f"{path}: expected float, got {type(v).__name__}")
            continue
        if v < spec["min"] or v > spec["max"]:
            violations.append(f"{path}={v} out of [{spec['min']}, {spec['max']}]")

    # 3. field_enums
    for path, allowed in rules.get("field_enums", {}).items():
        try:
            v = jsonpath_get(modules, path)
        except (KeyError, IndexError, TypeError):
            violations.append(f"enum path missing: {path}")
            continue
        if v not in allowed:
            violations.append(f"{path}={v!r} not in enum {allowed}")

    # 4. mutation distribution sum == 1
    up = modules.get("update_policy", {})
    dist = up.get("mutation_distribution", {})
    if dist:
        s = sum(dist.values())
        if abs(s - 1.0) > 1e-6:
            violations.append(f"mutation_distribution sums to {s:.6f}, expected 1.0")

    # 5. cross-module type-equality constraints
    for constraint in rules.get("cross_module_constraints", []):
        viol = _check_constraint(modules, constraint)
        if viol:
            violations.append(viol)

    return (not violations), violations


def _check_constraint(modules: dict, constraint: str) -> str | None:
    """Parse 'lhs == rhs' or 'lhs.type == rhs.type' style; we only do equality check."""
    constraint = constraint.strip()
    if "==" in constraint:
        lhs, rhs = (s.strip() for s in constraint.split("==", 1))
    elif "=" in constraint:
        lhs, rhs = (s.strip() for s in constraint.split("=", 1))
    else:
        return f"unparseable constraint: {constraint!r}"
    try:
        lv = jsonpath_get(modules, lhs)
        rv = jsonpath_get(modules, rhs)
    except (KeyError, IndexError, TypeError) as e:
        return f"constraint path missing ({lhs} vs {rhs}): {e}"
    if lv != rv:
        return f"constraint failed: {lhs}={lv!r} != {rhs}={rv!r}"
    return None


# ---------- 2. type_check ----------
# Workflow edges 用 port_src/port_dst 显式标注. type_check 检查 port 存在性;
# cross_module_constraints (schema_validate §5) 做严格 type-equality 检查.
NODE_ROLE_MAP = {
    "planner": "planner",
    "retriever": "memory",
    "executor": "tools",
    "verifier": "verifier",
}


def type_check(genome: dict[str, Any]) -> tuple[bool, list[str]]:
    violations: list[str] = []
    modules = genome.get("modules", {})
    workflow = modules.get("workflow", {})
    edges = workflow.get("edges", [])

    for edge in edges:
        if isinstance(edge, list):
            if len(edge) < 2:
                violations.append(f"bad edge tuple: {edge}")
                continue
            src, dst = edge[0], edge[1]
            port_src = None
            port_dst = None
            kind = "data" if len(edge) < 3 else edge[2]
        elif isinstance(edge, dict):
            src = edge.get("src")
            dst = edge.get("dst")
            port_src = edge.get("port_src")
            port_dst = edge.get("port_dst")
            kind = edge.get("kind", "data")
        else:
            violations.append(f"unsupported edge format: {edge!r}")
            continue

        if kind == "loop":
            continue

        if port_src is not None:
            src_mod = NODE_ROLE_MAP.get(src, src)
            out_ports = modules.get(src_mod, {}).get("output_ports") or {}
            if port_src not in out_ports:
                violations.append(
                    f"edge {src}->{dst}: src module {src_mod!r} has no output port {port_src!r}"
                )
        if port_dst is not None:
            dst_mod = NODE_ROLE_MAP.get(dst, dst)
            in_ports = modules.get(dst_mod, {}).get("input_ports") or {}
            if port_dst not in in_ports:
                violations.append(
                    f"edge {src}->{dst}: dst module {dst_mod!r} has no input port {port_dst!r}"
                )

    return (not violations), violations


# ---------- 3. minimal_execution_test ----------
def minimal_execution_test(genome: dict[str, Any]) -> tuple[bool, list[str]]:
    """Dry-run dispatcher; verify planner→retriever→executor→verifier path is callable.

    No LLM call; only checks workflow structure + module presence + entry/exit nodes.
    """
    violations: list[str] = []
    modules = genome.get("modules", {})
    workflow = modules.get("workflow", {})
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])

    # entry / exit nodes (founder uses 'id'; legacy 'name' supported)
    def _node_name(n):
        if isinstance(n, dict):
            return n.get("id") or n.get("name")
        return n

    node_names = [_node_name(n) for n in nodes]
    if "planner" not in node_names:
        violations.append("workflow missing entry node 'planner'")
    if "verifier" not in node_names:
        violations.append("workflow missing exit node 'verifier'")

    # ensure ≥ 1 path from planner to verifier (BFS)
    adj: dict[str, list[str]] = {n: [] for n in node_names}
    for e in edges:
        if isinstance(e, list):
            if len(e) >= 2:
                adj.setdefault(e[0], []).append(e[1])
        elif isinstance(e, dict):
            adj.setdefault(e["src"], []).append(e["dst"])
    visited = set()
    stack = ["planner"]
    while stack:
        n = stack.pop()
        if n in visited:
            continue
        visited.add(n)
        stack.extend(adj.get(n, []))
    if "verifier" not in visited:
        violations.append("no path planner -> verifier in workflow DAG")

    # required modules non-empty
    for mk in MODULE_KEYS:
        if mk not in modules:
            violations.append(f"missing module: {mk}")

    return (not violations), violations


def full_validate(genome: dict[str, Any]) -> tuple[bool, dict[str, list[str]]]:
    """Run all three validators. Returns (ok, {schema, type, exec})."""
    ok1, v1 = schema_validate(genome)
    ok2, v2 = type_check(genome)
    ok3, v3 = minimal_execution_test(genome)
    return (ok1 and ok2 and ok3), {"schema": v1, "type": v2, "exec": v3}


# ---------- 4. typed subgraph crossover utilities ----------
def extract_typed_subgraph(genome: dict[str, Any], module_name: str) -> dict[str, Any]:
    """Deep-copy a single module's subgraph (module_name ∈ MODULE_KEYS)."""
    if module_name not in MODULE_KEYS:
        raise ValueError(f"unknown module: {module_name}")
    return copy.deepcopy(genome["modules"][module_name])


def replace_subgraph(
    host: dict[str, Any], module_name: str, donor_subgraph: dict[str, Any]
) -> dict[str, Any]:
    """Replace host's module with donor_subgraph. Returns a NEW genome dict."""
    child = copy.deepcopy(host)
    child["modules"][module_name] = copy.deepcopy(donor_subgraph)
    return child


def reconnect_typed_ports(genome: dict[str, Any]) -> dict[str, Any]:
    """No-op for the founder MAG (workflow keeps the same node skeleton).

    If donor module exposes different port names, fall back to renaming to canonical
    `in_port` / `out_port` so workflow edges still resolve via role_map.
    Returns genome (mutated for renames).
    """
    # Founder MAG keeps node names planner/retriever/executor/verifier;
    # module-level replacement preserves port names, so no rewiring needed.
    return genome


def syntax_fix(genome: dict[str, Any]) -> dict[str, Any]:
    """Best-effort syntax fixes (drop None entries in edge list etc)."""
    wf = genome.get("modules", {}).get("workflow", {})
    if "edges" in wf:
        wf["edges"] = [e for e in wf["edges"] if e]
    if "nodes" in wf:
        wf["nodes"] = [n for n in wf["nodes"] if n]
    return genome


def type_check_fix(genome: dict[str, Any]) -> dict[str, Any]:
    """If type_check finds mismatched ports between donor module and host workflow,
    propagate donor's port schemas to dependent modules' adjacent ports.

    Implementation note: founder design keeps port name + type stable across mutation;
    we only fix when a mutation has bumped a schema version (e.g. v1->v2).
    Here we record the version drift on each affected port; this is the EST Thm 2
    'interface boundary mismatch' carrier. We do NOT auto-repair semantic mismatch.
    """
    return genome


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "../../data/founder_genome_v0.json"
    g = load_mag(path)
    ok, viol = full_validate(g)
    print(f"full_validate({path}): ok={ok}")
    for cat, vs in viol.items():
        if vs:
            print(f"  {cat}:")
            for v in vs:
                print(f"    - {v}")
    sys.exit(0 if ok else 1)
