import json
import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from app.rag.ingest import ingest_kb, prune_builds
from app.rag.kb_loader import KBLoader

FRONT = "---\naudience: customer\nlast_updated: 2026-11-09\n---\n"


class TestBlueGreenIngest(unittest.TestCase):
    def setUp(self):
        self.chroma = Path(tempfile.mkdtemp(prefix="chroma_test_"))
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        shutil.rmtree(self.chroma, ignore_errors=True)

    def _build(self, **kwargs):
        return ingest_kb(chroma_path=self.chroma, prefer_local=True, **kwargs)

    def test_build_writes_manifest_and_verified_index(self):
        self.assertEqual(self._build(), 0)
        info = json.loads((self.chroma / "index_info.json").read_text(encoding="utf-8"))
        build = self.chroma / info["index_path"]
        self.assertTrue(info["index_path"].startswith("build_"))
        self.assertTrue((build / "index.json").exists())
        self.assertTrue((build / "menu_summary.csv").exists())
        docs = json.loads((build / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(info["chunk_count"], len(docs))
        self.assertEqual(info["embedding_dim"], len(docs[0]["vector"]))
        self.assertFalse(any(d["meta"]["audience"] != "customer" for d in docs))
        self.assertFalse((self.chroma / "index_info.tmp").exists())

    def test_old_builds_are_pruned_keeping_two(self):
        for _ in range(3):
            self.assertEqual(self._build(), 0)
        builds = sorted(p.name for p in self.chroma.glob("build_*"))
        self.assertEqual(len(builds), 2)
        live = json.loads((self.chroma / "index_info.json").read_text(encoding="utf-8"))["index_path"]
        self.assertIn(live, builds)

    def test_prune_never_removes_live_build(self):
        for name in ("build_1", "build_2", "build_3"):
            (self.chroma / name).mkdir()
        removed = prune_builds(self.chroma, keep=1, live_build="build_1")
        self.assertEqual(removed, ["build_2"])
        self.assertTrue((self.chroma / "build_1").exists())

    def test_failed_preflight_keeps_previous_build_live(self):
        self.assertEqual(self._build(), 0)
        before = (self.chroma / "index_info.json").read_text(encoding="utf-8")

        empty_kb = Path(tempfile.mkdtemp(prefix="empty_kb_"))
        try:
            loader = KBLoader(kb_path=empty_kb, branches_path=empty_kb / "none.json")
            loader.menu_summary_rows = lambda: []  # no summaries either -> zero chunks
            loader.build_summary_chunks = lambda: []
            self.assertEqual(self._build(loader=loader), 1)
        finally:
            shutil.rmtree(empty_kb, ignore_errors=True)

        self.assertEqual((self.chroma / "index_info.json").read_text(encoding="utf-8"), before)
        self.assertEqual(len(list(self.chroma.glob("build_*"))), 1)

    def test_embedding_failure_midway_keeps_previous_build_live(self):
        self.assertEqual(self._build(), 0)
        before = (self.chroma / "index_info.json").read_text(encoding="utf-8")
        calls = {"n": 0}

        def flaky(text, backend):
            calls["n"] += 1
            if calls["n"] > 5:
                raise RuntimeError("network dropped")
            return [0.1] * 384

        with mock.patch("app.rag.ingest.embedding_service.embed_with_backend", side_effect=flaky):
            self.assertEqual(self._build(), 1)

        self.assertEqual((self.chroma / "index_info.json").read_text(encoding="utf-8"), before)
        self.assertEqual(len(list(self.chroma.glob("build_*"))), 1)


if __name__ == "__main__":
    unittest.main()

