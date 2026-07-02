"""Azure gpt-5.4-mini client wrapper with rate-limit backoff + token tracking.

仅供实验代码使用; 严禁配置进 agent system (per checklist §1.10).

Usage:
    from core.llm_client import LLMClient, BudgetExceeded
    client = LLMClient(budget_usd_hard_cap=500.0, tracker_path="experiments/budget_tracker.json")
    out = client.chat(messages=[{"role":"user","content":"hi"}], max_tokens=512)
    print(client.summary())
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

# --- Azure endpoint (per checklist §1.10) ---
AZURE_BASE_URL = "YOUR_AZURE_ENDPOINT"
AZURE_API_KEY = "YOUR_AZURE_API_KEY"
MODEL = "gpt-5.4-mini"

# --- Pricing (USD per 1M token, Azure published rates for gpt-5.4-mini class) ---
# 来源: niche_profiles.md §0 估算 + EXP_DESIGN.md §6 cost-estimate. 实际跑时第一批 call 会反查正确价。
PRICE_INPUT_PER_1M = 0.15
PRICE_OUTPUT_PER_1M = 0.60

# --- Hard caps (per EXP_DESIGN.md §10 GA.global) ---
DEFAULT_BUDGET_HARD_CAP = 500.0  # USD
DEFAULT_BUDGET_WARN_THRESHOLD = 400.0  # USD


class BudgetExceeded(RuntimeError):
    """Raised when accumulated USD spend exceeds hard cap. 自动停止所有 LLM call."""


@dataclass
class UsageRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_calls: int = 0
    total_failures: int = 0
    total_retries: int = 0
    total_usd: float = 0.0
    by_purpose: dict[str, dict[str, float]] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add(self, prompt: int, completion: int, purpose: str) -> float:
        cost = (prompt / 1_000_000) * PRICE_INPUT_PER_1M + (completion / 1_000_000) * PRICE_OUTPUT_PER_1M
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_calls += 1
        self.total_usd += cost
        bucket = self.by_purpose.setdefault(purpose, {"prompt": 0, "completion": 0, "calls": 0, "usd": 0.0})
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["calls"] += 1
        bucket["usd"] += cost
        self.last_updated = time.time()
        return cost


class LLMClient:
    """Thread-safe Azure gpt-5.4-mini client with retry + tracker.

    Args:
        budget_usd_hard_cap: 累计 USD 上限 (default 500). 超过 raise BudgetExceeded.
        tracker_path: JSON file 持久化 usage; 每次 chat 后增量写.
        purpose_tag: 默认 purpose tag (可在 chat call 覆盖).
        max_retries: rate-limit + transient 失败 retry 次数.
    """

    def __init__(
        self,
        budget_usd_hard_cap: float = DEFAULT_BUDGET_HARD_CAP,
        tracker_path: str | os.PathLike = "experiments/budget_tracker.json",
        purpose_tag: str = "default",
        max_retries: int = 5,
    ) -> None:
        self._client = OpenAI(base_url=AZURE_BASE_URL, api_key=AZURE_API_KEY)
        self._budget_cap = float(budget_usd_hard_cap)
        self._tracker_path = Path(tracker_path)
        self._tracker_path.parent.mkdir(parents=True, exist_ok=True)
        self._purpose_tag = purpose_tag
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._usage = self._load_tracker()

    # ---- tracker IO ----
    def _load_tracker(self) -> UsageRecord:
        if self._tracker_path.exists():
            try:
                raw = json.loads(self._tracker_path.read_text())
                return UsageRecord(**raw)
            except Exception:  # noqa: BLE001
                pass
        return UsageRecord()

    def _persist_tracker(self) -> None:
        tmp = self._tracker_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self._usage), indent=2))
        tmp.replace(self._tracker_path)

    # ---- accessors ----
    @property
    def total_usd(self) -> float:
        return self._usage.total_usd

    def summary(self) -> dict[str, Any]:
        return asdict(self._usage)

    def check_budget(self) -> None:
        if self._usage.total_usd >= self._budget_cap:
            raise BudgetExceeded(
                f"Hard cap ${self._budget_cap:.2f} exceeded; spent ${self._usage.total_usd:.2f}"
            )

    # ---- main API ----
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        purpose: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """One chat completion with retry + tracking.

        Returns dict {text, prompt_tokens, completion_tokens, cost_usd, raw}.
        Raises BudgetExceeded on over-budget; APIConnectionError / RateLimitError after max_retries.
        """
        self.check_budget()
        purpose = purpose or self._purpose_tag

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                # gpt-5.x family requires `max_completion_tokens` (not legacy `max_tokens`).
                call_kwargs = dict(extra)
                call_kwargs.setdefault("max_completion_tokens", max_tokens)
                # gpt-5.4-mini only supports default temperature; do not pass unless explicitly non-default
                if temperature != 0.0:
                    call_kwargs["temperature"] = temperature
                resp = self._client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    **call_kwargs,
                )
                text = resp.choices[0].message.content if resp.choices else ""
                usage = resp.usage
                p_tok = getattr(usage, "prompt_tokens", 0) or 0
                c_tok = getattr(usage, "completion_tokens", 0) or 0
                with self._lock:
                    cost = self._usage.add(p_tok, c_tok, purpose)
                    self._persist_tracker()
                return {
                    "text": text,
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "cost_usd": cost,
                    "attempt": attempt,
                }
            except (RateLimitError, APITimeoutError, APIConnectionError) as e:
                last_exc = e
                with self._lock:
                    self._usage.total_retries += 1
                # exponential backoff: 2, 4, 8, 16, 32 s, jitter ±25%
                base = 2 ** (attempt + 1)
                sleep_s = base * (0.75 + 0.5 * (hash((time.time(), attempt)) & 0xFFFF) / 0xFFFF)
                time.sleep(min(sleep_s, 60.0))
            except APIStatusError as e:
                # 4xx 不 retry (config error); 5xx retry
                if 500 <= e.status_code < 600 and attempt < self._max_retries:
                    last_exc = e
                    time.sleep(2 ** (attempt + 1))
                    continue
                with self._lock:
                    self._usage.total_failures += 1
                    self._persist_tracker()
                raise
            except Exception:  # noqa: BLE001
                with self._lock:
                    self._usage.total_failures += 1
                    self._persist_tracker()
                raise

        with self._lock:
            self._usage.total_failures += 1
            self._persist_tracker()
        assert last_exc is not None
        raise last_exc


if __name__ == "__main__":
    # M1 smoke test (per ROADMAP §M1 B3)
    import sys

    client = LLMClient(
        budget_usd_hard_cap=500.0,
        tracker_path=os.environ.get("LLM_TRACKER", "/tmp/agentspecies_llm_smoke.json"),
        purpose_tag="m1_smoke",
    )

    print("=== Azure gpt-5.4-mini smoke test (5 calls) ===")
    t0 = time.time()
    latencies = []
    for i in range(5):
        t_call = time.time()
        try:
            out = client.chat(
                messages=[
                    {"role": "system", "content": "You are a terse assistant."},
                    {"role": "user", "content": f"Say only OK#{i}. No other text."},
                ],
                max_tokens=20,
            )
            dt = time.time() - t_call
            latencies.append(dt)
            print(f"  call#{i}: {dt:.2f}s, p={out['prompt_tokens']} c={out['completion_tokens']} "
                  f"cost=${out['cost_usd']:.6f} text={out['text']!r}")
        except Exception as e:
            print(f"  call#{i}: FAIL {type(e).__name__}: {e}")
            sys.exit(1)

    avg = sum(latencies) / len(latencies)
    print(f"\nTotal: {time.time()-t0:.1f}s, avg latency {avg:.2f}s, "
          f"spent ${client.total_usd:.6f}")
    print("PASS" if avg < 8.0 else "WARN: avg latency > 8s")
