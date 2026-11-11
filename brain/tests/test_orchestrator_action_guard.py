import unittest
from unittest.mock import patch

from app.agents.orchestrator import orchestrator
from app.llm.client import LLMResponse
from app.schemas import IncomingMessage
from app.services import clock
from app.services.action_guard import (
    check_reply,
    detect_claims,
    extract_order_numbers,
)
from app.services.post_processor import find_unverified_prices
from app.state.session import Session, get_session_store
from app.tools.cart_tools import cart_add_item
from app.tools.delivery_tools import delivery_set_address
from app.tools.order_tools import order_show_summary


def _run_async(coro):
    """Drives an in-memory coroutine to completion without needing OS loopback sockets."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value


def _tc(call_id, name, args_json):
    return {"id": call_id, "function": {"name": name, "arguments": args_json}}


class TestActionClaimDetection(unittest.TestCase):
    def test_phantom_claims_from_the_live_transcript_are_detected(self):
        self.assertIn("cart_add", detect_claims("Added garlic bread. Anything else?"))
        self.assertIn("cart_update", detect_claims("Updated: 1 large Margherita (3490 LKR). Anything else?"))
        self.assertIn(
            "promo_applied",
            detect_claims("Applied promo STUDENT15 (15% off). Please show your student ID."),
        )
        self.assertIn("order_placed", detect_claims("Order placed! 🍕\nOrder No: 1001"))

    def test_questions_conditions_and_failures_are_not_claims(self):
        harmless = [
            "Would you like me to add a garlic bread?",
            "I couldn't add that item because it is unavailable.",
            "That code can't be applied on a Wednesday.",
            "Once you confirm, your order will be placed.",
            "If you want, I can remove the garlic bread.",
            "The promo wasn't applied because the cart is empty.",
            "Reply YES to confirm your order.",
            "We have 3 vegetarian pizzas: Margherita, Veggie Delight and Cheese Lover.",
        ]
        for text in harmless:
            self.assertEqual(detect_claims(text), set(), f"False positive: {text}")

    def test_claims_backed_by_successful_tools_pass(self):
        self.assertFalse(check_reply("Added garlic bread.", {"cart.add_item"}).has_problem)
        self.assertFalse(check_reply("Applied promo STUDENT15.", {"promo.apply"}).has_problem)
        # double-underscore tool names from the LLM are normalised
        self.assertFalse(check_reply("Added garlic bread.", {"cart__add_item"}).has_problem)

    def test_claims_without_matching_tool_fail(self):
        self.assertEqual(check_reply("Added garlic bread.", set()).unsupported, ["cart_add"])
        # a different successful tool does not back an add claim
        self.assertEqual(check_reply("Added garlic bread.", {"promo.apply"}).unsupported, ["cart_add"])

    def test_fabricated_order_numbers(self):
        report = check_reply("Order placed! Order No: 1001", set(), valid_order_nos=[])
        self.assertIn("order_placed", report.unsupported)
        self.assertEqual(report.fabricated_order_numbers, ["1001"])

        real = "PH-20261117-0001"
        ok = check_reply(f"Order placed! Your order number is {real}.", {"order.place_order"}, [real])
        self.assertFalse(ok.has_problem)

        # A real, earlier order number mentioned later is not fabricated
        later = check_reply(f"Your order {real} is confirmed and on its way.", set(), [real])
        self.assertFalse(later.has_problem)

        self.assertIn("PH-20261117-0001", extract_order_numbers("Ref PH-20261117-0001 thanks"))


class TestPriceGuard(unittest.TestCase):
    def setUp(self):
        clock.set_clock("2026-11-17T19:00:00+05:30")

    def tearDown(self):
        clock.reset_clock()

    def test_suffix_style_fabricated_price_is_caught(self):
        s = Session(user_id="u_price")
        self.assertEqual(find_unverified_prices("A large Margherita is 9999 LKR.", s, [], "price?"), [9999])
        self.assertEqual(find_unverified_prices("A large Margherita is LKR 9,999.", s, [], "price?"), [9999])

    def test_real_menu_prices_and_user_thresholds_are_allowed(self):
        s = Session(user_id="u_price2")
        self.assertEqual(find_unverified_prices("A large Margherita is 3490 LKR.", s, [], "price?"), [])
        self.assertEqual(
            find_unverified_prices("Pizzas under LKR 2500:", s, [], "which pizzas are under LKR 2500?"), []
        )

    def test_prices_inside_tool_text_are_allowed(self):
        s = Session(user_id="u_price3")
        tool = {"ok": True, "data": {"answer": "Garlic bread is LKR 790 and wings LKR 1,290."}}
        self.assertEqual(find_unverified_prices("Garlic bread is LKR 790.", s, [tool], "?"), [])

    def test_official_receipt_is_not_flagged(self):
        s = Session(user_id="u_receipt")
        cart_add_item(s, item_id="pz_margherita", size="large", qty=2)
        delivery_set_address(s, address_text="Delkanda")
        s.message_count = 1
        summary = order_show_summary(s)
        self.assertTrue(summary["ok"], summary)
        receipt = summary["data"]["receipt_text"]
        self.assertEqual(find_unverified_prices(receipt, s, [summary], "no that's all"), [])
        self.assertFalse(check_reply(receipt, {"order.show_summary"}, []).has_problem)


class TestOrchestratorActionGuard(unittest.TestCase):
    def setUp(self):
        clock.set_clock("2026-11-17T19:00:00+05:30")  # Tuesday evening

    def tearDown(self):
        clock.reset_clock()

    def _send(self, user_id, text, message_id):
        return _run_async(
            orchestrator.handle_message(
                IncomingMessage(user_id=user_id, type="text", content=text, message_id=message_id)
            )
        )

    def _fresh_session(self, user_id):
        store = get_session_store()
        _run_async(store.delete(user_id))
        return _run_async(store.get(user_id))

    def test_phantom_add_is_forced_into_a_real_tool_call(self):
        user_id = "u_guard_add"
        self._fresh_session(user_id)
        calls = []

        def fake_complete(system, messages, model=None, tools=None, temperature=None, tool_choice="auto", **kw):
            calls.append(tool_choice)
            if messages[-1].get("role") == "tool":
                return LLMResponse(text="Added 1 large Margherita. Anything else?", tool_calls=[], model="fake")
            if tool_choice == "required":
                return LLMResponse(
                    text="",
                    tool_calls=[_tc("c1", "cart__add_item", '{"item_id": "pz_margherita", "size": "large", "qty": 1}')],
                    model="fake",
                )
            return LLMResponse(text="Added 1 large Margherita. Anything else?", tool_calls=[], model="fake")

        with patch("app.agents.orchestrator.llm_client.complete", side_effect=fake_complete):
            reply = self._send(user_id, "add a large margherita", "g_add_1")

        session = _run_async(get_session_store().get(user_id))
        self.assertEqual([(c.item_id, c.size, c.qty) for c in session.cart], [("pz_margherita", "large", 1)])
        self.assertIn("required", calls, "The corrective retry must force tool use")
        self.assertIn("Added", reply.reply_text)

    def test_phantom_promo_is_forced_into_a_real_tool_call(self):
        user_id = "u_guard_promo"
        session = self._fresh_session(user_id)
        cart_add_item(session, item_id="pz_supreme", size="large", qty=1)
        delivery_set_address(session, address_text="Delkanda")  # Nugegoda; STUDENT15 valid on Tuesday
        _run_async(get_session_store().save(session))

        def fake_complete(system, messages, model=None, tools=None, temperature=None, tool_choice="auto", **kw):
            if messages[-1].get("role") == "tool":
                return LLMResponse(text="Applied promo STUDENT15 (15% off).", tool_calls=[], model="fake")
            if tool_choice == "required":
                return LLMResponse(
                    text="", tool_calls=[_tc("p1", "promo__apply", '{"code": "STUDENT15"}')], model="fake"
                )
            return LLMResponse(text="Applied promo STUDENT15 (15% off).", tool_calls=[], model="fake")

        with patch("app.agents.orchestrator.llm_client.complete", side_effect=fake_complete):
            self._send(user_id, "apply promo STUDENT15", "g_promo_1")

        after = _run_async(get_session_store().get(user_id))
        self.assertEqual(after.promo_code, "STUDENT15")

    def test_fabricated_order_number_never_reaches_the_customer(self):
        user_id = "u_guard_fake_order"
        self._fresh_session(user_id)
        calls = []

        def stubborn_liar(system, messages, model=None, tools=None, temperature=None, tool_choice="auto", **kw):
            calls.append(tool_choice)
            return LLMResponse(text="Order placed! 🍕\nOrder No: 1001", tool_calls=[], model="fake")

        with patch("app.agents.orchestrator.llm_client.complete", side_effect=stubborn_liar):
            reply = self._send(user_id, "yes", "g_fake_1")

        session = _run_async(get_session_store().get(user_id))
        self.assertNotIn("1001", reply.reply_text)
        self.assertNotEqual(session.stage, "placed")
        self.assertIn("haven't placed", reply.reply_text)
        self.assertEqual(len(calls), 3, "initial call + 2 forced corrections, then honest fallback")

    def test_honest_reply_needs_no_correction(self):
        user_id = "u_guard_honest"
        self._fresh_session(user_id)
        calls = []

        def honest(system, messages, model=None, tools=None, temperature=None, tool_choice="auto", **kw):
            calls.append(tool_choice)
            return LLMResponse(text="Hello! What would you like to order today? 🍕", tool_calls=[], model="fake")

        with patch("app.agents.orchestrator.llm_client.complete", side_effect=honest):
            reply = self._send(user_id, "hi", "g_hi_1")

        self.assertEqual(calls, ["auto"])
        self.assertIn("Hello", reply.reply_text)

    def test_state_block_exposes_indexed_cart_lines(self):
        session = Session(user_id="u_state_block")
        cart_add_item(session, item_id="pz_margherita", size="large", qty=2)
        cart_add_item(session, item_id="pz_supreme", size="medium", qty=1)
        block = orchestrator._build_state_block(session)
        self.assertIn("[0] 2 x Margherita (large)", block)
        self.assertIn("[1] 1 x Supreme (medium)", block)


if __name__ == "__main__":
    unittest.main()

