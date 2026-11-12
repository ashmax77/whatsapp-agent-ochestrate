"""
Phase 8 (Section 12.2): L1 Retrieval Evaluation Runner.

Measures Recall@4, Hit@1, MRR, per-folder recall breakdown, score distributions,
out-of-scope refusal rate, and internal-chunk leakage count (must be 0).
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import yaml  # type: ignore
from app.config import settings
from app.rag.ingest import ingest_kb
from app.rag.retriever import KnowledgeRetriever
from eval.isolation import QUALITY_GATES


def _build_temp_retriever() -> tuple[KnowledgeRetriever, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="eval_rag_"))
    ingest_kb(chroma_path=tmp, prefer_local=True)
    ret = KnowledgeRetriever(
        index_info_file=tmp / "index_info.json",
        legacy_index_file=tmp / "none.json",
    )
    return ret, tmp


def run_retrieval_eval(
    dataset_path: Optional[Path] = None,
    retriever: Optional[KnowledgeRetriever] = None,
    use_temp_local_index: bool = False,
    k: int = 4,
) -> Dict[str, Any]:
    path = dataset_path or (BASE_DIR / "eval" / "datasets" / "retrieval.yaml")
    cases: List[Dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))

    tmp_dir: Optional[Path] = None
    if retriever is None:
        if use_temp_local_index or not settings.INDEX_INFO_FILE.exists():
            retriever, tmp_dir = _build_temp_retriever()
        else:
            retriever = KnowledgeRetriever()

    try:
        in_scope_total = 0
        recall_hits = 0
        hit_at_1_count = 0
        mrr_sum = 0.0
        folder_stats: Dict[str, Dict[str, int]] = {}
        in_scope_scores: List[float] = []

        oos_total = 0
        oos_refused = 0
        oos_scores: List[float] = []

        leak_probes_total = 0
        internal_leaks = 0
        failures: List[Dict[str, Any]] = []
        per_case: List[Dict[str, Any]] = []

        for case in cases:
            cid = case["id"]
            q = case["question"]
            rel_ids = set(case.get("relevant_ids") or [])
            is_oos = bool(case.get("out_of_scope", False))
            forbidden_aud = case.get("must_not_return_audience")
            folder = case.get("folder", "unknown")

            hits = retriever.retrieve(q, k=k, role="customer")
            hit_ids = [h.id for h in hits]
            top_score = float(hits[0].score) if hits else None

            # Defense-in-depth audit: check audience & internal folder leakage on every query
            leaked_hits = [
                h.id for h in hits
                if h.meta.get("audience") != "customer" or h.meta.get("folder") == "internal"
            ]
            if leaked_hits:
                internal_leaks += len(leaked_hits)

            if forbidden_aud:
                leak_probes_total += 1
                leaked = any(h.meta.get("audience") == forbidden_aud for h in hits)
                if leaked:
                    internal_leaks += 1
                if leaked or leaked_hits:
                    failures.append({
                        "id": cid,
                        "question": q,
                        "type": "leak_probe",
                        "expected": f"0 chunks with audience={forbidden_aud}",
                        "got_ids": hit_ids,
                        "top_score": round(top_score, 4) if top_score is not None else None,
                    })
                per_case.append({
                    "id": cid,
                    "type": "leak_probe",
                    "passed": not leaked and not leaked_hits,
                    "hit_ids": hit_ids,
                })
            elif is_oos:
                oos_total += 1
                if top_score is not None:
                    oos_scores.append(top_score)
                refused = len(hits) == 0
                if refused:
                    oos_refused += 1
                else:
                    failures.append({
                        "id": cid,
                        "question": q,
                        "type": "out_of_scope",
                        "expected": "0 hits (refusal)",
                        "got_ids": hit_ids,
                        "top_score": round(top_score, 4) if top_score is not None else None,
                    })
                per_case.append({
                    "id": cid,
                    "type": "out_of_scope",
                    "passed": refused and not leaked_hits,
                    "hit_ids": hit_ids,
                })
            else:
                in_scope_total += 1
                if top_score is not None:
                    in_scope_scores.append(top_score)
                fb = folder_stats.setdefault(folder, {"total": 0, "recalled": 0, "hit1": 0})
                fb["total"] += 1

                recalled = bool(rel_ids & set(hit_ids))
                hit1 = bool(hit_ids and hit_ids[0] in rel_ids)
                if recalled:
                    recall_hits += 1
                    fb["recalled"] += 1
                if hit1:
                    hit_at_1_count += 1
                    fb["hit1"] += 1

                first_rank = next((idx + 1 for idx, hid in enumerate(hit_ids) if hid in rel_ids), None)
                if first_rank is not None:
                    mrr_sum += 1.0 / first_rank

                if not recalled:
                    failures.append({
                        "id": cid,
                        "question": q,
                        "type": f"in_scope:{folder}",
                        "expected": sorted(rel_ids),
                        "got_ids": hit_ids,
                        "top_score": round(top_score, 4) if top_score is not None else None,
                    })
                per_case.append({
                    "id": cid,
                    "type": f"in_scope:{folder}",
                    "passed": recalled,
                    "hit1": hit1,
                    "hit_ids": hit_ids,
                })

        recall_at_4 = round(recall_hits / max(1, in_scope_total), 4)
        hit_at_1 = round(hit_at_1_count / max(1, in_scope_total), 4)
        mrr = round(mrr_sum / max(1, in_scope_total), 4)
        oos_refusal_rate = round(oos_refused / max(1, oos_total), 4)

        per_folder = {
            f: {
                "cases": st["total"],
                "recall_at_4": round(st["recalled"] / max(1, st["total"]), 4),
                "hit_at_1": round(st["hit1"] / max(1, st["total"]), 4),
            }
            for f, st in sorted(folder_stats.items())
        }

        gates_passed = (
            recall_at_4 >= QUALITY_GATES["retrieval_recall_at_4_min"]
            and hit_at_1 >= QUALITY_GATES["retrieval_hit_at_1_min"]
            and oos_refusal_rate >= QUALITY_GATES["retrieval_oos_refusal_min"]
            and internal_leaks <= QUALITY_GATES["retrieval_internal_leaks_max"]
        )

        return {
            "suite": "retrieval",
            "total_cases": len(cases),
            "in_scope_cases": in_scope_total,
            "out_of_scope_cases": oos_total,
            "leak_probe_cases": leak_probes_total,
            "recall_at_4": recall_at_4,
            "hit_at_1": hit_at_1,
            "mrr": mrr,
            "oos_refusal_rate": oos_refusal_rate,
            "internal_leaks": internal_leaks,
            "per_folder": per_folder,
            "score_distribution": {
                "in_scope_min": round(min(in_scope_scores), 4) if in_scope_scores else None,
                "in_scope_mean": round(sum(in_scope_scores) / len(in_scope_scores), 4) if in_scope_scores else None,
                "oos_max": round(max(oos_scores), 4) if oos_scores else None,
            },
            "failures": failures,
            "per_case": per_case,
            "passed": gates_passed,
        }
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

