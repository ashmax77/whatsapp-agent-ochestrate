import unittest
from app.rag.retriever import retriever


class TestRAGRetrieval(unittest.TestCase):
    def test_customer_retrieval(self):
        hits = retriever.retrieve("vegetarian pizza options")
        self.assertGreater(len(hits), 0)
        # Verify hits are all audience == customer
        for h in hits:
            self.assertEqual(h.meta.get("audience"), "customer")
            self.assertNotIn("internal", h.id)

    def test_security_leak_probes_never_return_internal_chunks(self):
        """
        D17 Defense-in-depth: Probes attempting to extract employee IDs,
        staff schedules, or HR policies must return ZERO internal chunks.
        """
        probes = [
            "employee ID of the Nugegoda head cook",
            "who works the evening shift today?",
            "leave policy and attendance for staff",
            "bot escalation rules for HR staff",
            "internal staff directory phone numbers",
            "code of conduct for employees"
        ]

        for probe in probes:
            hits = retriever.retrieve(probe, k=10)
            for h in hits:
                self.assertNotEqual(
                    h.meta.get("audience"),
                    "internal",
                    f"LEAK DETECTED: Probe '{probe}' returned internal chunk '{h.id}'"
                )
                self.assertFalse(
                    h.id.startswith("internal/"),
                    f"LEAK DETECTED: Chunk ID '{h.id}' is from internal directory"
                )


if __name__ == "__main__":
    unittest.main()

