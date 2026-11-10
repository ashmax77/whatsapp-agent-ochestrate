"""
Order Agent: Thin deterministic agent that owns cart, fulfilment, summary, and order placement tools (Decision D6).
Zero LLM calls—all actions execute through the deterministic tool registry.
"""
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.state.session import Session
from app.tools.registry import registry


class OrderAgent(BaseAgent):
    TOOL_NAMES: List[str] = [
        "cart.add_item",
        "cart.add_combo",
        "cart.update_item",
        "cart.remove_item",
        "cart.view",
        "cart.clear",
        "order.set_fulfilment",
        "order.set_pickup",
        "order.show_summary",
        "order.place_order",
        "order.cancel_draft",
    ]

    def __init__(self):
        super().__init__(
            name="order_agent",
            description="Deterministic agent managing cart items, combos, pickup selection, order summary, and order placement.",
        )

    def execute_tool(
        self,
        tool_name: str,
        session: Session,
        args: Optional[Dict[str, Any]] = None,
        **extra_deps: Any,
    ) -> Dict[str, Any]:
        if tool_name not in self.TOOL_NAMES:
            return {
                "ok": False,
                "error": "UNAUTHORIZED_TOOL",
                "message": f"OrderAgent does not own tool '{tool_name}'.",
            }
        return registry.call(tool_name, session=session, args=args, **extra_deps)

    def run(self, message: str, session: Session, **kwargs: Any) -> Dict[str, Any]:
        tool_name = kwargs.pop("tool_name", "cart.view")
        args = kwargs.pop("args", {})
        return self.execute_tool(tool_name, session=session, args=args, **kwargs)


order_agent = OrderAgent()
