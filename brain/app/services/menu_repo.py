import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from app.config import settings

log = logging.getLogger("brain.menu_repo")


MENU_ALIASES: Dict[str, str] = {
    # Desserts
    "lava cake": "ds_choc_lava_cake",
    "choc lava cake": "ds_choc_lava_cake",
    "chocolate lava cake": "ds_choc_lava_cake",
    "chocolate cake": "ds_choc_lava_cake",
    "lava": "ds_choc_lava_cake",
    "cake": "ds_choc_lava_cake",
    "ice cream": "ds_ice_cream_cup",
    "ice cream cup": "ds_ice_cream_cup",
    "icecream": "ds_ice_cream_cup",
    # Sides
    "cheesy garlic bread": "sd_cheesy_garlic_bread",
    "cheese garlic bread": "sd_cheesy_garlic_bread",
    "garlic bread cheese": "sd_cheesy_garlic_bread",
    "garlic bread with cheese": "sd_cheesy_garlic_bread",
    "cheese bread": "sd_cheesy_garlic_bread",
    "garlic bread": "sd_garlic_bread",
    "plain garlic bread": "sd_garlic_bread",
    "chicken wings": "sd_chicken_wings",
    "wings": "sd_chicken_wings",
    "hot wings": "sd_chicken_wings",
    "bbq wings": "sd_chicken_wings",
    "potato wedges": "sd_potato_wedges",
    "wedges": "sd_potato_wedges",
    "chicken alfredo pasta": "sd_chicken_alfredo_pasta",
    "chicken alfredo": "sd_chicken_alfredo_pasta",
    "alfredo pasta": "sd_chicken_alfredo_pasta",
    "alfredo": "sd_chicken_alfredo_pasta",
    "pasta": "sd_chicken_alfredo_pasta",
    # Pizzas
    "margherita": "pz_margherita",
    "margarita": "pz_margherita",
    "supreme": "pz_supreme",
    "supreme pizza": "pz_supreme",
    "veggie delight": "pz_veggie",
    "veggie": "pz_veggie",
    "vegetarian": "pz_veggie",
    "veg delight": "pz_veggie",
    "chicken tikka masala": "pz_chicken_tikka",
    "chicken tikka": "pz_chicken_tikka",
    "tikka masala": "pz_chicken_tikka",
    "tikka": "pz_chicken_tikka",
    "bbq chicken": "pz_bbq_chicken",
    "bbq": "pz_bbq_chicken",
    "devilled chicken": "pz_devilled_chicken",
    "devilled": "pz_devilled_chicken",
    "cheese lover": "pz_cheese_lover",
    "cheese lovers": "pz_cheese_lover",
    "cheese pizza": "pz_cheese_lover",
    # Beverages
    "soft drink": "bv_soft_drink_500",
    "soft drink 500ml": "bv_soft_drink_500",
    "coke": "bv_soft_drink_500",
    "coca cola": "bv_soft_drink_500",
    "sprite": "bv_soft_drink_500",
    "fanta": "bv_soft_drink_500",
    "soft drink 1.5l": "bv_soft_drink_1500",
    "large soft drink": "bv_soft_drink_1500",
    "iced lime juice": "bv_iced_lime",
    "lime juice": "bv_iced_lime",
    "iced lime": "bv_iced_lime",
    "mineral water": "bv_water",
    "water": "bv_water",
    "water bottle": "bv_water",
    # Combos
    "family combo": "cb_family",
    "family meal": "cb_family",
    "family pack": "cb_family",
    "family deal": "cb_family",
}


class MenuItem(BaseModel):
    id: str
    name: str
    category: str
    description: str = ""
    sizes: Dict[str, int] = Field(default_factory=dict)  # Size -> Integer LKR price
    veg: bool = False
    allergens: List[str] = Field(default_factory=list)
    available: bool = True
    options: Dict[str, Any] = Field(default_factory=dict)
    delivery_zone_limit: Optional[str] = None


class MenuCombo(BaseModel):
    id: str
    name: str
    category: str = "combo"
    description: str = ""
    price: int  # Integer LKR
    slots: Dict[str, Any] = Field(default_factory=dict)
    available: bool = True


class MenuData(BaseModel):
    currency: str = "LKR"
    pizzas: List[MenuItem] = Field(default_factory=list)
    sides: List[MenuItem] = Field(default_factory=list)
    desserts: List[MenuItem] = Field(default_factory=list)
    beverages: List[MenuItem] = Field(default_factory=list)
    crusts: List[Dict[str, Any]] = Field(default_factory=list)
    extra_toppings: List[Dict[str, Any]] = Field(default_factory=list)
    combos: List[MenuCombo] = Field(default_factory=list)


