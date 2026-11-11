import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.escalation_agent import (
    BOT_ESCALATION_RULES_CLAUSES,
    CATEGORY_SAMPLE_PHRASES,
    escalation_agent,
)
from app.agents.orchestrator import orchestrator
from app.agents.post_order_agent import post_order_agent
from app.config import settings
from app.db.order_repo import OrderRepo, order_repo
from app.llm.client import LLMResponse
from app.schemas import IncomingMessage
from app.services import clock
from app.services.notifier import notifier
from app.state.session import Session, get_session_store
from app.tools.cart_tools import cart_add_item
from app.tools.delivery_tools import delivery_set_address
from app.tools.order_tools import order_place_order, order_show_summary


def _run_async(coro):
    """Drives an in-memory coroutine to completion without requiring OS loopback sockets."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value


class TestPhase7EscalationAndStaff(unittest.TestCase):
    def setUp(self):
        notifier.clear_events()
        notifier.set_transport(lambda jid, text: True)
        clock.set_clock("2026-11-13T18:00:00+05:30")  # Friday 6:00 PM (open)

    def tearDown(self):
        notifier.set_transport(None)
        notifier.clear_events()
        clock.reset_clock()

    def test_sync_with_bot_escalation_rules_markdown(self):
        """
        Verifies that every trigger clause in `internal/hr/bot-escalation-rules.md`
        is mapped in `BOT_ESCALATION_RULES_CLAUSES` and triggers `escalate=True`.
        """
        rules_md_path = (
            settings.KB_PATH / "internal" / "hr" / "bot-escalation-rules.md"
        )
        self.assertTrue(rules_md_path.exists())
        md_text = rules_md_path.read_text(encoding="utf-8").lower()

        for clause, category in BOT_ESCALATION_RULES_CLAUSES.items():
            self.assertIn(
                clause.lower(),
                md_text,
                f"Clause '{clause}' missing from bot-escalation-rules.md",
            )
            if category == "repeated_failures":
                s = Session(user_id="u_fail_3", consecutive_failures=3)
                decision = escalation_agent.evaluate("hello", session=s)
                self.assertTrue(decision.escalate)
                self.assertEqual(decision.category, "repeated_failures")
            else:
                sample = CATEGORY_SAMPLE_PHRASES[category]
                decision = escalation_agent.evaluate(sample)
                self.assertTrue(
                    decision.escalate,
                    f"Sample phrase for '{category}' did not trigger escalation: {sample}",
                )
                self.assertEqual(decision.category, category)

    def test_escalation_recall_and_low_false_positive_rate(self):
        must_escalate = [
            "I want to make a complaint about my cold pizza",
            "Give me a refund, I was charged twice",
            "I have a severe allergy to nuts, is this 100% safe?",
            "I got food poisoning and vomiting after eating your pizza",
            "You are a useless bot, worst service ever!",
            "Connect me to the branch manager right now",
        ]
        for phrase in must_escalate:
            dec = escalation_agent.evaluate(phrase)
            self.assertTrue(dec.escalate, f"Expected escalation for: {phrase}")

        ordinary_messages = [
            "Hello",
            "What vegetarian pizzas do you have?",
            "How much is a large Supreme?",
            "2 large Devilled Chicken please",
            "Add 1 Garlic Bread",
            "Deliver to Delkanda",
            "Can I pickup from Kandy?",
            "Use promo code FRIDAY10",
            "Do you have STUDENT15?",
            "What time does Colombo 07 close?",
            "Does Margherita contain dairy?",
            "Remove the garlic bread",
            "Show my cart",
            "Yes confirm",
            "No, that's all",
            "Thank you!",
        ]
        false_positives = [
            m for m in ordinary_messages if escalation_agent.evaluate(m).escalate
        ]
        self.assertEqual(len(false_positives), 0, f"Unexpected false positives: {false_positives}")

    def test_handoff_routing_and_after_hours_wording(self):
        # 1. Known branch (nugegoda), non-critical complaint during opening hours (18:00)
        s_nug = Session(user_id="u_nug_1", branch_id="nugegoda")
        res_open = escalation_agent.execute_handoff(
            session=s_nug,
            reason="Wrong pizza delivered",
            category="complaint",
            latest_user_message="You sent the wrong pizza",
        )
        self.assertEqual(s_nug.stage, "handoff")
        self.assertIn("within 30 minutes", res_open["data"]["customer_reply"])
        self.assertEqual(
            res_open["data"]["notified_jids"],
            [settings.STAFF_NOTIFY_JIDS["nugegoda"]],
        )

        # 2. Critical food-safety / severe allergy at kandy notifies BOTH kandy AND area manager
        s_kandy = Session(user_id="u_kandy_crit", branch_id="kandy")
        res_crit = escalation_agent.execute_handoff(
            session=s_kandy,
            reason="Severe nut allergy inquiry",
            category="severe_allergy",
            latest_user_message="I have anaphylaxis",
        )
        self.assertTrue(res_crit["data"]["is_critical"])
        self.assertEqual(
            res_crit["data"]["notified_jids"],
            [settings.STAFF_NOTIFY_JIDS["kandy"], settings.STAFF_NOTIFY_JIDS["area"]],
        )

        # 3. After hours (23:30) promises next morning by 11:00 instead of 30 minutes
        clock.set_clock("2026-11-13T23:30:00+05:30")
        s_closed = Session(user_id="u_late", branch_id="colombo07")
        res_closed = escalation_agent.execute_handoff(
            session=s_closed,
            reason="Late complaint",
            category="complaint",
        )
        self.assertFalse(res_closed["data"]["is_open_now"])
        self.assertIn("11:00", res_closed["data"]["customer_reply"])
        self.assertNotIn("within 30 minutes", res_closed["data"]["customer_reply"])

    def test_silence_during_handoff_and_staff_resume(self):
        async def _run():
            store = get_session_store()
            user_id = "u_handoff_flow"
            await store.delete(user_id)
            notifier.clear_events()

            # 1. Customer sends complaint -> triggers handoff & replies once
            reply_1 = await orchestrator.handle_message(
                IncomingMessage(
                    user_id=user_id,
                    type="text",
                    content="I want to make a complaint about my cold pizza",
                    message_id="m_h1",
                )
            )
            self.assertIsNotNone(reply_1.reply_text)
            self.assertEqual(reply_1.meta.stage, "handoff")
            handoff_events = [
                e for e in notifier.sent_events if e["event_type"] == "handoff"
            ]
            self.assertEqual(len(handoff_events), 1)

            # 2. Customer sends a follow-up while in handoff -> bot stays SILENT and forwards to staff
            reply_2 = await orchestrator.handle_message(
                IncomingMessage(
                    user_id=user_id,
                    type="text",
                    content="My order number was PH-20261113-0001",
                    message_id="m_h2",
                )
            )
            self.assertIsNone(reply_2.reply_text)
            self.assertEqual(reply_2.meta.stage, "handoff")
            followup_events = [
                e for e in notifier.sent_events if e["event_type"] == "handoff_followup"
            ]
            self.assertEqual(len(followup_events), 1)
            self.assertIn("PH-20261113-0001", followup_events[0]["text"])

            # 3. Area manager sends `/resume u_handoff_flow` -> returns customer to bot
            area_staff_id = settings.STAFF_NOTIFY_JIDS["area"]
            staff_reply = await orchestrator.handle_message(
                IncomingMessage(
                    user_id=area_staff_id,
                    type="text",
                    content=f"/resume {user_id}",
                    message_id="m_staff_res_1",
                )
            )
            self.assertIn("Resumed bot", staff_reply.reply_text)

            # 4. Customer can now talk to the bot again
            with patch(
                "app.agents.orchestrator.llm_client.complete",
                return_value=LLMResponse(
                    text="Welcome back! How can I help you?", tool_calls=[], model="fake"
                ),
            ):
                reply_3 = await orchestrator.handle_message(
                    IncomingMessage(
                        user_id=user_id,
                        type="text",
                        content="Hi again",
                        message_id="m_h3",
                    )
                )
                self.assertEqual(reply_3.reply_text, "Welcome back! How can I help you?")
                self.assertEqual(reply_3.meta.stage, "browsing")

        _run_async(_run())

    def test_three_consecutive_tool_failures_trigger_handoff(self):
        async def _run():
            store = get_session_store()
            user_id = "u_three_fails"
            await store.delete(user_id)

            # Script LLM to call a tool with invalid args 3 times in a row
            def failing_tool_llm(system, messages, **kwargs):
                return LLMResponse(
                    text="",
                    tool_calls=[
                        {
                            "id": "tc_bad_1",
                            "function": {
                                "name": "cart.add_item",
                                "arguments": '{"item_id": "non_existent_item_1", "size": "large", "qty": 1}',
                            },
                        },
                        {
                            "id": "tc_bad_2",
                            "function": {
                                "name": "cart.add_item",
                                "arguments": '{"item_id": "non_existent_item_2", "size": "large", "qty": 1}',
                            },
                        },
                        {
                            "id": "tc_bad_3",
                            "function": {
                                "name": "cart.add_item",
                                "arguments": '{"item_id": "non_existent_item_3", "size": "large", "qty": 1}',
                            },
                        },
                    ],
                    model="fake",
                )

            with patch(
                "app.agents.orchestrator.llm_client.complete",
                side_effect=failing_tool_llm,
            ):
                reply = await orchestrator.handle_message(
                    IncomingMessage(
                        user_id=user_id,
                        type="text",
                        content="Add three mystery items",
                        message_id="m_fail3",
                    )
                )
                self.assertEqual(reply.meta.stage, "handoff")
                self.assertIn("staff member", reply.reply_text)

        _run_async(_run())

    def test_post_order_exact_once_notification_and_branch_scoped_staff_commands(self):
        async def _run():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                temp_repo = OrderRepo(db_path=Path(tmp) / "test_phase7.db")
                store = get_session_store()
                cust_id = "94712345678"
                await store.delete(cust_id)
                session = await store.get(cust_id)

                # Build a valid Nugegoda delivery order
                cart_add_item(session, item_id="pz_supreme", size="large", qty=1)
                delivery_set_address(session, address_text="Delkanda")
                self.assertEqual(session.branch_id, "nugegoda")
                session.message_count = 1
                sum_res = order_show_summary(session)
                self.assertTrue(sum_res["ok"])
                h = sum_res["data"]["summary_hash"]

                # Simulate notifier failure during place_order -> order placement MUST still succeed!
                def failing_transport(jid, text):
                    raise RuntimeError("Simulated gateway connection refused")

                notifier.set_transport(failing_transport)
                session.message_count = 2
                place_res = order_place_order(session, cart_hash=h, orders=temp_repo)
                self.assertTrue(place_res["ok"], "Notifier failure must never break order placement")
                order_no = place_res["data"]["order_no"]

                # Calling on_order_placed again for the same order_no must NOT duplicate the notification
                persisted = temp_repo.get_order_by_no(order_no)
                self.assertIsNotNone(persisted)
                duplicate_sent = post_order_agent.on_order_placed(persisted)
                self.assertFalse(duplicate_sent, "Each new order must be notified to its branch exactly once")

                new_order_events = [
                    e for e in notifier.sent_events if e["event_type"] == "new_order"
                ]
                self.assertEqual(len(new_order_events), 1)
                self.assertEqual(
                    new_order_events[0]["jid"], settings.STAFF_NOTIFY_JIDS["nugegoda"]
                )

                # Restore working transport for staff command tests
                notifier.set_transport(lambda jid, text: True)

                # 1. Non-staff sender trying `/status` is ignored by staff handler (returns None)
                non_staff_res = await post_order_agent.handle_staff_command(
                    sender_user_id="94709999999",
                    raw_text=f"/status {order_no} accepted",
                    store=store,
                    orders=temp_repo,
                )
                self.assertIsNone(non_staff_res)

                # 2. Kandy staff number CANNOT update a Nugegoda order!
                kandy_staff = settings.STAFF_NOTIFY_JIDS["kandy"]
                kandy_attempt = await post_order_agent.handle_staff_command(
                    sender_user_id=kandy_staff,
                    raw_text=f"/status {order_no} accepted",
                    store=store,
                    orders=temp_repo,
                )
                self.assertIn("Access denied", kandy_attempt)
                self.assertEqual(
                    temp_repo.get_order_by_no(order_no).status.value, "new"
                )

                # 3. Nugegoda staff number CAN update its own branch's order -> customer gets notified!
                nug_staff = settings.STAFF_NOTIFY_JIDS["nugegoda"]
                nug_attempt = await post_order_agent.handle_staff_command(
                    sender_user_id=nug_staff,
                    raw_text=f"/status {order_no} out_for_delivery",
                    store=store,
                    orders=temp_repo,
                )
                self.assertIn("updated to *out_for_delivery*", nug_attempt)
                self.assertEqual(
                    temp_repo.get_order_by_no(order_no).status.value,
                    "out_for_delivery",
                )
                status_events = [
                    e
                    for e in notifier.sent_events
                    if e["event_type"] == "order_status_update"
                ]
                self.assertEqual(len(status_events), 1)
                self.assertEqual(status_events[0]["jid"], cust_id)
                self.assertIn("out for delivery", status_events[0]["text"])

                # 4. Area manager can view `/orders` across all branches
                area_staff = settings.STAFF_NOTIFY_JIDS["area"]
                orders_list_reply = await post_order_agent.handle_staff_command(
                    sender_user_id=area_staff,
                    raw_text="/orders",
                    store=store,
                    orders=temp_repo,
                )
                self.assertIn(order_no, orders_list_reply)

        _run_async(_run())


if __name__ == "__main__":
    unittest.main()
