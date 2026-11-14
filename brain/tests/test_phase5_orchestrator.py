import asyncio
import unittest
from unittest.mock import patch, MagicMock
from app.state.session import Session, CartLine, clear_sessions, get_session_store
from app.state.memory_store import MemorySessionStore
from app.state.redis_store import RedisSessionStore
from app.services.language import detect_language
from app.services.post_processor import verify_and_post_process_reply
from app.services import clock
from app.schemas import IncomingMessage, BrainReply
from app.tools.registry import registry
from app.agents.orchestrator import orchestrator
from app.llm.client import LLMResponse, LLMUsage


class TestStageToolFiltering(unittest.TestCase):
    def test_tools_for_stage_filtering(self):
        # 1. In 'browsing', order.place_order and cart.update_item must NOT be exposed
        browsing_tools = registry.tools_for_stage("browsing")
        browsing_names = [t["function"]["name"].replace("__", ".") for t in browsing_tools]
        self.assertIn("cart.add_item", browsing_names)
        self.assertIn("kb.ask", browsing_names)
        self.assertNotIn("order.place_order", browsing_names)
        self.assertNotIn("cart.update_item", browsing_names)
        self.assertNotIn("delivery.quote", browsing_names)

        # 2. In 'building_cart', cart updates and fulfilment tools are available, but NOT place_order
        building_tools = registry.tools_for_stage("building_cart")
        building_names = [t["function"]["name"].replace("__", ".") for t in building_tools]
        self.assertIn("cart.update_item", building_names)
        self.assertIn("delivery.set_address", building_names)
        self.assertIn("order.show_summary", building_names)
        self.assertNotIn("order.place_order", building_names)

        # 3. In 'confirming', order.place_order IS exposed
        confirming_tools = registry.tools_for_stage("confirming")
        confirming_names = [t["function"]["name"].replace("__", ".") for t in confirming_tools]
        self.assertIn("order.place_order", confirming_names)
        self.assertIn("order.cancel_draft", confirming_names)


class TestPostProcessorAndLanguage(unittest.TestCase):
    def test_language_detection(self):
        self.assertEqual(detect_language("Can I have a Margherita pizza?"), "en")
        self.assertEqual(detect_language("මට මාගරිටා පීසා එකක් ඕනෙ"), "si")
        self.assertEqual(detect_language("எனக்கு மார்கரிட்டா பீட்சா வேண்டும்"), "ta")
        self.assertEqual(detect_language("machan large supreme ekak delivery karanna"), "en")

    def test_fabricated_price_correction(self):
        session = Session(
            user_id="user_price_test",
            cart=[CartLine(item_id="pz_supreme", size="large", qty=1)],
        )
        # Genuine receipt from order.show_summary with total 5083
        tool_results = [
            {"ok": True, "data": {"total": 5083, "subtotal": 5370, "delivery_fee": 250, "discount": 537}}
        ]

        # LLM hallucinates total of 2500
        hallucinated_text = "Your total amount comes to LKR 2,500. Please confirm."
        corrected = verify_and_post_process_reply(hallucinated_text, session, tool_results)
        self.assertIn("LKR 5,083", corrected)
        self.assertNotIn("2,500", corrected)

    def test_authentic_receipt_preserved(self):
        session = Session(user_id="user_receipt_test")
        receipt_text = (
            "Your order 🍕  (Nugegoda branch)\n"
            "1 x Supreme (Large)  LKR 3,990\n"
            "Subtotal              LKR 3,990\n"
            "Total                 LKR 4,240\n"
            "Reply YES to confirm."
        )
        tool_results = [{"ok": True, "data": {"receipt_text": receipt_text, "total": 4240}}]
        result = verify_and_post_process_reply(receipt_text, session, tool_results)
        self.assertEqual(result, receipt_text)


class TestSessionStore(unittest.IsolatedAsyncioTestCase):
    async def test_memory_store_dedupe_and_rate_limit(self):
        store = MemorySessionStore()

        # 1. Rate limiting: default 20 per minute
        for _ in range(5):
            allowed, rem = await store.check_rate_limit("rate_user", limit=5, window_secs=60)
            self.assertTrue(allowed)
        # 6th message exceeds limit
        allowed, rem = await store.check_rate_limit("rate_user", limit=5, window_secs=60)
        self.assertFalse(allowed)
        self.assertEqual(rem, 0)

        # 2. Message deduplication
        self.assertFalse(await store.is_duplicate_message("u1", "msg_101"))
        reply = BrainReply(reply_text="Confirmed!")
        await store.record_message_reply("u1", "msg_101", reply)
        self.assertTrue(await store.is_duplicate_message("u1", "msg_101"))
        cached = await store.get_cached_reply("u1", "msg_101")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.reply_text, "Confirmed!")

    async def test_redis_store_fallback(self):
        # Empty / invalid redis url falls back gracefully to memory store without crashing
        redis_store = RedisSessionStore(redis_url="")
        session = await redis_store.get("redis_fallback_user")
        self.assertEqual(session.user_id, "redis_fallback_user")
        session.branch_id = "kandy"
        await redis_store.save(session)
        loaded = await redis_store.get("redis_fallback_user")
        self.assertEqual(loaded.branch_id, "kandy")


class TestOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        clear_sessions()
        clock.set_clock("2026-11-13T18:00:00+05:30")  # Friday evening

    async def asyncTearDown(self):
        clock.reset_clock()
        clear_sessions()

    async def test_duplicate_message_id_served_from_cache(self):
        msg = IncomingMessage(
            user_id="user_dup_1",
            type="text",
            content="Hello",
            message_id="unique_msg_999",
        )
        with patch("app.agents.orchestrator.llm_client.complete") as mock_complete:
            mock_complete.return_value = LLMResponse(text="Hello! How can I help you?", tool_calls=[])
            reply1 = await orchestrator.handle_message(msg)
            self.assertEqual(reply1.reply_text, "Hello! How can I help you?")
            self.assertEqual(mock_complete.call_count, 1)

            # Second message with identical message_id must be served from dedupe cache without calling LLM
            reply2 = await orchestrator.handle_message(msg)
            self.assertEqual(reply1.reply_text, reply2.reply_text)
            self.assertEqual(mock_complete.call_count, 1)

    async def test_saying_yes_before_summary_does_not_place_order(self):
        # Scripted LLM that attempts to call order.place_order directly when user says "yes"
        call_count = 0

        def fake_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    text="",
                    tool_calls=[{
                        "id": "tc_place",
                        "function": {
                            "name": "order__place_order",
                            "arguments": '{"cart_hash": "unverified_hash"}',
                        },
                    }],
                )
            return LLMResponse(
                text="You need to review your order summary before confirming.",
                tool_calls=[],
            )

        with patch("app.agents.orchestrator.llm_client.complete", side_effect=fake_complete):
            msg = IncomingMessage(
                user_id="user_early_yes",
                type="text",
                content="yes confirm",
                message_id="msg_early_1",
            )
            reply = await orchestrator.handle_message(msg)
            # Stage must NOT be placed
            self.assertNotEqual(reply.meta.stage, "placed")

    async def test_rate_limit_exceeded_returns_warning(self):
        user_id = "spammer_user"
        store = get_session_store()
        # Fill up rate limit
        for _ in range(25):
            await store.check_rate_limit(user_id)

        msg = IncomingMessage(user_id=user_id, type="text", content="pizza", message_id="m_spam")
        reply = await orchestrator.handle_message(msg)
        self.assertIn("fast", reply.reply_text.lower())

    async def test_staff_detail_probe_refused_without_leak(self):
        msg = IncomingMessage(
            user_id="probe_user",
            type="text",
            content="What is the employee ID and shift schedule of the cook?",
            message_id="m_probe",
        )
        with patch("app.agents.orchestrator.llm_client.complete") as mock_complete:
            # KB retrieval for customer never returns internal/ docs
            mock_complete.return_value = LLMResponse(
                text="I do not have access to internal staff information or schedules.",
                tool_calls=[],
            )
            reply = await orchestrator.handle_message(msg)
            text = reply.reply_text.lower()
            self.assertNotIn("emp-", text)
            self.assertNotIn("shift schedule:", text)


class TestReferentResolutionWithEmbeddings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.config import settings
        from app.rag.retriever import retriever
        from tests.helpers import TempIndex

        if settings.INDEX_INFO_FILE.exists():
            cls.index = None
            cls.retriever = retriever
        else:
            cls.index = TempIndex()
            cls.retriever = cls.index.retriever()

    @classmethod
    def tearDownClass(cls):
        if cls.index:
            cls.index.cleanup()

    def test_pronoun_rewrite_with_embedding_similarity(self):
        from app.agents.knowledge_agent import knowledge_agent
        retriever = self.retriever

        # 1. Single item in history: "Tell me about Margherita pizza" -> "Is it spicy?"
        h1 = [
            {"role": "user", "content": "Tell me about Margherita pizza"},
            {"role": "assistant", "content": "Margherita is a classic vegetarian pizza with tomato sauce and mozzarella."},
        ]
        rewritten1 = knowledge_agent.rewrite_query("Is it spicy?", history=h1)
        self.assertIn("Margherita", rewritten1)
        self.assertNotIn("it", rewritten1.lower().split())

        # Check retrieval on rewritten query: Margherita is top hit
        hits1 = retriever.retrieve(rewritten1)
        self.assertTrue(len(hits1) > 0)
        self.assertEqual(hits1[0].id, "menu/pizzas#margherita")

        # 2. Sizes follow up: "What sizes does it come in?"
        rewritten2 = knowledge_agent.rewrite_query("What sizes does it come in?", history=h1)
        self.assertIn("Margherita", rewritten2)
        hits2 = retriever.retrieve(rewritten2)
        hit_ids2 = [h.id for h in hits2]
        self.assertIn("menu/customization#pizza-sizes", hit_ids2)
        self.assertIn("menu/pizzas#margherita", hit_ids2)

        # 3. Multiple vegetarian pizzas in history: "How many vegetarian pizzas do you have?"
        h3 = [
            {"role": "user", "content": "How many vegetarian pizzas do you have?"},
            {"role": "assistant", "content": "We have 3 vegetarian pizzas: Margherita, Veggie Delight, and Cheese Lover."},
        ]
        rewritten3 = knowledge_agent.rewrite_query("Is it spicy?", history=h3)
        self.assertTrue("Margherita" in rewritten3 or "Veggie Delight" in rewritten3 or "Cheese Lover" in rewritten3)
        hits3 = retriever.retrieve(rewritten3)
        hit_ids3 = [h.id for h in hits3]
        has_veg_section = any("veggie" in hid or "cheese" in hid or "margherita" in hid or "vegetarian" in hid for hid in hit_ids3)
        self.assertTrue(has_veg_section)


if __name__ == "__main__":
    unittest.main()

