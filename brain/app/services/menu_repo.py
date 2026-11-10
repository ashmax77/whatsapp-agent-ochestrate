import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from app.config import settings

log = logging.getLogger("brain.menu_repo")


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
        """Case-insensitive name or ID lookup (also strips parenthetical notes)."""
        normalized = name.strip().lower()
        stripped = re.sub(r"\s*\([^)]*\)", "", normalized).strip()
        if normalized in self._items_by_id:
            return self._items_by_id[normalized]

        # 1. Exact name match
        for item in self._items_by_id.values():
            item_lower = item.name.lower()
            item_stripped = re.sub(r"\s*\([^)]*\)", "", item_lower).strip()
            if normalized == item_lower or stripped == item_lower or stripped == item_stripped:
                return item

        # 2. Substring match
        for item in self._items_by_id.values():
            item_lower = item.name.lower()
            if normalized in item_lower or (stripped and stripped in item_lower):
                return item
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
