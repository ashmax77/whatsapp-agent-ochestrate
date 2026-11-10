"""
Delivery Agent: Thin deterministic agent that owns branch listing, address/pin resolution, and delivery quoting (Decision D6).
"""
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.state.session import Session
from app.tools.registry import registry


class DeliveryAgent(BaseAgent):
    TOOL_NAMES: List[str] = [
        "branch.list",
        "delivery.set_address",
        "delivery.quote",
    ]

    def __init__(self):
        super().__init__(
            name="delivery_agent",
            description="Deterministic agent resolving delivery addresses, location pins, branch opening hours, and delivery fees.",
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
                "message": f"DeliveryAgent does not own tool '{tool_name}'.",
            }
        return registry.call(tool_name, session=session, args=args, **extra_deps)

    def run(self, message: str, session: Session, **kwargs: Any) -> Dict[str, Any]:
        tool_name = kwargs.pop("tool_name", "branch.list")
        args = kwargs.pop("args", {})
        return self.execute_tool(tool_name, session=session, args=args, **kwargs)


delivery_agent = DeliveryAgent()