class MenuRepo:
    def __init__(self, menu_path: Optional[Path] = None):
        self.menu_path = menu_path or settings.MENU_FILE_PATH
        self._data: Optional[MenuData] = None
        self._items_by_id: Dict[str, MenuItem] = {}
        self._combos_by_id: Dict[str, MenuCombo] = {}
        self._crusts_by_id: Dict[str, Dict[str, Any]] = {}
        self._toppings_by_id: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> MenuData:
        if not self.menu_path.exists():
            log.warning("Menu file not found at %s. Initializing empty menu.", self.menu_path)
            self._data = MenuData()
            return self._data

        try:
            with open(self.menu_path, "r", encoding="utf-8") as f:
                raw_json = json.load(f)

            self._data = MenuData(**raw_json)
            self._items_by_id.clear()
            self._combos_by_id.clear()
            self._crusts_by_id.clear()
            self._toppings_by_id.clear()

            all_items = (
                self._data.pizzas
                + self._data.sides
                + self._data.desserts
                + self._data.beverages
            )
            for item in all_items:
                self._items_by_id[item.id] = item

            for combo in self._data.combos:
                self._combos_by_id[combo.id] = combo

            for crust in self._data.crusts:
                self._crusts_by_id[crust["id"]] = crust

            for topping in self._data.extra_toppings:
                self._toppings_by_id[topping["id"]] = topping

            log.info("Loaded %d menu items and %d combos from %s", len(self._items_by_id), len(self._combos_by_id), self.menu_path)
        except Exception as e:
            log.error("Failed to load/validate menu.json: %s", e)
            self._data = MenuData()

        return self._data

    def get_item(self, item_id: str) -> Optional[MenuItem]:
        return self._items_by_id.get(item_id)

    def get_combo(self, combo_id: str) -> Optional[MenuCombo]:
        return self._combos_by_id.get(combo_id)

    def find_combo_by_name(self, name: str) -> Optional[MenuCombo]:
        raw = (name or "").strip()
        if not raw:
            return None
        if raw in self._combos_by_id:
            return self._combos_by_id[raw]
        normalized = raw.lower()
        if normalized in self._combos_by_id:
            return self._combos_by_id[normalized]
        spaced = re.sub(r"[_\-]+", " ", normalized).strip()
        if spaced in MENU_ALIASES:
            cid = MENU_ALIASES[spaced]
            if cid in self._combos_by_id:
                return self._combos_by_id[cid]
        for combo in self._combos_by_id.values():
            c_lower = combo.name.lower()
            if normalized == c_lower or spaced == c_lower or spaced in c_lower:
                return combo
        return None

    def get_crust(self, crust_id_or_name: str) -> Optional[Dict[str, Any]]:
        key = crust_id_or_name.strip().lower()
        if key in self._crusts_by_id:
            return self._crusts_by_id[key]
        for crust in self._crusts_by_id.values():
            if crust.get("name", "").lower() == key:
                return crust
        return None

    def get_topping(self, topping_id_or_name: str) -> Optional[Dict[str, Any]]:
        key = topping_id_or_name.strip().lower()
        if key in self._toppings_by_id:
            return self._toppings_by_id[key]
        for topping in self._toppings_by_id.values():
            if topping.get("name", "").lower() == key:
                return topping
        return None

    def is_available(self, item_id: str) -> bool:
        item = self.get_item(item_id)
        if item:
            return item.available
        combo = self.get_combo(item_id)
        if combo:
            return combo.available
        return False

    def find_by_name(self, name: str) -> Optional[MenuItem]:
        """Case-insensitive name or ID lookup (handles colloquial aliases, underscores, hyphens, and parentheticals)."""
        raw = name.strip()
        if not raw:
            return None

        # Direct id hit
        if raw in self._items_by_id:
            return self._items_by_id[raw]

        normalized = raw.lower()
        if normalized in self._items_by_id:
            return self._items_by_id[normalized]

        # Normalized with underscores/hyphens replaced by space
        spaced = re.sub(r"[_\-]+", " ", normalized).strip()
        stripped = re.sub(r"\s*\([^)]*\)", "", spaced).strip()

        # Check explicit aliases
        for candidate in (normalized, spaced, stripped):
            if candidate in MENU_ALIASES:
                target_id = MENU_ALIASES[candidate]
                if target_id in self._items_by_id:
                    return self._items_by_id[target_id]

        # Check category prefixes (e.g. 'pz_supreme' -> 'supreme' or vice-versa)
        for prefix in ("pz_", "sd_", "ds_", "bv_"):
            if normalized.startswith(prefix):
                without_prefix = normalized[len(prefix):].replace("_", " ")
                if without_prefix in MENU_ALIASES and MENU_ALIASES[without_prefix] in self._items_by_id:
                    return self._items_by_id[MENU_ALIASES[without_prefix]]
            else:
                with_prefix = f"{prefix}{normalized}"
                if with_prefix in self._items_by_id:
                    return self._items_by_id[with_prefix]
                with_prefix_underscored = f"{prefix}{normalized.replace(' ', '_')}"
                if with_prefix_underscored in self._items_by_id:
                    return self._items_by_id[with_prefix_underscored]

        # 1. Exact name match (checking item.name)
        for item in self._items_by_id.values():
            item_lower = item.name.lower()
            item_stripped = re.sub(r"\s*\([^)]*\)", "", item_lower).strip()
            if normalized == item_lower or spaced == item_lower or stripped == item_lower or stripped == item_stripped:
                return item

        # 2. Substring match (prioritize the longest, most specific matching item name)
        matches: List[Tuple[int, MenuItem]] = []
        for item in self._items_by_id.values():
            item_lower = item.name.lower()
            item_stripped = re.sub(r"\s*\([^)]*\)", "", item_lower).strip()
            for cand in (spaced, stripped, normalized):
                if cand and (cand in item_lower or item_lower in cand or cand in item_stripped):
                    matches.append((len(item_lower), item))
                    break

        if matches:
            matches.sort(key=lambda x: x[0], reverse=True)
            return matches[0][1]

        return None

    def list_items(
        self,
        category: Optional[str] = None,
        veg_only: Optional[bool] = None
    ) -> List[MenuItem]:
        results = list(self._items_by_id.values())
        if category:
            results = [i for i in results if i.category.lower() == category.lower()]
        if veg_only is not None:
            results = [i for i in results if i.veg == veg_only]
        return results

    def get_all_items(self) -> List[MenuItem]:
        return list(self._items_by_id.values())

    def get_all_combos(self) -> List[MenuCombo]:
        return list(self._combos_by_id.values())

    def validate_item_options(
        self,
        item: MenuItem,
        size: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validates options (crust, extra_toppings, sauce, flavour) for an item.
        Returns (ok, error_message, normalized_options).
        """
        if not options:
            return True, None, {}

        normalized: Dict[str, Any] = {}
        allowed_keys = set(item.options.keys())
        if item.category == "pizza":
            allowed_keys.update({"crust", "extra_toppings"})

        for key, val in options.items():
            if key not in allowed_keys:
                return False, f"Option '{key}' is not supported for '{item.name}'.", {}

            if key == "crust":
                crust = self.get_crust(str(val))
                if not crust:
                    valid_crusts = ", ".join(self._crusts_by_id.keys())
                    return False, f"Invalid crust '{val}'. Valid crusts: {valid_crusts}.", {}
                normalized["crust"] = crust["id"]

            elif key == "extra_toppings":
                if not isinstance(val, list):
                    return False, "Option 'extra_toppings' must be a list of topping ids.", {}
                norm_toppings: List[str] = []
                for t in val:
                    top = self.get_topping(str(t))
                    if not top:
                        valid_tops = ", ".join(self._toppings_by_id.keys())
                        return False, f"Invalid topping '{t}'. Valid toppings: {valid_tops}.", {}
                    norm_toppings.append(top["id"])
                normalized["extra_toppings"] = sorted(norm_toppings)

            else:
                choices = item.options.get(key, [])
                matched = next((c for c in choices if str(c).lower() == str(val).strip().lower()), None)
                if matched is None:
                    return False, f"Invalid {key} '{val}' for '{item.name}'. Allowed: {', '.join(choices)}.", {}
                normalized[key] = matched

        return True, None, normalized

    def validate_combo_choices(
        self,
        combo: MenuCombo,
        choices: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], Dict[str, str]]:
        """
        Validates each slot in a combo against the customer's choices.
        Fixed-item slots default automatically and forbid substitutions.
        Category/size slots must reference an available item of that category and size.
        """
        choices = choices or {}
        unknown_slots = [k for k in choices.keys() if k not in combo.slots]
        if unknown_slots:
            return False, f"Unknown combo slot(s): {', '.join(unknown_slots)}.", {}

        resolved: Dict[str, str] = {}
        for slot_name, spec in combo.slots.items():
            fixed_id = spec.get("item_id")
            given = choices.get(slot_name)

            if fixed_id:
                if given is not None:
                    item = self.get_item(given) or self.find_by_name(given)
                    chosen_id = item.id if item else given
                    if chosen_id != fixed_id:
                        return False, f"Substitutions are not allowed for slot '{slot_name}' (fixed to '{fixed_id}').", {}
                if not self.is_available(fixed_id):
                    return False, f"Combo item '{fixed_id}' is currently unavailable.", {}
                resolved[slot_name] = fixed_id
                continue

            if not given:
                return False, f"Missing required choice for combo slot '{slot_name}'.", {}

            item = self.get_item(given) or self.find_by_name(given)
            if not item:
                return False, f"Invalid item '{given}' for combo slot '{slot_name}'.", {}
            if not item.available:
                return False, f"Item '{item.name}' is currently out of stock.", {}

            req_cat = spec.get("category")
            if req_cat and item.category.lower() != req_cat.lower():
                return False, f"Slot '{slot_name}' requires a '{req_cat}' item, got '{item.name}'.", {}

            req_size = spec.get("size")
            if req_size and req_size.lower() not in item.sizes:
                return False, f"Item '{item.name}' is not available in size '{req_size}'.", {}

            resolved[slot_name] = item.id

        return True, None, resolved


menu_repo = MenuRepo()
