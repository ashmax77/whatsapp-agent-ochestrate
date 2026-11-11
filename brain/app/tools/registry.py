"""
Central tool registry with Pydantic input validation, state-machine guards,
and OpenAI/Anthropic-compatible JSON schema export.
"""
from typing import Any, Callable, Dict, List, Literal, Optional, Type
from pydantic import BaseModel, Field, ValidationError
from app.state.session import Session
from app.tools.kb_tools import kb_ask, kb_search, menu_get_item, menu_list_items
from app.tools.branch_tools import branch_list
from app.tools.cart_tools import (
    cart_add_combo,
    cart_add_item,
    cart_clear,
    cart_remove_item,
    cart_update_item,
    cart_view,
)
from app.tools.delivery_tools import delivery_quote, delivery_set_address
from app.tools.promo_tools import promo_apply, promo_remove
from app.tools.order_tools import (
    order_cancel_draft,
    order_place_order,
    order_set_fulfilment,
    order_set_pickup,
    order_show_summary,
)


# ------------------------------------------------------------------
# Pydantic input schemas for every tool
# ------------------------------------------------------------------
class EmptyInput(BaseModel):
    pass


class KBAskInput(BaseModel):
    question: str = Field(description="Customer question about menu, hours, branches, offers or policies")


class KBSearchInput(BaseModel):
    query: str = Field(description="Search query for knowledge chunks")
    k: int = Field(default=4, ge=1, le=10)


class MenuGetItemInput(BaseModel):
    item_id: str = Field(description="Menu item or combo id, e.g. pz_supreme, sd_garlic_bread, cb_family")


class MenuListItemsInput(BaseModel):
    category: Optional[str] = Field(default=None, description="Optional category: pizza, side, dessert, beverage")
    veg: Optional[bool] = Field(default=None, description="Optional vegetarian filter")


class CartAddItemInput(BaseModel):
    item_id: str = Field(description="Menu item id or name, e.g. pz_supreme")
    size: str = Field(default="regular", description="Size: personal, medium, large, or regular")
    qty: int = Field(default=1, description="Quantity between 1 and 20")
    notes: Optional[str] = Field(default=None, description="Special preparation notes")
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional crust, extra_toppings, sauce, or flavour options",
    )


class CartAddComboInput(BaseModel):
    combo_id: str = Field(description="Combo id, e.g. cb_family")
    choices: Dict[str, str] = Field(
        description="Slot choices, e.g. {'large_pizza': 'pz_supreme', 'medium_pizza': 'pz_veggie'}"
    )
    qty: int = Field(default=1, description="Quantity between 1 and 20")
    notes: Optional[str] = Field(default=None, description="Optional notes")


class CartUpdateItemInput(BaseModel):
    line_index: int = Field(description="0-based index of the cart line to update")
    qty: Optional[int] = Field(default=None, description="New quantity (0 removes the line)")
    size: Optional[str] = Field(default=None, description="New size")
    notes: Optional[str] = Field(default=None, description="New notes")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Updated options")


class CartRemoveItemInput(BaseModel):
    line_index: int = Field(description="0-based index of the cart line to remove")


class OrderSetFulfilmentInput(BaseModel):
    mode: Literal["delivery", "pickup"] = Field(description="Fulfilment mode: 'delivery' or 'pickup'")


class DeliverySetAddressInput(BaseModel):
    address_text: Optional[str] = Field(default=None, description="Delivery street address and area/landmark")
    lat: Optional[float] = Field(default=None, description="Latitude of pinned location")
    lng: Optional[float] = Field(default=None, description="Longitude of pinned location")


class OrderSetPickupInput(BaseModel):
    branch_id: str = Field(description="Pickup branch id: colombo07, nugegoda, or kandy")


class PromoApplyInput(BaseModel):
    code: str = Field(description="Promotional code, e.g. FRIDAY10 or STUDENT15")


class OrderPlaceOrderInput(BaseModel):
    cart_hash: str = Field(description="Exact summary_hash returned by order.show_summary")


