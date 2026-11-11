"""
Phase 6 (Section 12.6): Voice Note Evaluation Runner.
Computes per-language Word Error Rate (WER), Slot Accuracy, and
Transcript Confirmation Rule Recall across the 32-case voice dataset.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import yaml  # type: ignore
from app.agents.orchestrator import orchestrator
from app.config import settings


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Computes standard Levenshtein Word Error Rate (WER) between reference and hypothesis."""
    ref_words = reference.lower().strip().split()
    hyp_words = hypothesis.lower().strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    dp = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        dp[i][0] = i
    for j in range(len(hyp_words) + 1):
        dp[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            cost = 0 if ref_words[i - 1] == hyp_words[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,       # deletion
                dp[i][j - 1] + 1,       # insertion
                dp[i - 1][j - 1] + cost # substitution
            )
    return float(dp[len(ref_words)][len(hyp_words)]) / float(len(ref_words))


def check_slots_present(hypothesis: str, expected_slots: Dict[str, List[str]]) -> bool:
    """Checks that all expected slot values (items, sizes, quantities, areas, promos) appear in transcript."""
    lower = hypothesis.lower()
    for _slot_type, values in (expected_slots or {}).items():
        for val in values:
            if str(val).lower() not in lower:
                return False
    return True


def run_voice_eval(dataset_path: Path | None = None) -> Dict[str, Any]:
    path = dataset_path or (BASE_DIR / "eval" / "datasets" / "voice.yaml")
    cases: List[Dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))

    by_lang: Dict[str, Dict[str, Any]] = {}
    low_conf_total = 0
    low_conf_triggered = 0
    expected_confirm_total = 0
    expected_confirm_matched = 0
    results = []

    for case in cases:
        cid = case["id"]
        lang = case.get("lang", "en")
        ref = case["reference_transcript"]
        hyp = case.get("simulated_hypothesis", ref)
        conf = float(case.get("stt_confidence", 0.9))
        expected_slots = case.get("expected_slots", {})
        expect_confirm = bool(case.get("expect_confirmation", True))

        wer = word_error_rate(ref, hyp)
        slots_ok = check_slots_present(hyp, expected_slots)
        triggered_confirm = orchestrator._should_confirm_voice_transcript(hyp, conf)

        if conf < settings.STT_CONFIDENCE_THRESHOLD:
            low_conf_total += 1
            if triggered_confirm:
                low_conf_triggered += 1

        expected_confirm_total += 1
        if triggered_confirm == expect_confirm:
            expected_confirm_matched += 1

        lang_bucket = by_lang.setdefault(
            lang, {"count": 0, "wer_sum": 0.0, "slot_hits": 0, "confirm_matches": 0}
        )
        lang_bucket["count"] += 1
        lang_bucket["wer_sum"] += wer
        if slots_ok:
            lang_bucket["slot_hits"] += 1
        if triggered_confirm == expect_confirm:
            lang_bucket["confirm_matches"] += 1

        results.append(
            {
                "id": cid,
                "lang": lang,
                "wer": round(wer, 4),
                "slots_ok": slots_ok,
                "triggered_confirm": triggered_confirm,
                "expect_confirm": expect_confirm,
            }
        )

    lang_summary = {}
    for lang, b in by_lang.items():
        n = max(1, b["count"])
        lang_summary[lang] = {
            "cases": b["count"],
            "avg_wer": round(b["wer_sum"] / n, 4),
            "slot_accuracy": round(b["slot_hits"] / n, 4),
            "confirmation_accuracy": round(b["confirm_matches"] / n, 4),
        }

    low_conf_recall = (
        round(low_conf_triggered / low_conf_total, 4) if low_conf_total > 0 else 1.0
    )
    overall_confirm_acc = (
        round(expected_confirm_matched / expected_confirm_total, 4)
        if expected_confirm_total > 0
        else 1.0
    )

    summary = {
        "total_cases": len(cases),
        "low_confidence_confirmation_recall": low_conf_recall,
        "overall_confirmation_rule_accuracy": overall_confirm_acc,
        "by_language": lang_summary,
        "cases": results,
    }
    return summary


if __name__ == "__main__":
    report = run_voice_eval()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))

