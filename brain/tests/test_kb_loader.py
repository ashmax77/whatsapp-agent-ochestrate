import unittest
from app.rag.kb_loader import kb_loader, generate_slug, parse_front_matter


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


if __name__ == "__main__":
    unittest.main()

