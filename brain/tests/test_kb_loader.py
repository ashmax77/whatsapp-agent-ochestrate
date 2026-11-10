import shutil
import tempfile
import unittest
from pathlib import Path
from app.config import settings
from app.rag.kb_loader import (
    kb_loader, KBLoader, generate_slug, parse_front_matter, clean_text, split_by_size, INTRO_SLUG,
)
from app.rag.validate_kb import preflight_check

FRONT = "---\naudience: customer\nlast_updated: 2026-11-09\n---\n"


class TestKBLoader(unittest.TestCase):
    def test_slug_generation(self):
        # Slug rule: lowercase, drop non-alphanumeric/spaces/hyphens, spaces to hyphens
        self.assertEqual(
            generate_slug("Student Tuesday (code STUDENT15)"),
            "student-tuesday-code-student15"
        )
        self.assertEqual(
            generate_slug("Colombo 07 - Opening Hours"),
            "colombo-07---opening-hours"
        )
        self.assertEqual(
            generate_slug("Devilled Chicken (Sri Lankan special)"),
            "devilled-chicken-sri-lankan-special"
        )

    def test_parse_front_matter(self):
        doc = (
            "---\n"
            "audience: customer\n"
            "last_updated: 2026-11-09\n"
            "---\n"
            "# Title\n\n"
            "## Section 1\nContent 1"
        )
        meta, body = parse_front_matter(doc)
        self.assertEqual(meta.get("audience"), "customer")
        self.assertEqual(str(meta.get("last_updated")), "2026-11-09")
        self.assertTrue(body.startswith("# Title"))

    def test_customer_chunks_exclude_internal(self):
        chunks = kb_loader.load_chunks(include_internal=False)
        self.assertGreater(len(chunks), 0)

        for chunk in chunks:
            self.assertEqual(chunk.meta.get("audience"), "customer")
            self.assertNotIn("internal", chunk.meta.get("folder", ""))
            self.assertFalse(chunk.id.startswith("internal/"))

    def test_real_kb_passes_preflight(self):
        self.assertEqual(preflight_check(kb_loader.load_chunks(include_internal=False)), [])


class TestTextCleaning(unittest.TestCase):
    def test_removes_signature_lines_dividers_and_blank_runs(self):
        raw = "Signed by\n_______________\n**Manager**\n\n\n\n---\nNext part"
        cleaned = clean_text(raw)
        self.assertNotIn("_____", cleaned)
        self.assertNotIn("\n\n\n", cleaned)
        self.assertNotRegex(cleaned, r"(?m)^---\s*$")
        # Names and titles are kept
        self.assertIn("**Manager**", cleaned)
        self.assertIn("Next part", cleaned)

    def test_size_splitter_respects_limit_and_overlaps(self):
        text = " ".join(f"sentence number {i} about pizza." for i in range(200))
        parts = split_by_size(text, 300, 50)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 300 for p in parts))
        # Overlap: the start of part 2 repeats words from the end of part 1
        self.assertIn(parts[1].split()[0], parts[0])


class TestSafeLoadingAndChunking(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kb_loader_"))
        (self.root / "menu").mkdir()
        (self.root / "internal").mkdir()
        (self.root / "menu" / "good.md").write_text(
            FRONT + "# Pizzas\nOur pizzas are hand stretched every morning in each outlet.\n\n"
            "## Margherita\nClassic tomato sauce with mozzarella and fresh basil leaves.\n\n"
            "## Tiny\nx\n\n"
            "## Specials\nSeasonal specials change every month.\n\n"
            "### Black Pepper Chicken\nA peppery chicken pizza available in all outlets.\n",
            encoding="utf-8",
        )
        (self.root / "menu" / "bad.md").write_bytes("Café policy".encode("cp1252"))  # not UTF-8
        (self.root / "notes.txt").write_text("A loose file")
        (self.root / "internal" / "secret.md").write_text(
            "---\naudience: internal\nlast_updated: 2026-11-09\n---\n# Staff\n## Shifts\nNimal works nights every week.",
            encoding="utf-8",
        )
        self.loader = KBLoader(kb_path=self.root, branches_path=self.root / "none.json")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_bad_and_loose_files_do_not_crash(self):
        chunks = self.loader.load_chunks(include_summaries=False)
        self.assertEqual(self.loader.skipped_files, ["menu/bad.md"])
        self.assertTrue(all(c.meta["file"] == "good" for c in chunks))

    def test_internal_never_loaded(self):
        chunks = self.loader.load_chunks(include_summaries=False)
        self.assertFalse(any("Nimal" in c.text for c in chunks))

    def test_context_header_intro_h3_and_tiny_sections(self):
        chunks = {c.id: c for c in self.loader.load_chunks(include_summaries=False)}
        self.assertIn(f"menu/good#{INTRO_SLUG}", chunks)
        self.assertIn("menu/good#margherita", chunks)
        self.assertIn("menu/good#specials/black-pepper-chicken", chunks)
        self.assertNotIn("menu/good#tiny", chunks)  # title-only section skipped

        marg = chunks["menu/good#margherita"]
        self.assertTrue(marg.text.startswith("Document: menu - Pizzas\nSection: Margherita\n\n"))
        self.assertEqual(marg.meta["doc_title"], "Pizzas")

    def test_long_sections_are_split_with_unique_ids(self):
        long_body = " ".join(f"Line {i} describes the dough." for i in range(150))
        (self.root / "menu" / "long.md").write_text(FRONT + "# Long\n## Dough\n" + long_body, encoding="utf-8")
        chunks = [c for c in self.loader.load_chunks(include_summaries=False) if c.meta["file"] == "long"]
        self.assertGreater(len(chunks), 1)
        self.assertEqual(len({c.id for c in chunks}), len(chunks))
        self.assertTrue(all(c.id.startswith("menu/long#dough-part") for c in chunks))
        self.assertEqual(preflight_check(chunks), [])

    def test_preflight_rejects_empty_oversized_and_leaky_chunks(self):
        good = self.loader.load_chunks(include_summaries=False)[0]
        empty = good.model_copy(update={"id": "e", "text": "  "})
        huge = good.model_copy(update={"id": "h", "text": "x" * (settings.MAX_CHUNK_CHARS + 1)})
        leak = good.model_copy(update={"id": "l", "meta": {**good.meta, "audience": "internal"}})
        errors = preflight_check([empty, huge, leak])
        self.assertEqual(len(errors), 3)
        self.assertEqual(preflight_check([]), ["No chunks were created. Check KB_PATH and the markdown headings."])


class TestSummaryChunks(unittest.TestCase):
    def test_summaries_present_and_price_free(self):
        summaries = {c.id: c for c in kb_loader.build_summary_chunks()}
        self.assertIn("menu/_summary#all-items", summaries)
        self.assertIn("branches/_summary#all-outlets", summaries)
        self.assertIn("offers/_summary#current-offers", summaries)

        menu = summaries["menu/_summary#all-items"].text
        self.assertIn("Margherita", menu)
        self.assertNotRegex(menu, r"\b\d{3,},?\d*\b.*LKR|LKR\s*\d")  # D3: no prices in KB text
        self.assertIn("STUDENT15", summaries["offers/_summary#current-offers"].text)
        self.assertNotIn("Upcoming", summaries["offers/_summary#current-offers"].text)


if __name__ == "__main__":
    unittest.main()
