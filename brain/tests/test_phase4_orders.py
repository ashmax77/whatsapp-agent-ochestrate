import shutil
import tempfile
import unittest
from pathlib import Path
from app.state.session import CartLine, Session
from app.services import clock, pricing
from app.services.menu_repo import menu_repo
from app.services.branch_repo import branch_repo
from app.services.promo_repo import promo_repo
from app.db.order_repo import OrderRepo
from app.tools.registry import registry
from app.agents.order_agent import order_agent
from app.agents.delivery_agent import delivery_agent
from app.agents.promo_agent import promo_agent


class TestPricingEngine(unittest.TestCase):
    def test_unit_price_and_surcharges(self):
        # Supreme Large = 3990
        line_plain = CartLine(item_id="pz_supreme", size="large", qty=1)
        self.assertEqual(pricing.unit_price(line_plain), 3990)

        # Cheese-stuffed large (+700) + mushrooms (+250) + extra_cheese (+350) = 3990 + 1300 = 5290
        line_loaded = CartLine(
            item_id="pz_supreme",
            size="large",
            qty=2,
            options={"crust": "cheese_stuffed", "extra_toppings": ["mushrooms", "extra_cheese"]},
        )
        self.assertEqual(pricing.unit_price(line_loaded), 5290)
        self.assertEqual(pricing.line_total(line_loaded), 10580)

    def test_discount_rounding_and_excludes_delivery_fee(self):
        # Plan receipt fixture: 1 Large Supreme (3990) + 2 Garlic Bread (2 * 690 = 1380) = 5370
        cart = [
            CartLine(item_id="pz_supreme", size="large", qty=1),
            CartLine(item_id="sd_garlic_bread", size="regular", qty=2),
        ]
        sub = pricing.subtotal(cart)
        self.assertEqual(sub, 5370)

        friday = promo_repo.get_promo("FRIDAY10")
        disc = pricing.discount(friday, sub, cart)
        self.assertEqual(disc, 537)

        nugegoda = branch_repo.get_branch("nugegoda")
        fee_z2 = pricing.delivery_fee(nugegoda, "z2", sub, "delivery")
        self.assertEqual(fee_z2, 250)

        # Discount applies ONLY to food subtotal (5370 - 537 = 4833), then + 250 delivery = 5083
        self.assertEqual(pricing.total(sub, fee_z2, disc), 5083)

        # Half-up rounding check: 15% of 1490 = 223.5 -> 224
        student = promo_repo.get_promo("STUDENT15")
        self.assertEqual(pricing.discount(student, 1490), 224)


