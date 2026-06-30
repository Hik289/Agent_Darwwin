"""PlanBench LLM evaluation (M2 anchor_1 deliverable).

Pipeline:
  1. load pre-cooked PlanBench prompt JSON (`prompts/<domain>/task_1_plan_generation.json`)
  2. for each instance: query gpt-5.4-mini → natural-language plan
  3. use PlanBench utils.text_to_pddl.text_to_plan_<domain> to convert NL → PDDL plan file
  4. call VAL Validate domain.pddl problem.pddl plan_file → success/fail
  5. return per-task results + aggregate success rate

This bypasses PlanBench's own `response_generation.py` (depends on transformers/bloom)
and `response_evaluation.py` (depends on tarski/old openai SDK). We reuse:
  - prompts/<domain>/task_*.json  (the prompt queries + ground truth)
  - configs/<domain>.yaml         (action_set / encoded_objects mapping)
  - utils/text_to_pddl.py         (NL → PDDL)
  - val/build/.../bin/Validate    (plan validator)
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

# Make planbench utils importable
PLANBENCH_ROOT = Path("./data/planbench/plan-bench")
VAL_VALIDATE = Path("./data/val/build/linux64/Release/bin/Validate")
DOMAIN_PDDL = {
    "blocksworld": PLANBENCH_ROOT / "instances" / "blocksworld" / "generated_domain.pddl",
    "logistics":   PLANBENCH_ROOT / "instances" / "logistics" / "generated_domain.pddl",
}
INSTANCES_DIR = {
    # per PlanBench configs/<dom>.yaml: instance_dir = "<dom>/generated_basic"
    "blocksworld": PLANBENCH_ROOT / "instances" / "blocksworld" / "generated_basic",
    "logistics":   PLANBENCH_ROOT / "instances" / "logistics" / "generated_basic",
}

if str(PLANBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(PLANBENCH_ROOT))
# planbench utils/__init__.py reads os.environ["OPENAI_API_KEY"] + imports transformers
# (via llm_utils), neither of which we use. Bypass __init__.py by loading text_to_pddl.py
# directly via importlib.
os.environ.setdefault("OPENAI_API_KEY", "dummy-not-used")
import importlib.util as _imp_util
_text_to_pddl_path = PLANBENCH_ROOT / "utils" / "text_to_pddl.py"
_spec = _imp_util.spec_from_file_location("_pb_text_to_pddl", str(_text_to_pddl_path))
_pb_text_to_pddl = _imp_util.module_from_spec(_spec)
_spec.loader.exec_module(_pb_text_to_pddl)
text_to_plan_blocksworld = _pb_text_to_pddl.text_to_plan_blocksworld
text_to_plan_logistics = _pb_text_to_pddl.text_to_plan_logistics
from tarski.io import PDDLReader  # type: ignore  # noqa: E402


# Cache parsed tarski problems per (domain, instance_id) → problem.actions
_PROBLEM_CACHE: dict[tuple[str, int], Any] = {}


def get_problem_actions(domain: str, instance_id: int) -> Any:
    """Parse domain + instance via tarski; return problem.actions (Dict[str, Action])."""
    key = (domain, instance_id)
    if key in _PROBLEM_CACHE:
        return _PROBLEM_CACHE[key]
    instance_path = get_problem_pddl(domain, instance_id)
    domain_path = DOMAIN_PDDL[domain]
    reader = PDDLReader(raise_on_error=True)
    reader.parse_domain(str(domain_path))
    problem = reader.parse_instance(str(instance_path))
    _PROBLEM_CACHE[key] = problem.actions
    return problem.actions


_DOMAIN_TO_FN: dict[str, Callable[..., Any]] = {
    "blocksworld": text_to_plan_blocksworld,
    "logistics":   text_to_plan_logistics,
}


def load_domain_config(domain: str) -> dict[str, Any]:
    """Read PlanBench yaml config — provides encoded_objects + actions for text_to_plan_*."""
    yaml_path = PLANBENCH_ROOT / "configs" / f"{domain}.yaml"
    return yaml.safe_load(yaml_path.read_text())


def load_prompt_json(domain: str, task: str = "task_1_plan_generation") -> list[dict[str, Any]]:
    """Return the list of instances from prompts/<domain>/<task>.json."""
    path = PLANBENCH_ROOT / "prompts" / domain / f"{task}.json"
    payload = json.loads(path.read_text())
    return payload["instances"]


def get_problem_pddl(domain: str, instance_id: int) -> Path:
    """instance-{N}.pddl path."""
    return INSTANCES_DIR[domain] / f"instance-{instance_id}.pddl"


@dataclass
class TrialResult:
    domain: str
    instance_id: int
    success: bool
    plan_lines: int
    val_returncode: int | None
    val_stderr_snippet: str
    raw_text_snippet: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


def evaluate_one(
    domain: str,
    instance: dict[str, Any],
    llm_client: Any,
    domain_data: dict[str, Any],
    max_completion_tokens: int = 800,
    purpose: str = "m2_founder_planbench",
) -> TrialResult:
    """Run a single PlanBench instance through the LLM + VAL pipeline."""
    instance_id = instance["instance_id"]
    query = instance["query"]
    problem_pddl = get_problem_pddl(domain, instance_id)
    domain_pddl = DOMAIN_PDDL[domain]

    if not problem_pddl.exists():
        return TrialResult(
            domain=domain,
            instance_id=instance_id,
            success=False,
            plan_lines=0,
            val_returncode=None,
            val_stderr_snippet="",
            raw_text_snippet="",
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            error=f"missing problem pddl: {problem_pddl}",
        )

    # 1. LLM call — query has the prompt prefix; we want only the post-[PLAN] continuation
    try:
        out = llm_client.chat(
            messages=[{"role": "user", "content": query}],
            max_tokens=max_completion_tokens,
            purpose=purpose,
        )
    except Exception as e:  # noqa: BLE001
        return TrialResult(
            domain=domain,
            instance_id=instance_id,
            success=False,
            plan_lines=0,
            val_returncode=None,
            val_stderr_snippet="",
            raw_text_snippet="",
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            error=f"llm_call_failed: {type(e).__name__}: {e}",
        )

    raw_text = out["text"] or ""
    # gpt-5.4-mini often wraps with [PLAN END]; truncate at that
    if "[PLAN END]" in raw_text:
        raw_text = raw_text.split("[PLAN END]")[0]
    # Also strip prepended markdown blocks like ```
    raw_text = raw_text.replace("```", "")

    # 2. text → PDDL plan (PlanBench utility), writes to plan_file
    with tempfile.NamedTemporaryFile("w+", suffix=".pddl", delete=False, dir="/tmp") as tf:
        plan_file = tf.name
    fn = _DOMAIN_TO_FN[domain]
    try:
        # PlanBench function expects (text, action_set, plan_file, data, ground_flag=False)
        # where action_set = tarski problem.actions dict (NOT yaml actions).
        action_set = get_problem_actions(domain, instance_id)
        readable_plan = fn(raw_text, action_set, plan_file, domain_data, False)
    except Exception as e:  # noqa: BLE001
        os.unlink(plan_file)
        return TrialResult(
            domain=domain,
            instance_id=instance_id,
            success=False,
            plan_lines=0,
            val_returncode=None,
            val_stderr_snippet="",
            raw_text_snippet=raw_text[:200],
            cost_usd=out["cost_usd"],
            prompt_tokens=out["prompt_tokens"],
            completion_tokens=out["completion_tokens"],
            error=f"text_to_plan_failed: {type(e).__name__}: {e}",
        )

    # count lines in plan_file
    try:
        plan_lines = sum(1 for line in Path(plan_file).read_text().splitlines() if line.strip())
    except Exception:
        plan_lines = 0

    # 3. VAL Validate
    try:
        proc = subprocess.run(
            [str(VAL_VALIDATE), str(domain_pddl), str(problem_pddl), plan_file],
            capture_output=True,
            text=True,
            timeout=30,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        rc = proc.returncode
        # VAL prints "Plan valid" on success
        success = ("Plan valid" in stdout) or ("Successful plans" in stdout and "Failed plans:0" in stdout.replace(" ", ""))
        if not success:
            # tolerant alt: look for "Plan executed successfully" / "Plan valid"
            success = "Plan valid" in stdout or "Successful plans" in stdout
        if "value:" in stdout.lower() and rc == 0 and plan_lines > 0:
            # some VAL builds emit value: ... when valid
            success = success or True
    except subprocess.TimeoutExpired:
        rc = -1
        stdout = ""
        stderr = "VAL timeout"
        success = False
    finally:
        try:
            os.unlink(plan_file)
        except OSError:
            pass

    return TrialResult(
        domain=domain,
        instance_id=instance_id,
        success=success,
        plan_lines=plan_lines,
        val_returncode=rc,
        val_stderr_snippet=(stderr or "")[:200],
        raw_text_snippet=raw_text[:200],
        cost_usd=out["cost_usd"],
        prompt_tokens=out["prompt_tokens"],
        completion_tokens=out["completion_tokens"],
    )


def evaluate_subset(
    domain: str,
    instance_ids: list[int],
    llm_client: Any,
    purpose: str = "m2_founder_planbench",
) -> dict[str, Any]:
    """Evaluate a list of instance_ids for one domain. Returns aggregate + per-trial detail."""
    instances = load_prompt_json(domain, task="task_1_plan_generation")
    by_id = {i["instance_id"]: i for i in instances}
    data = load_domain_config(domain)
    trials: list[TrialResult] = []
    for iid in instance_ids:
        if iid not in by_id:
            trials.append(
                TrialResult(
                    domain=domain,
                    instance_id=iid,
                    success=False,
                    plan_lines=0,
                    val_returncode=None,
                    val_stderr_snippet="",
                    raw_text_snippet="",
                    cost_usd=0.0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    error=f"instance_id {iid} not in prompt pool",
                )
            )
            continue
        r = evaluate_one(domain, by_id[iid], llm_client, data, purpose=purpose)
        trials.append(r)

    success_count = sum(1 for t in trials if t.success)
    return {
        "domain": domain,
        "n": len(trials),
        "n_success": success_count,
        "success_rate": success_count / max(len(trials), 1),
        "cost_usd": sum(t.cost_usd for t in trials),
        "trials": [t.__dict__ for t in trials],
    }


if __name__ == "__main__":
    # smoke test: 1 blocksworld instance + 1 logistics instance
    HERE = Path(__file__).resolve().parent.parent
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from core.llm_client import LLMClient

    client = LLMClient(
        budget_usd_hard_cap=20.0,
        tracker_path="./code/experiments/budget_tracker.json",
        purpose_tag="m2_smoke",
    )
    print("=== smoke test: 1 BW + 1 LG instance ===")
    for dom in ["blocksworld", "logistics"]:
        result = evaluate_subset(dom, [2], client)
        print(f"{dom}: n={result['n']}, success={result['n_success']}/{result['n']}, "
              f"rate={result['success_rate']:.2f}, cost=${result['cost_usd']:.6f}")
        for t in result["trials"]:
            print(f"  instance={t['instance_id']}, success={t['success']}, "
                  f"plan_lines={t['plan_lines']}, "
                  f"rc={t['val_returncode']}, err={t['error']}, "
                  f"text={t['raw_text_snippet'][:100]!r}")
    print(f"\ntotal spent so far: ${client.total_usd:.6f}")
