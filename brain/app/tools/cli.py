"""
CLI harness to exercise the deterministic Phase 4 order tools with zero LLM calls:

    # Run a built-in demo order flow:
    python -m app.tools.cli --demo

    # Call a single tool on a user session:
    python -m app.tools.cli --user demo1 --tool cart.add_item --args '{"item_id":"pz_supreme","size":"large","qty":1}'
"""
import argparse
import json
import sys
from typing import Any, Dict, List
from app.state.session import Session, get_session
from app.tools.registry import registry
from app.services import clock


def run_demo() -> int:
    # Freeze clock to a Friday afternoon so FRIDAY10 and all branches are open
    clock.set_clock("2026-11-13T18:30:00+05:30")
    session = Session(user_id="cli_demo_user", message_count=1)

    steps: List[tuple[str, Dict[str, Any], bool]] = [
        ("branch.list", {}, False),
        ("cart.add_item", {"item_id": "pz_supreme", "size": "large", "qty": 1}, False),
        ("cart.add_item", {"item_id": "sd_garlic_bread", "size": "regular", "qty": 2}, False),
        ("order.set_fulfilment", {"mode": "delivery"}, False),
        ("delivery.set_address", {"address_text": "15 High Level Road, Maharagama"}, False),
        ("promo.apply", {"code": "FRIDAY10"}, False),
        ("order.show_summary", {}, False),
    ]

    for tool_name, args, _ in steps:
        res = registry.call(tool_name, session=session, args=args)
        print(f"=== {tool_name} ({args}) ===")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        if not res.get("ok"):
            clock.reset_clock()
            return 1

    # Simulate next customer message ("YES") by advancing message_count
    session.message_count += 1
    import tempfile
    from pathlib import Path
    from app.db.order_repo import OrderRepo

    with tempfile.TemporaryDirectory(prefix="cli_demo_") as tmp:
        demo_orders = OrderRepo(db_path=Path(tmp) / "demo_orders.db")
        place_res = registry.call(
            "order.place_order",
            session=session,
            args={"cart_hash": session.summary_hash},
            orders=demo_orders,
        )
    print("=== order.place_order ===")
    print(json.dumps(place_res, indent=2, ensure_ascii=False))
    clock.reset_clock()
    return 0 if place_res.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Phase 4 Tool CLI Harness")
    parser.add_argument("--demo", action="store_true", help="Run a complete scripted order flow")
    parser.add_argument("--user", default="cli_user", help="Session user_id")
    parser.add_argument("--tool", help="Tool name (e.g. cart.add_item)")
    parser.add_argument("--args", default="{}", help="JSON arguments string")
    parser.add_argument("--clock", default=None, help="Optional ISO timestamp to freeze clock")
    parsed = parser.parse_args()

    if parsed.clock:
        clock.set_clock(parsed.clock)

    if parsed.demo:
        return run_demo()

    if not parsed.tool:
        parser.print_help()
        return 1

    session = get_session(parsed.user)
    session.message_count += 1
    tool_args = json.loads(parsed.args)
    result = registry.call(parsed.tool, session=session, args=tool_args)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
