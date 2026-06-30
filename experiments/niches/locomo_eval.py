"""LoCoMo niche LLM evaluation (M2 sanity check + later main exp).

Pipeline:
  1. load conversation (turns / sessions) + question + gold answer from
     ./data/locomo/snap_locomo/data/locomo10.json
  2. format the prompt: full-conversation context + question
  3. query gpt-5.4-mini → answer
  4. judge correctness:
     - exact-match (case-insensitive substring) for cat=1,2,3 (factual)
     - LLM-judge for cat=4 (open-domain) — for M2 we skip and treat 0/1 as substring
     - cat=5 (adversarial): correct = answer explicitly says "no answer / not in conversation"
  5. return per-task results

Founder MAG honors:
  - memory.write_policy = verified_only
  - memory.retrieval = hybrid (bm25 + embedding) — but we just feed full conv context here
  - verifier.samples = 3 (self_consistency) — for QA, sample N answers, vote majority
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# H_diag_7 rigid interface check import (shared utility)
import sys as _sys
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in _sys.path:
    _sys.path.insert(0, os.path.dirname(_HERE))
try:
    from core import saet as _saet
except Exception:
    _saet = None

LOCOMO_JSON = Path("./data/locomo/snap_locomo/data/locomo10.json")

CAT_NAME = {
    1: "single_hop", 2: "multi_hop", 3: "temporal",
    4: "open_domain", 5: "adversarial",
}


def load_locomo() -> list[dict[str, Any]]:
    return json.loads(LOCOMO_JSON.read_text())


def serialize_conversation(conv_payload: dict[str, Any], max_chars: int = 60_000) -> str:
    """Flatten conversation into LLM-friendly text. Truncate to fit context."""
    parts: list[str] = []
    # iterate by session_<num> keys in chronological order
    for key in sorted(conv_payload.keys()):
        if not key.startswith("session_"):
            continue
        if "date_time" in key or "summary" in key:
            continue
        turns = conv_payload[key]
        if not isinstance(turns, list):
            continue
        date_key = f"{key}_date_time"
        if date_key in conv_payload:
            parts.append(f"\n--- {key} ({conv_payload[date_key]}) ---")
        else:
            parts.append(f"\n--- {key} ---")
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            spk = turn.get("speaker", "?")
            txt = turn.get("text", "")
            parts.append(f"{spk}: {txt}")
    text = "\n".join(parts)
    if len(text) > max_chars:
        # keep tail (more recent turns more relevant)
        text = "...[truncated]...\n" + text[-max_chars:]
    return text


@dataclass
class LocomoTrial:
    conversation_id: str
    question: str
    gold_answer: str
    category: int
    pred_answer: str
    success: bool
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    n_samples: int
    error: str | None = None


def _normalize(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[\s\.,;:!?]+", " ", s)
    return s


def _is_match(pred: str, gold: str | int | float | None, category: int) -> bool:
    if gold is None:
        return False
    gold_str = str(gold)
    p = _normalize(pred)
    g = _normalize(gold_str)
    if not g:
        return False
    # Fix (Director 2026-06-27 13:08 UTC): reject empty prediction explicitly.
    # Without this, "" in any string == True, causing silent false-success when
    # LLM calls fail silently (e.g. BudgetExceeded caught by upstream wrapper).
    if not p:
        return False
    if category == 5:
        # adversarial: gold often "Not mentioned" / "Cannot be determined"
        # accept any of these phrases or a substring of gold in pred
        keys = ["not mentioned", "cannot", "no information", "not available", "unknown"]
        if any(k in p for k in keys):
            return True
        return g in p or p in g
    # factual: substring match in either direction
    if g in p or p in g:
        return True
    # tokens overlap heuristic for short answers
    g_tokens = set(g.split())
    if g_tokens and len(g_tokens) <= 4:
        p_tokens = set(p.split())
        return g_tokens.issubset(p_tokens)
    return False


def evaluate_one(
    conv_payload: dict[str, Any],
    question: str,
    gold_answer: str,
    category: int,
    conversation_id: str,
    llm_client: Any,
    genome: dict[str, Any] | None = None,
    purpose: str = "m2_locomo",
    mismatch_mode: str = "hard",
) -> LocomoTrial:
    """Run one LoCoMo QA. If genome provided, use verifier.samples self-consistency.

    mismatch_mode='hard' (v4): TYPE_MISMATCH → q=0 skip
    mismatch_mode='soft' (v5): TYPE_MISMATCH → continue, mark genome for caller penalty
    """
    # E1 strict-all-edge check for hybrids (mismatch_mode='rigid', Director 2026-06-26)
    if genome and _saet is not None and mismatch_mode == "rigid" and _saet.is_hybrid(genome):
        ok_strict, fail_reason = _saet.check_strict_interface(genome)
        if not ok_strict:
            return LocomoTrial(
                conversation_id=conversation_id,
                question=question[:200],
                gold_answer=str(gold_answer)[:200],
                category=category,
                pred_answer="",
                success=False,
                cost_usd=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                n_samples=0,
                error=f"E1_STRICT_HYBRID_FAIL {fail_reason}",
            )
    # H_diag_7 rigid interface check (3 edges only)
    if genome and _saet is not None:
        m_count, m_reasons = _saet.count_rigid_mismatches(genome)
        if m_count > 0 and mismatch_mode == "hard":
            return LocomoTrial(
                conversation_id=conversation_id,
                question=question[:200],
                gold_answer=str(gold_answer)[:200],
                category=category,
                pred_answer="",
                success=False,
                cost_usd=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                n_samples=0,
                error="TYPE_MISMATCH " + " | ".join(m_reasons),
            )
        if m_count > 0 and mismatch_mode in ("soft", "rigid"):
            # mark genome; caller (niche evaluator) applies penalty
            genome["_type_mismatch_count"] = m_count
            genome["_type_mismatch_reasons"] = m_reasons

    n_samples = 1
    if genome:
        v = genome["modules"]["verifier"]
        n_samples = int(v.get("samples", 1))

    conv_text = serialize_conversation(conv_payload)
    system = (
        "You are a helpful assistant answering questions about a long conversation. "
        "Read the entire conversation context, then answer the question as concisely "
        "as possible. If the answer is a date, give the date. If the answer is a name, "
        "give the name only. If the conversation does not contain enough information, "
        "say 'Not mentioned in the conversation.'"
    )
    user = f"Conversation:\n{conv_text}\n\nQuestion: {question}\nAnswer:"

    samples: list[str] = []
    total_cost = 0.0
    total_p = 0
    total_c = 0
    last_error = None
    for _ in range(n_samples):
        try:
            out = llm_client.chat(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=400,
                purpose=purpose,
            )
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
            break
        samples.append((out["text"] or "").strip())
        total_cost += out["cost_usd"]
        total_p += out["prompt_tokens"]
        total_c += out["completion_tokens"]

    # majority vote on normalized answers
    if samples:
        norm_counts = Counter(_normalize(s) for s in samples)
        winner_norm, _ = norm_counts.most_common(1)[0]
        # pick first sample whose normalized form == winner
        chosen = next(s for s in samples if _normalize(s) == winner_norm)
    else:
        chosen = ""

    success = _is_match(chosen, gold_answer, category)
    return LocomoTrial(
        conversation_id=conversation_id,
        question=question[:200],
        gold_answer=str(gold_answer)[:200],
        category=category,
        pred_answer=chosen[:200],
        success=success,
        cost_usd=total_cost,
        prompt_tokens=total_p,
        completion_tokens=total_c,
        n_samples=len(samples),
        error=last_error,
    )


def sample_locomo_subset(n: int = 50, seed: int = 42) -> list[dict[str, Any]]:
    """Sample n QA pairs from LoCoMo, stratified by category roughly per main_subset_spec.

    Format: each entry has {conv_payload, question, gold_answer, category, conversation_id}.
    """
    import random
    rng = random.Random(seed)
    data = load_locomo()
    by_cat: dict[int, list[tuple[dict, dict, str]]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    for conv in data:
        cid = conv.get("sample_id")
        conv_payload = conv.get("conversation", {})
        for q in conv.get("qa", []):
            cat = q.get("category")
            ans = q.get("answer", q.get("adversarial_answer"))
            if ans is None or cat not in by_cat:
                continue
            by_cat[cat].append((conv_payload, q, cid))

    # spec for 50: 30% / 30% / 20% / 10% / 10%
    target_per_cat = {1: max(int(0.3 * n), 1), 2: max(int(0.3 * n), 1),
                      3: max(int(0.2 * n), 1), 4: max(int(0.1 * n), 1), 5: max(int(0.1 * n), 1)}
    out: list[dict[str, Any]] = []
    for cat, target_k in target_per_cat.items():
        bucket = by_cat[cat]
        if not bucket:
            continue
        k = min(target_k, len(bucket))
        picks = rng.sample(bucket, k)
        for conv_payload, q, cid in picks:
            out.append({
                "conv_payload": conv_payload,
                "question": q["question"],
                "gold_answer": q.get("answer", q.get("adversarial_answer")),
                "category": q["category"],
                "conversation_id": cid,
            })
    rng.shuffle(out)
    return out[:n]