class TestBranchResolutionAndHours(unittest.TestCase):
    def tearDown(self):
        clock.reset_clock()

    def test_pin_resolution_zones_and_radius_limits(self):
        # Near Colombo 07 (~0.5 km) -> colombo07, z1 (free)
        b, z, dist, err = branch_repo.resolve_by_pin(6.9080, 79.8650)
        self.assertIsNone(err)
        self.assertEqual(b.id, "colombo07")
        self.assertEqual(z.id, "z1")
        self.assertEqual(z.fee, 0)

        # ~4.5 km from Nugegoda -> z2 (fee 250)
        b2, z2, _, err2 = branch_repo.resolve_by_pin(6.8450, 79.9280)
        self.assertIsNone(err2)
        self.assertEqual(b2.id, "nugegoda")
        self.assertEqual(z2.id, "z2")
        self.assertEqual(z2.fee, 250)

        # Kandy has a strict 6 km limit: ~7 km from Kandy (7.3536, 80.6337 is ~7.0 km north) -> OUT_OF_AREA
        b3, z3, dist3, err3 = branch_repo.resolve_by_pin(7.3536, 80.6337)
        self.assertEqual(err3, "OUT_OF_AREA")
        self.assertIsNone(b3)
        self.assertGreater(dist3, 6.0)

    def test_address_alias_and_fuzzy_matching(self):
        # Exact alias in Kandy Zone 2
        b, z, err = branch_repo.resolve_by_address("Peradeniya Road, Peradeniya")
        self.assertIsNone(err)
        self.assertEqual(b.id, "kandy")
        self.assertEqual(z.id, "z2")

        # Minor typo in Maharagama ("Maharagam") -> fuzzy >= 85 -> nugegoda
        b2, z2, err2 = branch_repo.resolve_by_address("15 High Level Rd, Maharagam")
        self.assertIsNone(err2)
        self.assertEqual(b2.id, "nugegoda")

        # Ambiguous address mentioning two branches -> NEEDS_CLARIFICATION
        _, _, err_ambig = branch_repo.resolve_by_address("Between Colombo 07 and Nugegoda")
        self.assertEqual(err_ambig, "NEEDS_CLARIFICATION")

        # Vague street with no area -> NEEDS_CLARIFICATION
        _, _, err_vague = branch_repo.resolve_by_address("No 42, Temple Lane")
        self.assertEqual(err_vague, "NEEDS_CLARIFICATION")

        # Known out-of-coverage town (Colombo 10 / Galle) -> OUT_OF_AREA
        _, _, err_col10 = branch_repo.resolve_by_address("Maradana, Colombo 10")
        self.assertEqual(err_col10, "OUT_OF_AREA")
        _, _, err_galle = branch_repo.resolve_by_address("Galle Fort, Galle")
        self.assertEqual(err_galle, "OUT_OF_AREA")

    def test_opening_hours_boundaries(self):
        # Colombo 07 delivery cut-off is 22:30
        clock.set_clock("2026-11-10T22:29:00+05:30")
        self.assertTrue(branch_repo.is_open("colombo07", mode="delivery"))
        clock.set_clock("2026-11-10T22:31:00+05:30")
        self.assertFalse(branch_repo.is_open("colombo07", mode="delivery"))

        # Colombo 07 pickup (last_dine_in_order) cut-off is 22:15
        clock.set_clock("2026-11-10T22:15:00+05:30")
        self.assertTrue(branch_repo.is_open("colombo07", mode="pickup"))
        clock.set_clock("2026-11-10T22:16:00+05:30")
        self.assertFalse(branch_repo.is_open("colombo07", mode="pickup"))

        # Kandy delivery cut-off is 22:00, opens at 11:00
        clock.set_clock("2026-11-10T10:59:00+05:30")
        self.assertFalse(branch_repo.is_open("kandy", mode="delivery"))
        clock.set_clock("2026-11-10T21:59:00+05:30")
        self.assertTrue(branch_repo.is_open("kandy", mode="delivery"))
        clock.set_clock("2026-11-10T22:01:00+05:30")
        self.assertFalse(branch_repo.is_open("kandy", mode="delivery"))


class TestPromoRules(unittest.TestCase):
    def tearDown(self):
        clock.reset_clock()

    def test_student15_branch_day_date_and_subtotal_rules(self):
        # Tuesday 10 Nov 2026 at Nugegoda with subtotal 2500 -> VALID
        clock.set_clock("2026-11-10T18:00:00+05:30")
        promo, err, msg = promo_repo.validate("STUDENT15", subtotal_lkr=2500, branch_id="nugegoda")
        self.assertIsNone(err)
        self.assertIsNotNone(promo)
        self.assertIn("student ID", msg)

        # Rejected at Colombo 07
        promo_c, err_c, _ = promo_repo.validate("STUDENT15", subtotal_lkr=2500, branch_id="colombo07")
        self.assertIsNone(promo_c)
        self.assertEqual(err_c, "PROMO_INVALID")

        # Rejected on Wednesday (11 Nov 2026)
        clock.set_clock("2026-11-11T18:00:00+05:30")
        promo_w, err_w, _ = promo_repo.validate("STUDENT15", subtotal_lkr=2500, branch_id="nugegoda")
        self.assertIsNone(promo_w)
        self.assertEqual(err_w, "PROMO_INVALID")

        # Rejected after 31 Dec 2026 (Tuesday 5 Jan 2027) with "expired"
        clock.set_clock("2027-01-05T18:00:00+05:30")
        promo_exp, err_exp, msg_exp = promo_repo.validate("STUDENT15", subtotal_lkr=2500, branch_id="nugegoda")
        self.assertIsNone(promo_exp)
        self.assertEqual(err_exp, "PROMO_INVALID")
        self.assertIn("expired", msg_exp.lower())

        # Ended Monsoon Special -> rejected with "expired"
        clock.set_clock("2026-11-10T18:00:00+05:30")
        _, err_mon, msg_mon = promo_repo.validate("MONSOON", subtotal_lkr=3000, branch_id="nugegoda")
        self.assertEqual(err_mon, "PROMO_INVALID")
        self.assertIn("expired", msg_mon.lower())


