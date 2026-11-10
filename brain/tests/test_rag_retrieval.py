import json
import shutil
import time
import unittest
from tests.helpers import TempIndex
from app.rag.retriever import BM25Okapi, KnowledgeRetriever
from app.rag.text import tokenize
from app.rag.embeddings import embedding_service, LOCAL_BACKEND


class TestRAGRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = TempIndex()
        cls.retriever = cls.index.retriever()

    @classmethod
    def tearDownClass(cls):
        cls.index.cleanup()

    def test_customer_retrieval(self):
        hits = self.retriever.retrieve("vegetarian pizza options")
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
            hits = self.retriever.retrieve(probe, k=10, min_score=0.0)
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

    def test_keyword_search_finds_exact_promo_code(self):
        hits = self.retriever.retrieve("What is the STUDENT15 offer?")
        self.assertTrue(hits)
        self.assertEqual(hits[0].id, "offers/current-offers#student-tuesday-code-student15")

    def test_hybrid_finds_named_item(self):
        hits = self.retriever.retrieve("Is the devilled chicken pizza spicy?")
        self.assertIn("devilled-chicken", hits[0].id)

    def test_off_topic_questions_return_no_hits(self):
        for q in ["What is the capital of France?", "Write me a poem about cats", "What is the weather tomorrow?"]:
            self.assertEqual(self.retriever.retrieve(q), [], q)

    def test_hits_sorted_and_limited(self):
        hits = self.retriever.retrieve("delivery fee and delivery areas", k=3)
        self.assertLessEqual(len(hits), 3)
        self.assertEqual([h.score for h in hits], sorted([h.score for h in hits], reverse=True))


class TestRBAC(unittest.TestCase):
    """Search-time access control on an index that DOES contain an internal chunk."""

    @classmethod
    def setUpClass(cls):
        cls.index = TempIndex()
        info = json.loads(cls.index.manifest.read_text(encoding="utf-8"))
        data_file = cls.index.dir / info["index_path"] / "index.json"
        docs = json.loads(data_file.read_text(encoding="utf-8"))
        secret = "Document: internal/employees - Staff\nSection: Night shift\n\nNimal Perera works the night shift roster."
        docs.append({
            "id": "internal/employees/staff#night-shift", "text": secret,
            "meta": {"audience": "internal", "folder": "internal/employees", "title": "Night shift"},
            "vector": embedding_service.embed_with_backend(secret, LOCAL_BACKEND),
        })
        data_file.write_text(json.dumps(docs), encoding="utf-8")
        cls.retriever = cls.index.retriever()

    @classmethod
    def tearDownClass(cls):
        cls.index.cleanup()

    def test_customer_and_unknown_roles_cannot_see_internal(self):
        for role in ("customer", "staff", "hacker"):
            hits = self.retriever.retrieve("Nimal Perera night shift roster", k=10, role=role, min_score=0.0)
            self.assertFalse(any(h.id.startswith("internal/") for h in hits), role)

    def test_manager_can_see_internal(self):
        hits = self.retriever.retrieve("Nimal Perera night shift roster", k=3, role="manager")
        self.assertEqual(hits[0].id, "internal/employees/staff#night-shift")


class TestManifestHotSwap(unittest.TestCase):
    def test_new_build_is_picked_up_without_restart(self):
        index = TempIndex()
        try:
            r = index.retriever()
            first = r.index_path
            self.assertIsNotNone(first)

            # Simulate a rebuild: copy the build, add a chunk, switch the manifest
            info = json.loads(index.manifest.read_text(encoding="utf-8"))
            new_name = first + "_next"
            shutil.copytree(index.dir / first, index.dir / new_name)
            data_file = index.dir / new_name / "index.json"
            docs = json.loads(data_file.read_text(encoding="utf-8"))
            text = "Document: faq - FAQ\nSection: Zebra\n\nZebracrust is our brand new striped crust."
            docs.append({"id": "faq/general-faq#zebra", "text": text,
                         "meta": {"audience": "customer", "folder": "faq", "title": "Zebra"},
                         "vector": embedding_service.embed_with_backend(text, LOCAL_BACKEND)})
            data_file.write_text(json.dumps(docs), encoding="utf-8")
            time.sleep(0.05)  # ensure a new mtime on coarse filesystems
            info["index_path"] = new_name
            index.manifest.write_text(json.dumps(info), encoding="utf-8")

            hits = r.retrieve("zebracrust striped")
            self.assertEqual(r.index_path, new_name)
            self.assertEqual(hits[0].id, "faq/general-faq#zebra")
        finally:
            index.cleanup()

    def test_broken_manifest_keeps_serving_current_build(self):
        index = TempIndex()
        try:
            r = index.retriever()
            first = r.index_path
            time.sleep(0.05)
            index.manifest.write_text(json.dumps({"index_path": "build_missing"}), encoding="utf-8")
            self.assertTrue(r.retrieve("Kandy opening hours"))
            self.assertEqual(r.index_path, first)
        finally:
            index.cleanup()


class TestBM25(unittest.TestCase):
    def test_tokenizer_drops_stopwords_and_stems(self):
        self.assertEqual(tokenize("What are the offers for STUDENT15?"), ["offer", "student15"])

    def test_rare_exact_term_wins(self):
        corpus = [tokenize(t) for t in ["pizza crust cheese", "pizza code FRIDAY10 discount", "pizza sauce"]]
        scores = BM25Okapi(corpus).get_scores(tokenize("friday10"))
        self.assertEqual(int(scores.argmax()), 1)
        self.assertEqual(float(scores[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
