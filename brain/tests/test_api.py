import unittest
from app.schemas import ChatRequest, ChatResponse
from app.state.session import session_manager

class TestBrainLogic(unittest.TestCase):
    def test_schemas(self):
        req = ChatRequest(senderId="12345@s.whatsapp.net", message="Hello")
        self.assertEqual(req.senderId, "12345@s.whatsapp.net")
        self.assertEqual(req.message, "Hello")

        res = ChatResponse(reply="Welcome!")
        self.assertEqual(res.reply, "Welcome!")

    def test_session_manager(self):
        session = session_manager.get_or_create("12345@s.whatsapp.net")
        session.add_message("user", "Hello")
        self.assertEqual(len(session.history), 1)
        self.assertEqual(session.history[0]["content"], "Hello")

if __name__ == "__main__":
    unittest.main()