class ToolSpec(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    schema_cls: Type[BaseModel]
    handler: Callable[..., Dict[str, Any]]
    requires_session: bool = True
    allowed_stages: Optional[List[str]] = None


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._register_defaults()

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def schemas(self, stage: Optional[str] = None) -> List[Dict[str, Any]]:
        """Exports OpenAI function-calling tool schemas, optionally filtered by session stage."""
        out = []
        for spec in self._tools.values():
            if stage is not None and spec.allowed_stages is not None:
                if stage not in spec.allowed_stages:
                    continue
            json_schema = spec.schema_cls.model_json_schema()
            json_schema.pop("title", None)
            out.append({
                "type": "function",
                "function": {
                    "name": spec.name.replace(".", "__"),
                    "description": f"[{spec.name}] {spec.description}",
                    "parameters": json_schema,
                },
            })
        return out

    def tools_for_stage(self, stage: str) -> List[Dict[str, Any]]:
        """Returns OpenAI function tool schemas valid for the given conversation stage."""
        return self.schemas(stage=stage)

    def call(
        self,
        name: str,
        session: Session,
        args: Optional[Dict[str, Any]] = None,
        **extra_deps: Any,
    ) -> Dict[str, Any]:
        """
        Validates tool arguments with Pydantic, checks state-machine stage guards,
        and executes the deterministic tool function against `session`.
        """
        normalized_name = name.replace("__", ".")
        spec = self._tools.get(normalized_name)
        if not spec:
            return {
                "ok": False,
                "error": "UNKNOWN_TOOL",
                "message": f"Tool '{name}' is not registered.",
            }

        if spec.allowed_stages and session.stage not in spec.allowed_stages:
            if normalized_name == "order.place_order":
                return {
                    "ok": False,
                    "error": "SUMMARY_REQUIRED",
                    "message": (
                        f"Cannot call '{normalized_name}' from stage '{session.stage}'. "
                        "Run 'order.show_summary' and wait for customer confirmation first."
                    ),
                }
            return {
                "ok": False,
                "error": "INVALID_STAGE",
                "message": (
                    f"Tool '{normalized_name}' is not allowed in stage '{session.stage}' "
                    f"(allowed: {', '.join(spec.allowed_stages)})."
                ),
            }

        raw_args = args or {}
        try:
            validated = spec.schema_cls(**raw_args)
        except ValidationError as e:
            first_msg = e.errors()[0].get("msg", str(e)) if e.errors() else str(e)
            return {
                "ok": False,
                "error": "INVALID_ARGS",
                "message": f"Invalid arguments for '{normalized_name}': {first_msg}",
            }

        call_kwargs = validated.model_dump()
        call_kwargs.update(extra_deps)
        if spec.requires_session:
            return spec.handler(session=session, **call_kwargs)
        return spec.handler(**call_kwargs)

    def _register_defaults(self) -> None:
        # Knowledge & menu read-only tools (allowed in any stage except handoff)
        self.register(ToolSpec(
            name="kb.ask",
            description="Ask a grounded question against the Pizza Hut knowledge base.",
            schema_cls=KBAskInput,
            handler=lambda session, question, **kw: kb_ask(question=question, session=session),
        ))
        self.register(ToolSpec(
            name="kb.search",
            description="Hybrid search over the knowledge base chunks.",
            schema_cls=KBSearchInput,
            handler=lambda session, query, k=4, **kw: kb_search(query=query, k=k),
        ))
        self.register(ToolSpec(
            name="menu.get_item",
            description="Get structured details and integer LKR prices for a menu item or combo.",
            schema_cls=MenuGetItemInput,
            handler=lambda item_id, **kw: menu_get_item(item_id=item_id),
            requires_session=False,
        ))
        self.register(ToolSpec(
            name="menu.list_items",
            description="List menu items filtered by category or vegetarian flag.",
            schema_cls=MenuListItemsInput,
            handler=lambda category=None, veg=None, **kw: menu_list_items(category=category, veg=veg),
            requires_session=False,
        ))
        self.register(ToolSpec(
            name="branch.list",
            description="List all Pizza Hut outlets with hours and current open/closed status.",
            schema_cls=EmptyInput,
            handler=branch_list,
        ))

        # Cart tools
        self.register(ToolSpec(
            name="cart.add_item",
            description="Add a menu item (with size, qty 1-20, notes, options) to the cart.",
            schema_cls=CartAddItemInput,
            handler=cart_add_item,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="cart.add_combo",
            description="Add a combo bundle (with slot choices) to the cart.",
            schema_cls=CartAddComboInput,
            handler=cart_add_combo,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="cart.update_item",
            description="Update quantity, size, notes, or options for a cart line.",
            schema_cls=CartUpdateItemInput,
            handler=cart_update_item,
            allowed_stages=["building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="cart.remove_item",
            description="Remove a line from the cart by its 0-based index.",
            schema_cls=CartRemoveItemInput,
            handler=cart_remove_item,
            allowed_stages=["building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="cart.view",
            description="View current cart lines and computed food subtotal in LKR.",
            schema_cls=EmptyInput,
            handler=cart_view,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="cart.clear",
            description="Clear all items from the cart and reset to browsing.",
            schema_cls=EmptyInput,
            handler=cart_clear,
            allowed_stages=["building_cart", "collecting_fulfilment", "confirming"],
        ))

        # Fulfilment & delivery tools
        self.register(ToolSpec(
            name="order.set_fulfilment",
            description="Set fulfilment mode to 'delivery' or 'pickup'.",
            schema_cls=OrderSetFulfilmentInput,
            handler=order_set_fulfilment,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="delivery.set_address",
            description="Resolve delivery address or location pin to a branch and delivery zone.",
            schema_cls=DeliverySetAddressInput,
            handler=delivery_set_address,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="order.set_pickup",
            description="Set pickup branch and verify pickup opening hours.",
            schema_cls=OrderSetPickupInput,
            handler=order_set_pickup,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="delivery.quote",
            description="Get delivery fee and ETA for the current branch and zone.",
            schema_cls=EmptyInput,
            handler=delivery_quote,
            allowed_stages=["collecting_fulfilment", "confirming"],
        ))

        # Promo tools
        self.register(ToolSpec(
            name="promo.apply",
            description="Validate and apply a promo code (e.g. FRIDAY10, STUDENT15) to the order.",
            schema_cls=PromoApplyInput,
            handler=promo_apply,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="promo.remove",
            description="Remove the active promo code from the order.",
            schema_cls=EmptyInput,
            handler=promo_remove,
            allowed_stages=["browsing", "building_cart", "collecting_fulfilment", "confirming"],
        ))

        # Order summary & checkout tools
        self.register(ToolSpec(
            name="order.show_summary",
            description="Validate the order, compute receipt totals, and transition to 'confirming'.",
            schema_cls=EmptyInput,
            handler=order_show_summary,
            allowed_stages=["building_cart", "collecting_fulfilment", "confirming"],
        ))
        self.register(ToolSpec(
            name="order.place_order",
            description="Place the confirmed order using the summary_hash from order.show_summary.",
            schema_cls=OrderPlaceOrderInput,
            handler=order_place_order,
            allowed_stages=["confirming"],
        ))
        self.register(ToolSpec(
            name="order.cancel_draft",
            description="Cancel the current draft order and reset the session.",
            schema_cls=EmptyInput,
            handler=order_cancel_draft,
            allowed_stages=["building_cart", "collecting_fulfilment", "confirming"],
        ))


registry = ToolRegistry()

