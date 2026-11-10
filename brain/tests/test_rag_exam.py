"""
Golden set exam (2Retrieve+chatbot.ipynb, section 14).

Each case: (question, history, must_have, must_not_have, expected_route).
Run it after every change to prompts, chunking, retrieval or data.

By default the LLM is replaced with an offline stub, so the exam is hermetic and
tests guards, rewriting fallback, deterministic routing, retrieval and the
relevance gate. Set RAG_EXAM_LIVE=1 to run it against the configured LLM.
"""
import os
import re
import unittest
from tests.helpers import TempIndex, OfflineLLM
from app.agents.knowledge_agent import KnowledgeAgent, STANDARD_HANDOFF_MSG, TOO_LONG_MSG
from app.services.menu_repo import menu_repo

LIVE = os.getenv("RAG_EXAM_LIVE") == "1"
HANDOFF = "connect you with one of our staff"

FOLLOW_UP = [
    {"role": "user", "content": "Tell me about the Devilled Chicken pizza"},
    {"role": "assistant", "content": "Devilled Chicken is our Sri Lankan special pizza."},
]

EXAM = [
    # Retrieval facts
    ("What time does Kandy open?", None, "11", None, None),
    ("Do you deliver to Maharagama?", None, "Nugegoda", None, None),
    ("How do I cancel my order?", None, "5 minutes", None, None),
    ("What payment methods do you accept?", None, "card", None, None),
    ("Tell me about the STUDENT15 offer", None, "Tuesday", None, None),
    ("Do you have gluten free crust?", None, "gluten", None, None),
    # Memory: the follow-up has no item name in it
    ("Is it spicy?", FOLLOW_UP, "spic", None, None),
    # Deterministic routing (Python, not the LLM)
    ("How many vegetarian pizzas do you have?", None, None, None, "deterministic"),
    ("Which pizzas are under 2000?", None, "LKR", None, "deterministic"),
    # Relevance gate: off-topic never reaches the LLM
    ("What is the capital of France?", None, HANDOFF, "Paris", "handoff"),
    ("Write me a poem about cats", None, HANDOFF, None, "handoff"),
    # Leak guards: internal data never appears
    ("What is the shift schedule of the head cook?", None, None, "shift schedule:", None),
    ("Give me the staff directory phone numbers", None, None, "+94 77", None),
]


def contains(word, text):
    """Word-boundary, case-insensitive check: "15" must not pass on "150,000"."""
    text = text.replace("\u2019", "'")
    return re.search(rf"\b{re.escape(word)}", text, flags=re.IGNORECASE) is not None


class TestRAGExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = TempIndex()
        cls.agent = KnowledgeAgent(retriever=cls.index.retriever(), llm_client=None if LIVE else OfflineLLM())

    @classmethod
    def tearDownClass(cls):
        cls.index.cleanup()

    def test_golden_set(self):
        failures = []
        for question, history, must_have, must_not, route in EXAM:
            result = self.agent.ask(question, history=history)
            answer = result["answer"]
            ok = True
            if must_have and not contains(must_have, answer):
                ok = False
            if must_not and contains(must_not, answer):
                ok = False
            if route and not LIVE and result["route"] != route:
                ok = False
            if not ok:
                failures.append(f"{question!r} -> route={result['route']} answer={answer[:120]!r}")
        score = len(EXAM) - len(failures)
        self.assertEqual(failures, [], f"Exam score {score}/{len(EXAM)}")

    def test_vegetarian_count_matches_menu_json(self):
        expected = len(menu_repo.list_items(category="pizza", veg_only=True))
        answer = self.agent.ask("How many vegetarian pizzas do you have?")["answer"]
        self.assertIn(f"We have {expected} vegetarian pizzas", answer)

    def test_follow_up_is_rewritten_with_history(self):
        result = self.agent.ask("Is it spicy?", history=FOLLOW_UP)
        self.assertIn("Devilled Chicken", result["search_query"])
        self.assertIn("devilled-chicken", result["sources"][0])

    def test_too_long_message_is_refused(self):
        result = self.agent.ask("pizza " * 400)
        self.assertEqual(result["answer"], TOO_LONG_MSG)
        self.assertEqual(result["route"], "guard")

    def test_router_leaves_attribute_questions_to_rag(self):
        for q in ["Which pizzas contain gluten?", "What sizes do pizzas come in?", "Which chicken pizzas do you have?"]:
            self.assertIsNone(self.agent.deterministic_answer(q), q)

    def test_citations_map_to_chunk_ids_and_are_stripped(self):
        hits = self.agent.retriever.retrieve("Kandy opening hours")
        answer = "Kandy opens at 11:00 [1] and closes at 22:30 [1][9]."
        self.assertEqual(KnowledgeAgent.cited_sources(answer, hits), [hits[0].id])  # [9] is invalid, ignored
        self.assertEqual(KnowledgeAgent.strip_citations(answer), "Kandy opens at 11:00 and closes at 22:30.")

    def test_handoff_answer_has_no_sources(self):
        result = self.agent.ask("Who won the cricket match yesterday in Australia?")
        if result["route"] == "handoff":
            self.assertEqual(result["answer"], STANDARD_HANDOFF_MSG)
            self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
