import unittest
from app.schemas import IncomingMessage, BrainReply
from app.state.session import get_session
from app.main import handle_message


class TestBrainAPI(unittest.TestCase):
    def test_schemas(self):
        req = IncomingMessage(
            user_id="9470000000",
            type="text",
            content="Hello",
            push_name="Ashen"
        )
        self.assertEqual(req.user_id, "9470000000")
        self.assertEqual(req.content, "Hello")

        res = BrainReply(reply_text="Welcome to Pizza Hut! 🍕")
        self.assertEqual(res.reply_text, "Welcome to Pizza Hut! 🍕")

    def test_session_state(self):
        session = get_session("test_user_123")
        session.add_history("user", "Hello")
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0]["content"], "Hello")

    def test_handle_message_route(self):
        msg = IncomingMessage(
            user_id="test_user_456",
            type="text",
            content="What are your vegetarian options?",
            push_name="Test"
        )
        reply = handle_message(msg)
        self.assertIsNotNone(reply.reply_text)
        self.assertGreater(len(reply.reply_text), 0)


if __name__ == "__main__":
    unittest.main()
