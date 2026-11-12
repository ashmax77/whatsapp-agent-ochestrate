"""
Phase 8 (Section 12.4): L3 End-to-End Conversation Simulator & Runner.

Executes multi-turn customer scenarios through `orchestrator.handle_message` (live LLM
customer persona) or deterministic scripted turns (`offline=True`) inside an isolated
EvalSandbox with a frozen Asia/Colombo clock, temp SQLite DB, and mocked notifier.
"""

import asyncio
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import yaml  # type: ignore
from app.agents.escalation_agent import escalation_agent
from app.agents.orchestrator import orchestrator
from app.config import settings
from app.db.order_repo import order_repo
from app.llm.client import llm_client
from app.schemas import IncomingMessage
from app.services.post_processor import find_unverified_prices
from app.state.session import get_session_store
from app.tools.registry import registry
from eval.isolation import QUALITY_GATES, TelemetryCollector, eval_sandbox


def _run_coro(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            while True:
                coro.send(None)
        except StopIteration as stop:
            return stop.value
    return asyncio.run(coro)


_SIMULATOR_SYSTEM = (
    "You are simulating a WhatsApp customer chatting with Pizza Hut Sri Lanka.\n"
    "Stay strictly in character for the persona and goal below. Send short, realistic WhatsApp messages (1-2 sentences).\n"
    "Once your goal is completely finished (e.g. you received an order number, or were refused/handed off as appropriate), "
    "reply with exactly: [SIM_DONE]"
)


def _next_customer_utterance(
    persona: str,
    goal: str,
    transcript: List[Dict[str, str]],
) -> str:
    prompt = f"Persona: {persona}\nGoal: {goal}\n\nConversation so far:\n"
    if not transcript:
        prompt += "(Start the conversation now with your first message.)"
    else:
        for t in transcript[-8:]:
            role = "Customer" if t["role"] == "user" else "Bot"
            prompt += f"{role}: {t['content']}\n"
        prompt += "\nWrite the Customer's next single WhatsApp reply (or [SIM_DONE] if finished):"

    resp = llm_client.complete(
        system=_SIMULATOR_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        model=settings.SUBAGENT_MODEL,
        max_tokens=120,
        temperature=0.7,
    )
    return (resp.text or "").strip()


def _check_scenario_outcome(
    scenario: Dict[str, Any],
    transcript: List[Dict[str, str]],
    user_id: str,
    executed_tools: List[Dict[str, Any]],
) -> tuple[List[str], List[str]]:
    """Returns (outcome_errors, invariant_violations)."""
    errors: List[str] = []
    invariants: List[str] = []

    store = get_session_store()
    sess = _run_coro(store.get(user_id))
    expected = scenario.get("expected_outcome") or {}
    inv_rules = scenario.get("invariants") or []

    # 1. Outcome checks
    if "order_placed" in expected:
        want_placed = bool(expected["order_placed"])
        is_placed = sess.stage == "placed" and bool(sess.last_order_no)
        if want_placed != is_placed:
            errors.append(
                f"order_placed expected={want_placed}, got={is_placed} (stage={sess.stage}, last_order_no={sess.last_order_no})"
            )

    if "stage" in expected and sess.stage != expected["stage"]:
        errors.append(f"stage expected={expected['stage']!r}, got={sess.stage!r}")

    if "stage_not" in expected and sess.stage == expected["stage_not"]:
        errors.append(f"stage must not be {expected['stage_not']!r}")

    if "branch_id" in expected and sess.branch_id != expected["branch_id"]:
        errors.append(f"branch_id expected={expected['branch_id']!r}, got={sess.branch_id!r}")

    if "fulfilment" in expected and sess.fulfilment != expected["fulfilment"]:
        errors.append(f"fulfilment expected={expected['fulfilment']!r}, got={sess.fulfilment!r}")

    if "promo_code" in expected and sess.promo_code != expected["promo_code"]:
        errors.append(f"promo_code expected={expected['promo_code']!r}, got={sess.promo_code!r}")

    if expected.get("items") and expected.get("order_placed"):
        order = order_repo.get_order_by_no(sess.last_order_no) if sess.last_order_no else None
        if not order:
            errors.append("persisted DB order missing for placed session")
        else:
            for exp_it in expected["items"]:
                if not any(
                    oi.item_id == exp_it["item_id"]
                    and oi.size == exp_it.get("size", oi.size)
                    and oi.qty == exp_it.get("qty", oi.qty)
                    for oi in order.items
                ):
                    errors.append(f"DB order missing expected item {exp_it}")
            if "total_lkr" in expected and expected["total_lkr"] is not None:
                if order.total != int(expected["total_lkr"]):
                    errors.append(f"DB order total expected={expected['total_lkr']}, got={order.total}")

    # 2. Invariant checks (must be 0 violations)
    bot_replies = [t["content"] for t in transcript if t["role"] == "assistant" and t.get("content")]
    all_bot_text = "\n".join(bot_replies)

    for inv in inv_rules:
        inv_l = str(inv).lower()
        if "order_no present" in inv_l and expected.get("order_placed"):
            if not sess.last_order_no or sess.last_order_no not in all_bot_text:
                invariants.append(f"order_no {sess.last_order_no!r} missing from bot replies")
        elif "student id" in inv_l:
            if "student" not in all_bot_text.lower() or "id" not in all_bot_text.lower():
                invariants.append("customer was not reminded to show student ID")
        elif "no price" in inv_l or "unverified price" in inv_l:
            unverified = find_unverified_prices(all_bot_text, sess, executed_tools)
            if unverified:
                invariants.append(f"unverified price(s) in reply: {unverified}")
        elif "no internal" in inv_l or "emp-" in inv_l:
            if re.search(r"\bEMP-\d+\b", all_bot_text, re.I):
                invariants.append("internal employee ID leaked in reply")
        elif "no unlisted discount" in inv_l or "christmas" in inv_l:
            if re.search(r"\b\d+\s*%\s*off\b", all_bot_text, re.I):
                invariants.append("promised an unlisted percentage discount")

    return errors, invariants


def _run_one_scenario(
    scenario: Dict[str, Any],
    offline: bool,
    rep_idx: int,
    telemetry: Optional[TelemetryCollector],
) -> Dict[str, Any]:
    sid = scenario["id"]
    uid = f"sim_{sid}_{rep_idx}"
    transcript: List[Dict[str, str]] = []
    executed_tools: List[Dict[str, Any]] = []

    with eval_sandbox(frozen_clock=scenario.get("clock"), telemetry=telemetry):
        store = get_session_store()

        if offline:
            for tidx, step in enumerate(scenario.get("scripted_turns") or []):
                user_msg = step.get("user", "")
                transcript.append({"role": "user", "content": user_msg})
                sess = _run_coro(store.get(uid))
                if sess.stage == "placed":
                    sess.reset_cart()
                sess.message_count += 1
                _run_coro(store.save(sess))

                step_replies: List[str] = []
                if step.get("handoff"):
                    h_res = escalation_agent.execute_handoff(
                        session=sess,
                        reason=step["handoff"].get("reason", "Escalated"),
                        category=step["handoff"].get("category", "complaint"),
                        is_critical=bool(step["handoff"].get("is_critical", False)),
                        latest_user_message=user_msg,
                    )
                    _run_coro(store.save(sess))
                    step_replies.append(h_res["data"]["customer_reply"])

                for tc in step.get("tool_calls") or []:
                    targs = dict(tc.get("args") or {})
                    if tc.get("use_summary_hash") and sess.summary_hash:
                        targs["cart_hash"] = sess.summary_hash
                    res = registry.call(tc["name"], session=sess, args=targs)
                    _run_coro(store.save(sess))
                    executed_tools.append(res)
                    if tc["name"] == "order.place_order" and res.get("ok"):
                        step_replies.append(f"Order placed! Order No: {res['data']['order_no']}")
                    elif tc["name"] == "order.show_summary" and res.get("ok"):
                        step_replies.append(res["data"].get("summary_text", ""))
                    elif tc["name"] == "promo.apply" and res.get("ok"):
                        step_replies.append(res["data"].get("message", ""))
                    elif not res.get("ok"):
                        step_replies.append(res.get("message", ""))

                if step.get("bot_reply"):
                    step_replies.append(step["bot_reply"])

                transcript.append({"role": "assistant", "content": "\n".join(r for r in step_replies if r)})
        else:
            max_turns = int(scenario.get("max_turns", 12))
            for tidx in range(max_turns):
                cust_text = _next_customer_utterance(
                    scenario.get("persona", "Customer"),
                    scenario.get("goal", "Order pizza"),
                    transcript,
                )
                if not cust_text or "[SIM_DONE]" in cust_text:
                    break
                transcript.append({"role": "user", "content": cust_text})

                t0 = time.perf_counter()
                reply = _run_coro(
                    orchestrator.handle_message(
                        IncomingMessage(
                            user_id=uid,
                            type="text",
                            content=cust_text,
                            message_id=f"{uid}_{tidx}",
                        )
                    )
                )
                lat_ms = (time.perf_counter() - t0) * 1000.0
                if telemetry:
                    telemetry.record_turn(lat_ms, 0)
                transcript.append({"role": "assistant", "content": reply.reply_text or ""})

                sess = _run_coro(store.get(uid))
                expected = scenario.get("expected_outcome") or {}
                if not offline:
                    if expected.get("order_placed") and sess.stage == "placed":
                        break
                    if expected.get("stage") == "handoff" and sess.stage == "handoff":
                        break

        errors, invariants = _check_scenario_outcome(scenario, transcript, uid, executed_tools)

    return {
        "id": sid,
        "repeat": rep_idx + 1,
        "passed": len(errors) == 0 and len(invariants) == 0,
        "errors": errors,
        "invariants": invariants,
        "turns": len([t for t in transcript if t["role"] == "user"]),
        "transcript": transcript,
    }


def run_conversation_eval(
    dataset_dir: Optional[Path] = None,
    offline: bool = True,
    repeats: int = 1,
    telemetry: Optional[TelemetryCollector] = None,
) -> Dict[str, Any]:
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    cdir = dataset_dir or (BASE_DIR / "eval" / "datasets" / "conversations")
    files = sorted(cdir.glob("*.yaml"))
    effective_repeats = 1 if offline else max(1, repeats)

    scenario_results: List[Dict[str, Any]] = []
    pass_at_k_count = 0
    pass_all_count = 0
    total_invariant_violations = 0
    failures: List[Dict[str, Any]] = []
    turns_list: List[int] = []

    for fpath in files:
        scenario = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        rep_runs = [
            _run_one_scenario(scenario, offline=offline, rep_idx=r, telemetry=telemetry)
            for r in range(effective_repeats)
        ]
        any_pass = any(r["passed"] for r in rep_runs)
        all_pass = all(r["passed"] for r in rep_runs)
        if any_pass:
            pass_at_k_count += 1
        if all_pass:
            pass_all_count += 1

        for r in rep_runs:
            turns_list.append(r["turns"])
            total_invariant_violations += len(r["invariants"])
            if not r["passed"]:
                failures.append({
                    "id": r["id"],
                    "repeat": r["repeat"],
                    "errors": r["errors"],
                    "invariants": r["invariants"],
                    "transcript": r["transcript"],
                })

        scenario_results.append({
            "id": scenario["id"],
            "pass_any": any_pass,
            "pass_all": all_pass,
        })

    n_scen = max(1, len(files))
    pass_rate = round(pass_at_k_count / n_scen, 4)
    pass_all_rate = round(pass_all_count / n_scen, 4)
    avg_turns = round(sum(turns_list) / max(1, len(turns_list)), 2)

    passed = (
        pass_rate >= QUALITY_GATES["conversation_pass_at_3_min"]
        and total_invariant_violations <= QUALITY_GATES["conversation_invariant_violations_max"]
    )

    return {
        "suite": "conversation",
        "mode": "offline" if offline else "live",
        "total_scenarios": len(files),
        "repeats": effective_repeats,
        "pass_at_k_rate": pass_rate,
        "pass_all_rate": pass_all_rate,
        "invariant_violations": total_invariant_violations,
        "avg_turns": avg_turns,
        "failures": failures,
        "scenarios": scenario_results,
        "passed": passed,
    }
