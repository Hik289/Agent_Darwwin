"""LoCoMo niche evaluator (skeleton — M1 deliverable).

Data source: snap-research/locomo (cloned to /data1/.../locomo/snap_locomo/data/locomo10.json).
- 10 long-form conversations
- 1986 total QA pairs across 5 categories
- Categories (per LoCoMo paper § 3.2):
    1 = single-hop  (basic memory retrieval)
    2 = multi-hop   (跨多个 turn 推理)
    3 = temporal    (event ordering)
    4 = open-domain (long context QA)
    5 = adversarial (干扰 / negation)
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

LOCOMO_JSON = Path("./data/locomo/snap_locomo/data/locomo10.json")

CATEGORY_NAME = {
    1: "single_hop",
    2: "multi_hop",
    3: "temporal",
    4: "open_domain",
    5: "adversarial",
}


def env_ready() -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not LOCOMO_JSON.exists():
        issues.append(f"LoCoMo data missing: {LOCOMO_JSON}")
    return (not issues), issues


def load_locomo() -> list[dict[str, Any]]:
    return json.loads(LOCOMO_JSON.read_text())


def collect_qa_pool(min_per_cat: int = 30) -> dict[str, list[dict[str, Any]]]:
    """Collect (question, answer, evidence, conversation_id, conversation) tuples grouped by category name."""
    data = load_locomo()
    pool: dict[str, list[dict[str, Any]]] = {v: [] for v in CATEGORY_NAME.values()}
    for conv in data:
        cid = conv.get("sample_id")
        conv_payload = conv.get("conversation")
        for q in conv.get("qa", []):
            cat = CATEGORY_NAME.get(q.get("category"))
            if cat is None:
                continue
            # category 5 (adversarial) stores gold as `adversarial_answer`
            ans = q.get("answer", q.get("adversarial_answer"))
            if ans is None:
                continue
            pool[cat].append({
                "conversation_id": cid,
                "question": q["question"],
                "answer": ans,
                "evidence": q.get("evidence"),
                "category": cat,
            })
    return pool


# Per niche_profiles.md §5.5 — main subset (100 tasks total)
MAIN_SUBSET_SPEC = {
    "single_hop": 30,
    "multi_hop": 30,
    "temporal": 20,
    "open_domain": 10,
    "adversarial": 10,
}


def sample_main_subset(seed: int = 42) -> list[dict[str, Any]]:
    pool = collect_qa_pool()
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for cat, k in MAIN_SUBSET_SPEC.items():
        bucket = pool.get(cat, [])
        if len(bucket) >= k:
            out.extend(rng.sample(bucket, k))
        else:
            out.extend(bucket)
    rng.shuffle(out)
    return out


def smoke_test() -> int:
    print("=== LoCoMo niche smoke test ===")
    ok, issues = env_ready()
    print(f"env_ready: {ok}")
    for i in issues:
        print(f"  - {i}")
    if not ok:
        return 1
    pool = collect_qa_pool()
    for cat in CATEGORY_NAME.values():
        print(f"  pool[{cat}]: {len(pool[cat])} QA")
    sub = sample_main_subset(seed=42)
    print(f"main subset size: {len(sub)} (expected {sum(MAIN_SUBSET_SPEC.values())})")
    print(f"sample QA[0]: question={sub[0]['question']!r}, answer={sub[0]['answer']!r}, cat={sub[0]['category']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(smoke_test())
