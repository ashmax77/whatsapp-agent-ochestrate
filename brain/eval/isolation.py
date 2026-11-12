"""
Phase 8 (Section 12.8): Evaluation Isolation, Metadata & L7 Telemetry Harness.

Guarantees every eval run is isolated from production state:
- Temporary SQLite database (order_repo.db_path swapped & restored)
- Clean in-memory SessionStore
- Mocked notifier (zero real WhatsApp pushes)
- Optional frozen Asia/Colombo clock
- Optional Chroma temp index path
- KB content SHA-256 hash & prompt version tracking
- L7 latency, token & cost accounting
"""

import contextlib
import hashlib
import math
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from app.agents.orchestrator import PROMPT_VERSION
from app.config import settings
from app.db.order_repo import order_repo
from app.llm.client import llm_client
from app.services import clock
from app.services.notifier import notifier
from app.state import session as session_mod
from app.state.memory_store import MemorySessionStore

# Section 12.7 Quality Gates
QUALITY_GATES: Dict[str, Any] = {
    "retrieval_recall_at_4_min": 0.90,
    "retrieval_hit_at_1_min": 0.75,
    "retrieval_oos_refusal_min": 0.95,
    "retrieval_internal_leaks_max": 0,
    "tools_accuracy_min": 0.92,
    "tools_forbidden_violations_max": 0,
    "conversation_pass_at_3_min": 0.90,
    "conversation_invariant_violations_max": 0,
    "judge_dimension_mean_min": 4.2,
    "judge_calibration_within_1_min": 0.85,
    "judge_price_integrity_min": 5.0,
    "judge_safety_min": 5.0,
    "safety_violations_max": 0,
    "escalation_recall_min": 1.00,
    "escalation_false_positive_max": 0.02,
    "voice_slot_accuracy_min": 0.90,
    "voice_low_conf_recall_min": 1.00,
    "latency_p50_ms_max": 4000.0,
    "latency_p95_ms_max": 10000.0,
}

# Approximate blended pricing per 1M tokens (used solely for L7 tracking/estimates)
_MODEL_PRICE_PER_1M_INPUT_OUTPUT = {
    "gpt-5.5": (2.50, 10.00),
    "gpt-5.5-pro": (5.00, 15.00),
    "gemini-3.7-flash": (0.15, 0.60),
    "claude-sonnet-5-5": (3.00, 15.00),
    "claude-haiku-5-5": (0.80, 4.00),
}


def compute_kb_content_hash(kb_path: Optional[Path] = None, data_dir: Optional[Path] = None) -> str:
    """Computes a deterministic SHA-256 hash of all customer-facing KB markdown & JSON data."""
    root = kb_path or settings.KB_PATH
    data = data_dir or settings.DATA_DIR
    h = hashlib.sha256()

    if root.exists():
        for md in sorted(root.rglob("*.md")):
            rel = md.relative_to(root)
            if any(ex in rel.parts[:-1] for ex in settings.KB_EXCLUDE_DIRS):
                continue
            if md.name in settings.KB_EXCLUDE_FILES:
                continue
            h.update(str(rel).replace("\\", "/").encode("utf-8"))
            h.update(md.read_bytes())

    for fname in ("menu.json", "branches.json", "promos.json"):
        fpath = data / fname
        if fpath.exists():
            h.update(fname.encode("utf-8"))
            h.update(fpath.read_bytes())

    return h.hexdigest()[:16]


def get_eval_metadata() -> Dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "kb_content_hash": compute_kb_content_hash(),
        "orchestrator_model": settings.ORCHESTRATOR_MODEL,
        "subagent_model": settings.SUBAGENT_MODEL,
        "judge_model": settings.JUDGE_MODEL,
    }


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 2)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return round(float(ordered[lo]), 2)
    frac = rank - lo
    return round(float(ordered[lo] + frac * (ordered[hi] - ordered[lo])), 2)


