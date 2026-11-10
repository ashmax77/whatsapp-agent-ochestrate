import unittest
from app.services.menu_repo import menu_repo


class TestMenuRepo(unittest.TestCase):
    def test_get_pizza_item(self):
        item = menu_repo.get_item("pz_margherita")
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Margherita")
        self.assertTrue(item.veg)
        self.assertEqual(item.sizes.get("medium"), 2490)
        self.assertIsInstance(item.sizes.get("medium"), int)

    def test_find_by_name(self):
        item = menu_repo.find_by_name("Supreme")
        self.assertIsNotNone(item)
        self.assertEqual(item.id, "pz_supreme")

        # Case-insensitive partial
        item2 = menu_repo.find_by_name("garlic bread")
        self.assertIsNotNone(item2)
        self.assertEqual(item2.id, "sd_garlic_bread")

    def test_veg_filter(self):
        veg_items = menu_repo.list_items(category="pizza", veg_only=True)
        self.assertGreater(len(veg_items), 0)
        for p in veg_items:
            self.assertTrue(p.veg)


if __name__ == "__main__":
    unittest.main()

