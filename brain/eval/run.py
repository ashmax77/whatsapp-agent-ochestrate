"""
Phase 8 (Section 12.7 & 12.8): Unified Evaluation Runner, Quality Gates & Baseline Regression CLI.

Usage:
  python -m eval.run --suite all --offline
  python -m eval.run --suite retrieval
  python -m eval.run --suite all --offline --save-baseline
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import settings
from eval.isolation import QUALITY_GATES, TelemetryCollector, get_eval_metadata
from eval.runners.judge import run_judge_eval
from eval.runners.retrieval_eval import run_retrieval_eval
from eval.runners.safety_eval import run_safety_eval
from eval.runners.tools_eval import run_tools_eval
from eval.runners.voice_eval import run_voice_eval
from eval.simulator import run_conversation_eval

REPORTS_DIR = BASE_DIR / "eval" / "reports"
BASELINE_PATH = REPORTS_DIR / "baseline.json"

# Metrics monitored for >3% regression against baseline.json
_RATE_METRICS: Dict[str, List[str]] = {
    "retrieval": ["recall_at_4", "hit_at_1", "mrr", "oos_refusal_rate"],
    "tools": ["tool_selection_accuracy", "argument_accuracy", "state_match_rate"],
    "conversation": ["pass_at_k_rate", "pass_all_rate"],
    "judge": ["within_1_pct", "overall_mean"],
    "safety": ["escalation_recall"],
    "voice": ["low_confidence_confirmation_recall", "overall_confirmation_rule_accuracy"],
}

_ZERO_TOLERANCE_METRICS: Dict[str, List[str]] = {
    "retrieval": ["internal_leaks"],
    "tools": ["forbidden_tool_violations"],
    "conversation": ["invariant_violations"],
    "safety": ["safety_violations"],
}


def _evaluate_voice_with_gates() -> Dict[str, Any]:
    res = run_voice_eval()
    by_lang = res.get("by_language") or {}
    min_slot_acc = min(
        (float(v.get("slot_accuracy", 0.0)) for v in by_lang.values()),
        default=0.0,
    )
    low_conf_recall = float(res.get("low_confidence_confirmation_recall", 0.0))
    overall_conf_acc = float(res.get("overall_confirmation_rule_accuracy", 0.0))
    passed = (
        min_slot_acc >= QUALITY_GATES["voice_slot_accuracy_min"]
        and low_conf_recall >= QUALITY_GATES["voice_low_conf_recall_min"]
        and overall_conf_acc >= 0.90
    )
    return {
        **res,
        "suite": "voice",
        "min_language_slot_accuracy": round(min_slot_acc, 4),
        "passed": passed,
    }


def check_baseline_regressions(
    current_suites: Dict[str, Dict[str, Any]],
    baseline_path: Path = BASELINE_PATH,
    max_drop: float = 0.03,
) -> List[str]:
    """Compare current suite results against baseline.json; flag >3% drops or >0 zero-tolerance leaks."""
    if not baseline_path.exists():
        return []
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    base_suites = baseline.get("suites") or {}
    regressions: List[str] = []

    for suite_name, metrics in _RATE_METRICS.items():
        if suite_name not in current_suites or suite_name not in base_suites:
            continue
        cur = current_suites[suite_name]
        base = base_suites[suite_name]
        for m in metrics:
            if m in cur and m in base:
                cur_v = float(cur[m])
                base_v = float(base[m])
                if base_v > 0 and (base_v - cur_v) > max_drop:
                    regressions.append(
                        f"{suite_name}.{m} dropped from {base_v:.4f} to {cur_v:.4f} (> {max_drop:.2%})"
                    )

    for suite_name, metrics in _ZERO_TOLERANCE_METRICS.items():
        if suite_name not in current_suites:
            continue
        cur = current_suites[suite_name]
        for m in metrics:
            if float(cur.get(m, 0)) > 0:
                regressions.append(f"{suite_name}.{m} is {cur[m]} (zero-tolerance gate)")

    return regressions


def _render_summary_md(report: Dict[str, Any]) -> str:
    meta = report["metadata"]
    tel = report["telemetry"]
    lines = [
        "# Evaluation Summary",
        "",
        f"- **Timestamp (UTC)**: `{meta.get('timestamp_utc', '')}`",
        f"- **Prompt Version**: `{meta.get('prompt_version', '')}`",
        f"- **KB Hash**: `{meta.get('kb_content_hash', '')}`",
        f"- **Orchestrator Model**: `{meta.get('orchestrator_model', '')}`",
        f"- **Overall Passed**: `{'PASS' if report['passed'] else 'FAIL'}`",
        "",
        "## Suite Results",
        "",
        "| Suite | Mode | Key Metrics | Passed |",
        "|---|---|---|---|",
    ]
    for name, res in report["suites"].items():
        mode = res.get("mode", "deterministic")
        if name == "retrieval":
            key = f"recall@4={res['recall_at_4']}, hit@1={res['hit_at_1']}, oos={res['oos_refusal_rate']}, leaks={res['internal_leaks']}"
        elif name == "tools":
            key = f"sel={res['tool_selection_accuracy']}, args={res['argument_accuracy']}, state={res['state_match_rate']}, forbidden={res['forbidden_tool_violations']}"
        elif name == "conversation":
            key = f"pass@k={res['pass_at_k_rate']}, invariants={res['invariant_violations']}, avg_turns={res['avg_turns']}"
        elif name == "judge":
            key = f"mean={res['overall_mean']}, within_1={res['within_1_pct']}, kappa={res['cohens_kappa']}"
        elif name == "safety":
            key = f"esc_recall={res['escalation_recall']}, fpr={res['escalation_false_positive_rate']}, violations={res['safety_violations']}"
        elif name == "voice":
            key = f"min_slot_acc={res['min_language_slot_accuracy']}, low_conf_recall={res['low_confidence_confirmation_recall']}"
        else:
            key = "-"
        lines.append(f"| `{name}` | `{mode}` | {key} | `{'PASS' if res.get('passed') else 'FAIL'}` |")

    lines.extend([
        "",
        "## Telemetry & Cost",
        "",
        f"- Turns: `{tel.get('turns', 0)}` | Total tokens: `{tel.get('total_tokens', 0)}` | Est. cost: `${tel.get('estimated_cost_usd', 0.0):.6f}`",
        f"- Latency p50: `{tel.get('latency_p50_ms', 0.0)} ms` | p95: `{tel.get('latency_p95_ms', 0.0)} ms`",
    ])
    if report.get("latency_gate_failures"):
        lines.extend(["", "## Latency Gate Failures", ""])
        for lf in report["latency_gate_failures"]:
            lines.append(f"- {lf}")
    if report.get("baseline_regressions"):
        lines.extend(["", "## Baseline Regressions", ""])
        for reg in report["baseline_regressions"]:
            lines.append(f"- {reg}")
    return "\n".join(lines) + "\n"


def _render_failures_md(report: Dict[str, Any]) -> str:
    lines = ["# Evaluation Failures", ""]
    any_fail = False
    for name, res in report["suites"].items():
        fails = res.get("failures") or res.get("calibration_mismatches") or []
        if fails or not res.get("passed"):
            any_fail = True
            lines.append(f"## `{name}`")
            lines.append("```json")
            lines.append(json.dumps(fails, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
    if not any_fail:
        lines.append("No failures detected across executed suites.")
    return "\n".join(lines) + "\n"


def run_eval(
    suite: str = "all",
    offline: bool = True,
    repeats: int = 1,
    model_override: Optional[str] = None,
    report_dir: Optional[Path] = None,
    save_baseline: bool = False,
    check_baseline: bool = True,
) -> Dict[str, Any]:
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    prev_model = settings.ORCHESTRATOR_MODEL
    if model_override:
        settings.ORCHESTRATOR_MODEL = model_override

    telemetry = TelemetryCollector()
    suites_to_run = (
        ["retrieval", "tools", "conversation", "judge", "safety", "voice"]
        if suite == "all"
        else [suite]
    )

    results: Dict[str, Dict[str, Any]] = {}
    try:
        for s in suites_to_run:
            if s == "retrieval":
                results[s] = run_retrieval_eval()
            elif s == "tools":
                results[s] = run_tools_eval(offline=offline, repeats=repeats, telemetry=telemetry)
            elif s == "conversation":
                results[s] = run_conversation_eval(offline=offline, repeats=repeats, telemetry=telemetry)
            elif s == "judge":
                results[s] = run_judge_eval(offline=offline, telemetry=telemetry)
            elif s == "safety":
                results[s] = run_safety_eval(offline=offline, telemetry=telemetry)
            elif s == "voice":
                results[s] = _evaluate_voice_with_gates()
            else:
                raise ValueError(f"Unknown eval suite: {s}")
        meta = get_eval_metadata()
    finally:
        settings.ORCHESTRATOR_MODEL = prev_model

    tel_summary = telemetry.summary()
    latency_gate_failures: List[str] = []
    if not offline and tel_summary.get("turns", 0) > 0:
        if tel_summary["latency_p50_ms"] > QUALITY_GATES["latency_p50_ms_max"]:
            latency_gate_failures.append(
                f"latency_p50_ms={tel_summary['latency_p50_ms']:.2f} ms > {QUALITY_GATES['latency_p50_ms_max']:.1f} ms"
            )
        if tel_summary["latency_p95_ms"] > QUALITY_GATES["latency_p95_ms_max"]:
            latency_gate_failures.append(
                f"latency_p95_ms={tel_summary['latency_p95_ms']:.2f} ms > {QUALITY_GATES['latency_p95_ms_max']:.1f} ms"
            )
    latency_ok = len(latency_gate_failures) == 0

    regressions = check_baseline_regressions(results) if (check_baseline and not save_baseline) else []
    all_suites_passed = all(bool(r.get("passed")) for r in results.values())
    overall_passed = all_suites_passed and latency_ok and len(regressions) == 0

    meta["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    meta["offline"] = offline

    report: Dict[str, Any] = {
        "metadata": meta,
        "quality_gates": QUALITY_GATES,
        "telemetry": tel_summary,
        "suites": results,
        "latency_gate_failures": latency_gate_failures,
        "baseline_regressions": regressions,
        "passed": overall_passed,
    }

    ts_dir = report_dir or (REPORTS_DIR / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    ts_dir.mkdir(parents=True, exist_ok=True)
    (ts_dir / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ts_dir / "costs.json").write_text(json.dumps(tel_summary, indent=2), encoding="utf-8")
    (ts_dir / "summary.md").write_text(_render_summary_md(report), encoding="utf-8")
    (ts_dir / "failures.md").write_text(_render_failures_md(report), encoding="utf-8")

    if save_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    report["report_dir"] = str(ts_dir)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pizza Hut WhatsApp Agent Evaluation Runner")
    parser.add_argument(
        "--suite",
        choices=["retrieval", "tools", "conversation", "judge", "safety", "voice", "all"],
        default="all",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--model-override", type=str, default=None)
    parser.add_argument("--report-dir", type=str, default=None)
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--no-baseline-check", action="store_true")
    args = parser.parse_args(argv)

    rep_dir = Path(args.report_dir) if args.report_dir else None
    report = run_eval(
        suite=args.suite,
        offline=args.offline,
        repeats=args.repeats,
        model_override=args.model_override,
        report_dir=rep_dir,
        save_baseline=args.save_baseline,
        check_baseline=not args.no_baseline_check,
    )
    print(_render_summary_md(report))
    print(f"Report written to: {report['report_dir']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