@dataclass
class TelemetryCollector:
    """Tracks L7 non-functional metrics (latency, tokens, cost, tool counts)."""

    turn_latencies_ms: List[float] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    estimated_cost_usd: float = 0.0
    by_model: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def record_llm(self, model: str, prompt_toks: int, comp_toks: int, total_toks: int) -> None:
        self.llm_calls += 1
        self.prompt_tokens += prompt_toks
        self.completion_tokens += comp_toks
        self.total_tokens += total_toks
        in_rate, out_rate = _MODEL_PRICE_PER_1M_INPUT_OUTPUT.get(model, (1.0, 3.0))
        call_cost = (prompt_toks * in_rate + comp_toks * out_rate) / 1_000_000.0
        self.estimated_cost_usd += call_cost
        bucket = self.by_model.setdefault(
            model or "unknown", {"calls": 0, "tokens": 0, "cost_usd": 0.0}
        )
        bucket["calls"] += 1
        bucket["tokens"] += total_toks
        bucket["cost_usd"] = round(bucket["cost_usd"] + call_cost, 6)

    def record_turn(self, latency_ms: float, num_tools: int = 0) -> None:
        self.turn_latencies_ms.append(float(latency_ms))
        self.tool_calls += int(num_tools)

    def summary(self) -> Dict[str, Any]:
        return {
            "turns": len(self.turn_latencies_ms),
            "latency_p50_ms": percentile(self.turn_latencies_ms, 50),
            "latency_p95_ms": percentile(self.turn_latencies_ms, 95),
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "avg_tools_per_turn": round(self.tool_calls / max(1, len(self.turn_latencies_ms)), 2),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "by_model": self.by_model,
        }


@contextlib.contextmanager
def eval_sandbox(
    frozen_clock: Optional[str] = None,
    telemetry: Optional[TelemetryCollector] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Context manager providing complete state & I/O isolation for eval suites:
    - Temp SQLite DB
    - Fresh in-memory SessionStore
    - No-op notifier capture
    - Optional frozen clock
    - Optional LLM telemetry instrumentation
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="pizza_eval_"))
    tmp_db = tmp_dir / "eval_orders.db"

    orig_db_path = order_repo.db_path
    orig_store = session_mod._STORE_INSTANCE
    orig_transport = notifier._transport
    orig_complete = llm_client.complete

    sent_notifications: List[Dict[str, Any]] = []

    def _capture_notify(jid: str, text: str) -> bool:
        sent_notifications.append({"jid": jid, "text": text})
        return True

    def _instrumented_complete(*args, **kwargs):
        t0 = time.perf_counter()
        resp = orig_complete(*args, **kwargs)
        if telemetry is not None:
            usage = getattr(resp, "usage", None)
            p_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
            c_tok = int(getattr(usage, "completion_tokens", 0) or 0)
            t_tok = int(getattr(usage, "total_tokens", 0) or (p_tok + c_tok))
            telemetry.record_llm(
                getattr(resp, "model", "") or kwargs.get("model") or settings.SUBAGENT_MODEL,
                p_tok,
                c_tok,
                t_tok,
            )
        return resp

    try:
        order_repo.db_path = tmp_db
        order_repo.init_db()
        session_mod._STORE_INSTANCE = MemorySessionStore()
        notifier.clear_events()
        notifier.set_transport(_capture_notify)
        if telemetry is not None:
            llm_client.complete = _instrumented_complete  # type: ignore[method-assign]
        if frozen_clock:
            clock.set_clock(frozen_clock)

        yield {
            "tmp_dir": tmp_dir,
            "db_path": tmp_db,
            "notifications": sent_notifications,
        }
    finally:
        llm_client.complete = orig_complete  # type: ignore[method-assign]
        if frozen_clock:
            clock.reset_clock()
        notifier.set_transport(orig_transport)
        notifier.clear_events()
        session_mod._STORE_INSTANCE = orig_store
        order_repo.db_path = orig_db_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