class TestOrderFlowAndNegativeGuards(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="orders_db_"))
        self.orders = OrderRepo(db_path=self.tmp_dir / "test_orders.db")
        # Tuesday 18:00 (open at all branches; STUDENT15 active)
        clock.set_clock("2026-11-10T18:00:00+05:30")

    def tearDown(self):
        clock.reset_clock()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_scripted_order_flow_all_three_branches(self):
        # 1. Colombo 07 delivery (Friday with FRIDAY10)
        clock.set_clock("2026-11-13T18:30:00+05:30")
        s1 = Session(user_id="u_colombo", message_count=1)
        self.assertTrue(order_agent.execute_tool("cart.add_item", s1, {"item_id": "pz_supreme", "size": "large", "qty": 1})["ok"])
        self.assertTrue(order_agent.execute_tool("cart.add_item", s1, {"item_id": "sd_garlic_bread", "size": "regular", "qty": 2})["ok"])
        self.assertTrue(delivery_agent.execute_tool("delivery.set_address", s1, {"address_text": "Fort, Colombo 01"})["ok"])
        self.assertEqual(s1.branch_id, "colombo07")
        self.assertEqual(s1.delivery_zone, "z2")
        self.assertTrue(promo_agent.execute_tool("promo.apply", s1, {"code": "FRIDAY10"})["ok"])

        sum1 = order_agent.execute_tool("order.show_summary", s1)
        self.assertTrue(sum1["ok"])
        self.assertEqual(sum1["data"]["subtotal"], 5370)
        self.assertEqual(sum1["data"]["discount"], 537)
        self.assertEqual(sum1["data"]["delivery_fee"], 250)
        self.assertEqual(sum1["data"]["total"], 5083)

        s1.message_count += 1
        placed1 = order_agent.execute_tool("order.place_order", s1, {"cart_hash": s1.summary_hash}, orders=self.orders)
        self.assertTrue(placed1["ok"])
        self.assertEqual(s1.stage, "placed")
        db_order1 = self.orders.get_order_by_no(placed1["data"]["order_no"])
        self.assertIsNotNone(db_order1)
        self.assertEqual(db_order1.total, 5083)
        self.assertEqual(db_order1.branch_id, "colombo07")

        # 2. Nugegoda Tuesday delivery with STUDENT15 (Zone 1 Delkanda -> free delivery)
        clock.set_clock("2026-11-10T19:00:00+05:30")
        s2 = Session(user_id="u_nugegoda", message_count=1)
        self.assertTrue(registry.call("cart.add_item", s2, {"item_id": "pz_veggie", "size": "medium", "qty": 1})["ok"])
        self.assertTrue(registry.call("cart.add_item", s2, {"item_id": "sd_garlic_bread", "size": "regular", "qty": 1})["ok"])
        self.assertTrue(registry.call("delivery.set_address", s2, {"address_text": "Delkanda, Nugegoda"})["ok"])
        self.assertTrue(registry.call("promo.apply", s2, {"code": "STUDENT15"})["ok"])
        sum2 = registry.call("order.show_summary", s2)
        self.assertTrue(sum2["ok"])
        # 2590 + 690 = 3280; 15% = 492; Zone 1 delivery = 0 -> total = 2788
        self.assertEqual(sum2["data"]["subtotal"], 3280)
        self.assertEqual(sum2["data"]["discount"], 492)
        self.assertEqual(sum2["data"]["delivery_fee"], 0)
        self.assertEqual(sum2["data"]["total"], 2788)
        self.assertIn("student ID", sum2["data"]["receipt_text"])
        s2.message_count += 1
        placed2 = registry.call("order.place_order", s2, {"cart_hash": s2.summary_hash}, orders=self.orders)
        self.assertTrue(placed2["ok"])
        self.assertEqual(self.orders.get_order_by_no(placed2["data"]["order_no"]).total, 2788)

        # 3. Kandy pickup with Family Combo (no minimum order check required for pickup)
        s3 = Session(user_id="u_kandy", message_count=1)
        combo_res = registry.call(
            "cart.add_combo",
            s3,
            {"combo_id": "cb_family", "choices": {"large_pizza": "pz_devilled_chicken", "medium_pizza": "pz_margherita"}},
        )
        self.assertTrue(combo_res["ok"])
        self.assertTrue(registry.call("order.set_pickup", s3, {"branch_id": "kandy"})["ok"])
        sum3 = registry.call("order.show_summary", s3)
        self.assertTrue(sum3["ok"])
        self.assertEqual(sum3["data"]["total"], 6490)
        s3.message_count += 1
        placed3 = registry.call("order.place_order", s3, {"cart_hash": s3.summary_hash}, orders=self.orders)
        self.assertTrue(placed3["ok"])
        self.assertEqual(self.orders.get_order_by_no(placed3["data"]["order_no"]).branch_id, "kandy")

    def test_negative_guards_and_hash_invalidation(self):
        s = Session(user_id="u_neg", message_count=1)

        # 1. Invalid quantities (0 and 21)
        self.assertEqual(
            registry.call("cart.add_item", s, {"item_id": "pz_margherita", "size": "personal", "qty": 0})["error"],
            "INVALID_QTY",
        )
        self.assertEqual(
            registry.call("cart.add_item", s, {"item_id": "pz_margherita", "size": "personal", "qty": 21})["error"],
            "INVALID_QTY",
        )

        # 2. Combo with invalid substitution on fixed slot
        bad_combo = registry.call(
            "cart.add_combo",
            s,
            {
                "combo_id": "cb_family",
                "choices": {
                    "large_pizza": "pz_supreme",
                    "medium_pizza": "pz_veggie",
                    "side": "sd_chicken_wings",
                },
            },
        )
        self.assertFalse(bad_combo["ok"])
        self.assertEqual(bad_combo["error"], "INVALID_COMBO_CHOICES")

        # 3. Below minimum delivery order (Margherita personal is 1490 < 1500)
        self.assertTrue(registry.call("cart.add_item", s, {"item_id": "pz_margherita", "size": "personal", "qty": 1})["ok"])
        self.assertTrue(registry.call("delivery.set_address", s, {"address_text": "Nugegoda"})["ok"])
        below_min = registry.call("order.show_summary", s)
        self.assertFalse(below_min["ok"])
        self.assertEqual(below_min["error"], "BELOW_MIN_ORDER")

        # 4. Ice cream to Zone 2 rejected at summary time
        self.assertTrue(registry.call("cart.add_item", s, {"item_id": "ds_ice_cream_cup", "size": "regular", "qty": 1})["ok"])
        self.assertTrue(registry.call("delivery.set_address", s, {"address_text": "Maharagama"})["ok"])  # z2
        zone_err = registry.call("order.show_summary", s)
        self.assertFalse(zone_err["ok"])
        self.assertEqual(zone_err["error"], "ZONE_RESTRICTED_ITEM")

        # Switch to Zone 1 (Nugegoda) -> summary succeeds
        self.assertTrue(registry.call("delivery.set_address", s, {"address_text": "Nugegoda"})["ok"])
        sum_ok = registry.call("order.show_summary", s)
        self.assertTrue(sum_ok["ok"])
        valid_hash = s.summary_hash

        # 5. Same-turn confirm rejected (message_count == summary_msg_no)
        same_turn = registry.call("order.place_order", s, {"cart_hash": valid_hash}, orders=self.orders)
        self.assertFalse(same_turn["ok"])
        self.assertEqual(same_turn["error"], "SAME_TURN_CONFIRM")

        # 6. Wrong hash rejected
        s.message_count += 1
        wrong_hash = registry.call("order.place_order", s, {"cart_hash": "0000deadbeef0000"}, orders=self.orders)
        self.assertFalse(wrong_hash["ok"])
        self.assertEqual(wrong_hash["error"], "HASH_MISMATCH")

        # 7. Any change (including switching branch) invalidates summary_hash and leaves 'confirming'
        self.assertTrue(registry.call("order.set_pickup", s, {"branch_id": "colombo07"})["ok"])
        self.assertIsNone(s.summary_hash)
        self.assertNotEqual(s.stage, "confirming")
        no_sum = registry.call("order.place_order", s, {"cart_hash": valid_hash}, orders=self.orders)
        self.assertFalse(no_sum["ok"])
        self.assertEqual(no_sum["error"], "SUMMARY_REQUIRED")

        # 8. Closed branch rejected at place_order time even after a valid summary
        sum2 = registry.call("order.show_summary", s)
        self.assertTrue(sum2["ok"])
        s.message_count += 1
        clock.set_clock("2026-11-10T23:15:00+05:30")  # after closing
        closed_place = registry.call("order.place_order", s, {"cart_hash": s.summary_hash}, orders=self.orders)
        self.assertFalse(closed_place["ok"])
        self.assertEqual(closed_place["error"], "BRANCH_CLOSED")
        self.assertNotEqual(s.stage, "placed")


if __name__ == "__main__":
    unittest.main()

