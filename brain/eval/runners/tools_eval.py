"""
Phase 8 (Section 12.3): L2 Tool Trajectory & State-Machine Evaluation Runner.

Supports:
- offline=True: Deterministically executes scripted `tool_call` / `tool_calls` sequences
  against the real ToolRegistry & state machine inside an isolated EvalSandbox.
- offline=False (live): Feeds customer utterances through `orchestrator.handle_message`
  at temperature 0, repeats N times (default 3), and checks tool selection, arguments,
  forbidden tools, reply redlines, and final session state.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import yaml  # type: ignore
from app.agents.orchestrator import orchestrator
from app.agents.post_order_agent import post_order_agent
from app.schemas import IncomingMessage
from app.state.session import CartLine, Session, get_session_store
from app.tools.registry import registry
from eval.isolation import QUALITY_GATES, TelemetryCollector, eval_sandbox


def _run_coro(coro):
    """Drives coroutine cleanly without requiring OS loopback sockets in sandboxed environments."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            while True:
                coro.send(None)
        except StopIteration as stop:
            return stop.value
    return asyncio.run(coro)


def _seed_session(user_id: str, setup: Dict[str, Any]) -> Session:
    store = get_session_store()
    sess = Session(user_id=user_id)
    if "stage" in setup:
        sess.stage = setup["stage"]
    if "fulfilment" in setup:
        sess.fulfilment = setup["fulfilment"]
    if "branch_id" in setup:
        sess.branch_id = setup["branch_id"]
    if "delivery_zone" in setup:
        sess.delivery_zone = setup["delivery_zone"]
    if "address" in setup:
        sess.address = setup["address"]
    if "promo_code" in setup:
        sess.promo_code = setup["promo_code"]
    if "summary_hash" in setup:
        sess.summary_hash = setup["summary_hash"]
    if "summary_msg_no" in setup:
        sess.summary_msg_no = int(setup["summary_msg_no"])

    for line in setup.get("cart") or []:
        sess.cart.append(
            CartLine(
                item_id=line["item_id"],
                size=line.get("size", "regular"),
                qty=int(line.get("qty", 1)),
                notes=line.get("notes"),
                combo_choices=line.get("combo_choices"),
            )
        )
    _run_coro(store.save(sess))
    return sess


