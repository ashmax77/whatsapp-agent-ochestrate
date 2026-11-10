import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
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

            log.info("Loaded %d menu items and %d combos from %s", len(self._items_by_id), len(self._combos_by_id), self.menu_path)
        except Exception as e:
            log.error("Failed to load/validate menu.json: %s", e)
            self._data = MenuData()

        return self._data

    def get_item(self, item_id: str) -> Optional[MenuItem]:
        return self._items_by_id.get(item_id)

    def get_combo(self, combo_id: str) -> Optional[MenuCombo]:
        return self._combos_by_id.get(combo_id)

    def is_available(self, item_id: str) -> bool:
        item = self.get_item(item_id)
        if item:
            return item.available
        combo = self.get_combo(item_id)
        if combo:
            return combo.available
        return False

    def find_by_name(self, name: str) -> Optional[MenuItem]:
        """Case-insensitive name or ID lookup."""
        normalized = name.strip().lower()
        # Exact ID match
        if normalized in self._items_by_id:
            return self._items_by_id[normalized]

        # Exact or substring name match
        for item in self._items_by_id.values():
            if normalized == item.name.lower() or normalized in item.name.lower():
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


menu_repo = MenuRepo()

