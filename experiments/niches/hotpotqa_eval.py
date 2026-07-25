"""HotpotQA distractor niche evaluator (E_tool surrogate)."""
from __future__ import annotations

import ast
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from datasets import load_dataset
import sys as _sys; import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _os.path.dirname(_HERE) not in _sys.path: _sys.path.insert(0, _os.path.dirname(_HERE))
try:
    from core import saet as _saet
except Exception:
    _saet = None


_HQA_POOL = None


def _load_pool(n=1000, seed=42, max_context_chars=5000, config="distractor"):
    ds = load_dataset("hotpotqa/hotpot_qa", config, split="validation")
    rng = random.Random(seed)
    idx = list(range(len(ds)))
    rng.shuffle(idx)
    out = []
    for i in idx:
        item = ds[i]
        context = item.get("context")
        if isinstance(context, str):
            try:
                context = ast.literal_eval(context)
            except Exception:
                context = None
        paragraphs = []
        if isinstance(context, dict) and "title" in context and "sentences" in context:
            for t, ss in zip(context["title"], context["sentences"]):
                body = " ".join(ss) if isinstance(ss, list) else str(ss)
                paragraphs.append(f"[{t}] {body}")
        elif isinstance(context, list):
            for entry in context:
                if isinstance(entry, dict):
                    paragraphs.append(f"[{entry.get('title','?')}] " + " ".join(entry.get('sentences', []) or []))
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    body = " ".join(entry[1]) if isinstance(entry[1], list) else str(entry[1])
                    paragraphs.append(f"[{entry[0]}] {body}")
        flat = "\n\n".join(paragraphs)
        if len(flat) > max_context_chars:
            flat = flat[:max_context_chars] + "...[truncated]"
        out.append({
            "id": item.get("id", str(i)),
            "question": item["question"],
            "answer": item["answer"],
            "level": item.get("level"),
            "type": item.get("type"),
            "context": flat,
        })
        if len(out) >= n:
            break
    return out


def sample_hotpotqa_subset(n=100, seed=42, max_context_chars=5000, config="distractor"):
    global _HQA_POOL
    if _HQA_POOL is None or len(_HQA_POOL) < n:
        _HQA_POOL = _load_pool(n=max(n, 1000), seed=seed, max_context_chars=max_context_chars, config=config)
    return _HQA_POOL[:n]


@dataclass
class HQATrial:
    qid: str
    question: str
    gold_answer: str
    level: str
    pred_answer: str
    success: bool
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    n_samples: int
    error: str | None = None


def _normalize(s):
    s = (s or "").lower().strip()
    s = re.sub(r"^(the |a |an )", "", s)
    s = re.sub(r"[\.,;:!?\"'()]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_match(pred, gold):
    p = _normalize(pred)
    g = _normalize(gold)
    if not g or not p:
        return False
    if p == g:
        return True
    if g in p or p in g:
        return True
    g_tokens = set(g.split())
    if 0 < len(g_tokens) <= 3:
        p_tokens = set(p.split())
        return g_tokens.issubset(p_tokens)
    return False


def evaluate_one(item, llm_client, genome=None, purpose="hotpotqa", mismatch_mode="hard"):
    # Apply the E1 strict all-edge check to hybrids in rigid mode.
    if genome and _saet is not None and mismatch_mode == "rigid" and _saet.is_hybrid(genome):
        ok_strict, fail_reason = _saet.check_strict_interface(genome)
        if not ok_strict:
            return HQATrial(
                qid=str(item["id"]),
                question=item["question"][:200],
                gold_answer=item["answer"][:200],
                level=item.get("level", ""),
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
            return HQATrial(
                qid=str(item["id"]),
                question=item["question"][:200],
                gold_answer=item["answer"][:200],
                level=item.get("level", ""),
                pred_answer="",
                success=False,
                cost_usd=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                n_samples=0,
                error="TYPE_MISMATCH " + " | ".join(m_reasons),
            )
        if m_count > 0 and mismatch_mode in ("soft", "rigid"):
            genome["_type_mismatch_count"] = m_count
            genome["_type_mismatch_reasons"] = m_reasons

    n_samples = 1
    if genome:
        v = genome["modules"]["verifier"]
        n_samples = int(v.get("samples", 1))

    system = (
        "You are an agent answering multi-hop questions. You receive several passages "
        "as context (similar to tool/retrieval output). Read all passages, then answer the "
        "question with the shortest correct answer (a name, date, number, or short phrase). "
        "Respond with ONLY the final answer — no explanation, no prefix."
    )
    user = f"Passages:\n{item['context']}\n\nQuestion: {item['question']}\nAnswer:"

    samples = []
    total_cost = 0.0
    total_p = 0
    total_c = 0
    last_err = None

    for _ in range(n_samples):
        try:
            out = llm_client.chat(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=200,
                purpose=purpose,
            )
            samples.append((out["text"] or "").strip())
            total_cost += out["cost_usd"]
            total_p += out["prompt_tokens"]
            total_c += out["completion_tokens"]
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            break

    if samples:
        normed = [_normalize(s) for s in samples]
        winner = Counter(normed).most_common(1)[0][0]
        chosen = next(s for s in samples if _normalize(s) == winner)
    else:
        chosen = ""

    success = _is_match(chosen, item["answer"])
    return HQATrial(
        qid=str(item["id"]),
        question=item["question"][:200],
        gold_answer=item["answer"][:200],
        level=item.get("level", ""),
        pred_answer=chosen[:200],
        success=success,
        cost_usd=total_cost,
        prompt_tokens=total_p,
        completion_tokens=total_c,
        n_samples=len(samples),
        error=last_err,
    )


def smoke_test():
    pool = sample_hotpotqa_subset(n=3, seed=42)
    print(f"loaded {len(pool)} items")
    for it in pool:
        print(f"  id={it['id']} level={it['level']}")
        print(f"    Q: {it['question']}")
        print(f"    A (gold): {it['answer']}")
        print(f"    context preview: {it['context'][:150]}...")
        print()


if __name__ == "__main__":
    smoke_test()