def _args_match(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    for k, v in (expected or {}).items():
        if k not in actual:
            return False
        if isinstance(v, str) and isinstance(actual[k], str):
            if v.lower() not in actual[k].lower() and actual[k].lower() != v.lower():
                return False
        elif actual[k] != v:
            return False
    return True


def _check_final_state(expect_state: Dict[str, Any], sess: Session) -> List[str]:
    errs: List[str] = []
    for k, v in (expect_state or {}).items():
        if k == "stage_not":
            if sess.stage == v:
                errs.append(f"stage must not be {v!r}")
        elif k == "cart":
            actual_cart = [
                {"item_id": c.item_id, "size": c.size, "qty": c.qty} for c in sess.cart
            ]
            for exp_item in v:
                if not any(
                    a["item_id"] == exp_item["item_id"]
                    and a["size"] == exp_item.get("size", a["size"])
                    and a["qty"] == exp_item.get("qty", a["qty"])
                    for a in actual_cart
                ):
                    errs.append(f"missing expected cart item {exp_item}; got {actual_cart}")
        else:
            actual_val = getattr(sess, k, None)
            if actual_val != v:
                errs.append(f"{k}: expected {v!r}, got {actual_val!r}")
    return errs


def run_tools_eval(
    dataset_path: Optional[Path] = None,
    offline: bool = True,
    repeats: int = 1,
    telemetry: Optional[TelemetryCollector] = None,
) -> Dict[str, Any]:
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    path = dataset_path or (BASE_DIR / "eval" / "datasets" / "tools.yaml")
    cases: List[Dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))

    effective_repeats = 1 if offline else max(1, repeats)
    total_runs = 0
    passed_runs = 0
    tool_expected_total = 0
    tool_selected_hits = 0
    arg_hits = 0
    state_checks_total = 0
    state_checks_passed = 0
    forbidden_violations = 0
    total_tool_calls = 0
    total_turns = 0
    failures: List[Dict[str, Any]] = []
    case_summaries: List[Dict[str, Any]] = []

    for case in cases:
        cid = case["id"]
        case_pass_count = 0

        for rep in range(effective_repeats):
            total_runs += 1
            case_errs: List[str] = []
            executed_calls: List[Dict[str, Any]] = []
            replies: List[str] = []
            uid = f"eval_{cid}_{rep}"

            with eval_sandbox(frozen_clock=case.get("clock"), telemetry=telemetry):
                sess = _seed_session(uid, case.get("setup") or {})
                store = get_session_store()

                if offline:
                    for tidx, turn in enumerate(case.get("turns") or []):
                        total_turns += 1
                        scripted = []
                        if "tool_calls" in turn:
                            scripted = turn["tool_calls"]
                        elif "tool_call" in turn:
                            scripted = [turn["tool_call"]]

                        if not scripted:
                            continue

                        sess.message_count += 1
                        _run_coro(store.save(sess))

                        for tc in scripted:
                            tname = tc["name"]
                            targs = dict(tc.get("args") or {})
                            if tc.get("use_summary_hash") and sess.summary_hash:
                                targs["cart_hash"] = sess.summary_hash
                            res = registry.call(
                                tname, session=sess, args=targs
                            )
                            _run_coro(store.save(sess))
                            total_tool_calls += 1
                            executed_calls.append(
                                {"name": tname, "args": targs, "ok": bool(res.get("ok")), "res": res}
                            )
                            if tname == "kb.ask" and res.get("ok"):
                                replies.append(str(res.get("data", {}).get("answer", "")))
                else:
                    orig_call = registry.call

                    def _spy_call(name: str, session: Session, args: Optional[Dict[str, Any]] = None, **kw):
                        norm_name = name.replace("__", ".")
                        res = orig_call(norm_name, session=session, args=args, **kw)
                        executed_calls.append(
                            {
                                "name": norm_name,
                                "args": dict(args or {}),
                                "ok": bool(res.get("ok")),
                                "res": res,
                            }
                        )
                        return res

                    registry.call = _spy_call  # type: ignore[method-assign]
                    try:
                        for tidx, turn in enumerate(case.get("turns") or []):
                            total_turns += 1
                            t0 = time.perf_counter()
                            before_n = len(executed_calls)
                            reply = _run_coro(
                                orchestrator.handle_message(
                                    IncomingMessage(
                                        user_id=uid,
                                        type="text",
                                        content=turn["user"],
                                        message_id=f"{uid}_m{tidx}",
                                    )
                                )
                            )
                            lat_ms = (time.perf_counter() - t0) * 1000.0
                            turn_tools = len(executed_calls) - before_n
                            total_tool_calls += turn_tools
                            if telemetry:
                                telemetry.record_turn(lat_ms, turn_tools)
                            if reply.reply_text:
                                replies.append(reply.reply_text)
                    finally:
                        registry.call = orig_call  # type: ignore[method-assign]

                final_sess = _run_coro(store.get(uid))
                expect = case.get("expect") or {}

                # Check forbidden tools (only count successful forbidden executions as violations)
                forbidden = set(expect.get("forbidden_tools") or [])
                for c in executed_calls:
                    if c["name"] in forbidden and c["ok"]:
                        forbidden_violations += 1
                        case_errs.append(f"forbidden tool succeeded: {c['name']}")

                # Check expected tool calls
                for exp_tc in expect.get("tool_calls_include") or []:
                    tool_expected_total += 1
                    exp_name = exp_tc["name"]
                    matches = [c for c in executed_calls if c["name"] == exp_name]
                    if matches:
                        tool_selected_hits += 1
                        exp_args = exp_tc.get("args") or {}
                        if not exp_args or any(_args_match(exp_args, m["args"]) for m in matches):
                            arg_hits += 1
                        else:
                            case_errs.append(
                                f"tool {exp_name} args mismatch: expected {exp_args}, got {[m['args'] for m in matches]}"
                            )
                    else:
                        case_errs.append(f"expected tool {exp_name} not called")

                # Check final state
                if "final_state" in expect:
                    state_checks_total += 1
                    st_errs = _check_final_state(expect["final_state"], final_sess)
                    if not st_errs:
                        state_checks_passed += 1
                    else:
                        case_errs.extend(st_errs)

                # Check forbidden reply substrings
                combined_reply = "\n".join(replies)
                for bad_sub in expect.get("answer_must_not_contain_any") or []:
                    if bad_sub.lower() in combined_reply.lower():
                        case_errs.append(f"forbidden text leaked in reply: {bad_sub!r}")

            if not case_errs:
                passed_runs += 1
                case_pass_count += 1
            else:
                failures.append({
                    "id": cid,
                    "repeat": rep + 1,
                    "description": case.get("description", ""),
                    "errors": case_errs,
                })

        case_passed = case_pass_count >= ((effective_repeats + 1) // 2)  # >= 2/3 for N=3
        case_summaries.append({
            "id": cid,
            "description": case.get("description", ""),
            "passes": case_pass_count,
            "repeats": effective_repeats,
            "passed": case_passed,
        })

    tool_sel_acc = round(tool_selected_hits / max(1, tool_expected_total), 4)
    arg_acc = round(arg_hits / max(1, tool_expected_total), 4)
    state_match = round(state_checks_passed / max(1, state_checks_total), 4)
    avg_tools = round(total_tool_calls / max(1, total_turns), 2)

    passed = (
        tool_sel_acc >= QUALITY_GATES["tools_accuracy_min"]
        and forbidden_violations <= QUALITY_GATES["tools_forbidden_violations_max"]
        and state_match >= QUALITY_GATES["tools_accuracy_min"]
        and not any("forbidden text leaked" in str(f["errors"]) for f in failures)
    )

    return {
        "suite": "tools",
        "mode": "offline" if offline else "live",
        "total_cases": len(cases),
        "total_runs": total_runs,
        "tool_selection_accuracy": tool_sel_acc,
        "argument_accuracy": arg_acc,
        "state_match_rate": state_match,
        "forbidden_tool_violations": forbidden_violations,
        "avg_tools_per_turn": avg_tools,
        "failures": failures,
        "cases": case_summaries,
        "passed": passed,
    }
