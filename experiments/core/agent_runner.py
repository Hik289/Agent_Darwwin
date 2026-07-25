"""Founder MAG → runnable agent on PlanBench.

Honors the founder genome v0 settings:
  - planner.family = plan_execute
  - planner.depth = 4
  - planner.replan_on_failure = True
  - planner.decomposition_style = hierarchical
  - verifier.family = self_consistency
  - verifier.samples = 3
  - verifier.voting = majority
  - verifier.stopping_rule.max_total_steps = 12

For PlanBench (single-shot plan generation, no iterative env), the relevant knobs are:
  - self_consistency: sample N=verifier.samples plans, vote majority (or any-valid)
  - replan_on_failure: if best plan VAL-fails, attempt up to `depth-1` re-plans with
    a follow-up message explaining the failure
  - max_total_steps caps total LLM calls per task
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


SYSTEM_PROMPT_DEFAULT = (
    "You are a PDDL planner. The user gives a planning problem in PlanBench format "
    "ending with '[PLAN]'. Output ONLY the action sequence (one natural-language verb "
    "phrase per line) followed by '[PLAN END]'. Do NOT number, do NOT comment, do NOT "
    "explain. Match the action vocabulary used in the one-shot example earlier in the "
    "user message."
)


@dataclass
class AgentTrial:
    instance_id: int
    domain: str
    success: bool
    n_samples: int            # self_consistency samples actually issued
    n_replans: int            # replan attempts used
    final_plan_pddl: str
    final_plan_lines: int
    val_stdout_snippet: str
    val_returncode: int | None
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None
    chosen_strategy: str = ""  # "self_consistency_any_valid" / "majority" / "replan"


def _normalize_plan_text(text: str) -> str:
    text = text or ""
    if "[PLAN END]" in text:
        text = text.split("[PLAN END]")[0]
    text = text.replace("```", "")
    # strip leading "[PLAN]" if model echoed it
    if "[PLAN]" in text:
        text = text.split("[PLAN]", 1)[-1]
    return text.strip()


def _validate(domain_pddl: Path, problem_pddl: Path, plan_file: Path, val_bin: Path, timeout: int = 30):
    proc = subprocess.run(
        [str(val_bin), str(domain_pddl), str(problem_pddl), str(plan_file)],
        capture_output=True, text=True, timeout=timeout,
    )
    ok = "Plan valid" in proc.stdout
    return ok, proc.stdout, proc.returncode


def run_founder_on_instance(
    genome: dict[str, Any],
    domain: str,
    instance_id: int,
    instance_payload: dict[str, Any],
    llm_client: Any,
    domain_data: dict[str, Any],
    action_set: Any,
    text_to_plan_fn: Callable[..., Any],
    domain_pddl: Path,
    problem_pddl: Path,
    val_bin: Path,
    purpose: str = "m2_founder",
    mismatch_mode: str = "hard",
) -> AgentTrial:
    """Execute one PlanBench instance using the agent defined by genome (MAG).

    Self-consistency: sample N=verifier.samples plans (parallel single-call calls
    since gpt-5.4-mini does not support n>1 or temperature). We approximate by
    sampling N independent calls; choose the FIRST one that validates (any_valid),
    falling back to majority-vote (same PDDL text) when no single one validates.

    Replan-on-failure: if all N samples fail VAL, try up to (planner.depth - 1)
    additional rounds with a corrective system follow-up. Capped by
    verifier.stopping_rule.max_total_steps total LLM calls.
    """
    modules = genome["modules"]

    # E1: strict all-edge check for cross-lineage hybrids.
    # mode="rigid": if agent is cross-lineage hybrid (lineage_id contains '+'),
    # check ALL adjacent module pair input/output types. Any mismatch → fail.
    # Same-lineage agents bypass strict check (fast path).
    if mismatch_mode == "rigid":
        from core import saet as _saet_mod
        if _saet_mod.is_hybrid(genome):
            ok_strict, fail_reason = _saet_mod.check_strict_interface(genome)
            if not ok_strict:
                return AgentTrial(
                    instance_id=instance_id,
                    domain=domain,
                    success=False,
                    n_samples=0,
                    n_replans=0,
                    final_plan_pddl="",
                    final_plan_lines=0,
                    val_stdout_snippet="",
                    val_returncode=None,
                    cost_usd=0.0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    error=f"E1_STRICT_HYBRID_FAIL {fail_reason}",
                    chosen_strategy="e1_strict_hybrid_killed",
                )

    # H_diag_7 rigid-interface check.
    # mode="hard": Type-mismatch → q=0 skip (v4)
    # mode="soft": Type-mismatch → continue with LLM, count mismatches; caller applies penalty (v5)
    # mode="rigid": E1 above already handled hybrids; here keep soft semantics for non-hybrid
    RIGID_EDGES = [
        ("planner", "workflow"),
        ("verifier", "communication"),
        ("verifier", "update_policy"),
    ]
    mismatch_count = 0
    mismatch_reasons = []
    for src, dst in RIGID_EDGES:
        s_out = modules.get(src, {}).get("output_type")
        d_in = modules.get(dst, {}).get("input_type")
        if s_out is not None and d_in is not None and s_out != d_in:
            mismatch_count += 1
            mismatch_reasons.append(f"{src}.{s_out}->{dst}.{d_in}")
    if mismatch_count > 0:
        if mismatch_mode == "hard":
            return AgentTrial(
                instance_id=instance_id,
                domain=domain,
                success=False,
                n_samples=0,
                n_replans=0,
                final_plan_pddl="",
                final_plan_lines=0,
                val_stdout_snippet="",
                val_returncode=None,
                cost_usd=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                error=f"TYPE_MISMATCH " + " | ".join(mismatch_reasons),
                chosen_strategy="rigid_type_mismatch_skipped",
            )
        # soft mode: record on genome, continue execution
        genome["_type_mismatch_count"] = mismatch_count
        genome["_type_mismatch_reasons"] = mismatch_reasons

    planner = modules["planner"]
    verifier = modules["verifier"]
    n_samples = int(verifier.get("samples", 1))
    replan_on_failure = bool(planner.get("replan_on_failure", False))
    max_replans = max(int(planner.get("depth", 1)) - 1, 0)
    max_total_steps = int((verifier.get("stopping_rule") or {}).get("max_total_steps", n_samples + max_replans + 1))

    user_msg = instance_payload["query"]
    base_msgs = [
        {"role": "system", "content": SYSTEM_PROMPT_DEFAULT},
        {"role": "user", "content": user_msg},
    ]

    total_calls = 0
    total_cost = 0.0
    total_p = 0
    total_c = 0
    last_error = None

    def _call(msgs):
        nonlocal total_calls, total_cost, total_p, total_c
        out = llm_client.chat(messages=msgs, max_tokens=2000, purpose=purpose)
        total_calls += 1
        total_cost += out["cost_usd"]
        total_p += out["prompt_tokens"]
        total_c += out["completion_tokens"]
        return out

    def _try_plan(text: str):
        text = _normalize_plan_text(text)
        with tempfile.NamedTemporaryFile("w", suffix=".pddl", delete=False, dir="/tmp") as tf:
            plan_file = Path(tf.name)
        try:
            pddl_plan, _ = text_to_plan_fn(text, action_set, str(plan_file), domain_data, False)
        except Exception as e:
            try:
                plan_file.unlink()
            except OSError:
                pass
            return None, "", -1, f"text_to_plan_error: {type(e).__name__}: {e}"
        try:
            ok, stdout, rc = _validate(domain_pddl, problem_pddl, plan_file, val_bin)
        finally:
            try:
                plan_file.unlink()
            except OSError:
                pass
        return ok, pddl_plan, rc, stdout

    # ---- Stage 1: self_consistency sampling ----
    samples: list[tuple[bool, str, int, str]] = []  # (ok, pddl, rc, stdout)
    for _ in range(min(n_samples, max_total_steps)):
        try:
            out = _call(base_msgs)
        except Exception as e:  # noqa: BLE001
            last_error = f"llm_failed: {type(e).__name__}: {e}"
            break
        result = _try_plan(out["text"])
        samples.append(result)
        if result[0]:  # ok == True
            return AgentTrial(
                instance_id=instance_id, domain=domain, success=True,
                n_samples=len(samples), n_replans=0,
                final_plan_pddl=result[1], final_plan_lines=len([l for l in result[1].splitlines() if l.strip()]),
                val_stdout_snippet=(result[3] or "")[:200] if isinstance(result[3], str) else "",
                val_returncode=result[2],
                cost_usd=total_cost, prompt_tokens=total_p, completion_tokens=total_c,
                chosen_strategy="self_consistency_any_valid",
            )
    if total_calls >= max_total_steps:
        # no more budget
        best = samples[0] if samples else (False, "", -1, "")
        return AgentTrial(
            instance_id=instance_id, domain=domain, success=False,
            n_samples=len(samples), n_replans=0,
            final_plan_pddl=best[1] if isinstance(best[1], str) else "",
            final_plan_lines=0,
            val_stdout_snippet=(best[3] or "")[:200] if isinstance(best[3], str) else "",
            val_returncode=best[2] if isinstance(best[2], int) else None,
            cost_usd=total_cost, prompt_tokens=total_p, completion_tokens=total_c,
            error=last_error or "max_total_steps_hit_no_valid",
            chosen_strategy="max_steps_no_valid",
        )

    # ---- Stage 2: majority-vote among samples (if multiple identical pddl found) ----
    if samples and not any(s[0] for s in samples):
        # majority among PDDL strings
        pddl_counts = Counter(s[1] for s in samples if isinstance(s[1], str))
        majority_pddl, _ = pddl_counts.most_common(1)[0]
        # try VAL on this (cheap, no LLM call)
        if majority_pddl:
            with tempfile.NamedTemporaryFile("w", suffix=".pddl", delete=False, dir="/tmp") as tf:
                pf = Path(tf.name)
                pf.write_text(majority_pddl)
            try:
                ok, stdout, rc = _validate(domain_pddl, problem_pddl, pf, val_bin)
            finally:
                pf.unlink(missing_ok=True)
            if ok:
                return AgentTrial(
                    instance_id=instance_id, domain=domain, success=True,
                    n_samples=len(samples), n_replans=0,
                    final_plan_pddl=majority_pddl,
                    final_plan_lines=len([l for l in majority_pddl.splitlines() if l.strip()]),
                    val_stdout_snippet=stdout[:200], val_returncode=rc,
                    cost_usd=total_cost, prompt_tokens=total_p, completion_tokens=total_c,
                    chosen_strategy="majority_vote_valid",
                )

    # ---- Stage 3: replan_on_failure ----
    n_replans = 0
    if replan_on_failure:
        # construct follow-up with the failure stdout snippet (corrective hint)
        feedback_msgs = list(base_msgs)
        for replan_i in range(max_replans):
            if total_calls >= max_total_steps:
                break
            # last failure description
            last = samples[-1] if samples else (False, "", -1, "no prior plan")
            fail_hint = (last[3] or "")[:300] if isinstance(last[3], str) else "previous plan invalid"
            feedback_msgs.append({"role": "assistant", "content": (last[1] if isinstance(last[1], str) else "") + "\n[PLAN END]"})
            feedback_msgs.append({
                "role": "user",
                "content": f"That plan failed VAL with:\n{fail_hint}\n\nProvide a corrected plan in the same format. End with [PLAN END]."
            })
            try:
                out = _call(feedback_msgs)
            except Exception as e:  # noqa: BLE001
                last_error = f"replan_llm_failed: {type(e).__name__}: {e}"
                break
            n_replans += 1
            result = _try_plan(out["text"])
            samples.append(result)
            if result[0]:
                return AgentTrial(
                    instance_id=instance_id, domain=domain, success=True,
                    n_samples=n_samples, n_replans=n_replans,
                    final_plan_pddl=result[1],
                    final_plan_lines=len([l for l in result[1].splitlines() if l.strip()]),
                    val_stdout_snippet=(result[3] or "")[:200] if isinstance(result[3], str) else "",
                    val_returncode=result[2],
                    cost_usd=total_cost, prompt_tokens=total_p, completion_tokens=total_c,
                    chosen_strategy="replan",
                )

    # All strategies failed
    best = samples[-1] if samples else (False, "", -1, "")
    return AgentTrial(
        instance_id=instance_id, domain=domain, success=False,
        n_samples=n_samples, n_replans=n_replans,
        final_plan_pddl=best[1] if isinstance(best[1], str) else "",
        final_plan_lines=len([l for l in best[1].splitlines() if l.strip()]) if isinstance(best[1], str) else 0,
        val_stdout_snippet=(best[3] or "")[:200] if isinstance(best[3], str) else "",
        val_returncode=best[2] if isinstance(best[2], int) else None,
        cost_usd=total_cost, prompt_tokens=total_p, completion_tokens=total_c,
        error=last_error,
        chosen_strategy="all_failed",
    )
