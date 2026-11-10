"""
Promo Agent: Thin deterministic agent that owns promo validation, application, and removal (Decision D6).
"""
from typing import Any, Dict, List, Optional
from app.agents.base import BaseAgent
from app.state.session import Session
from app.tools.registry import registry


class PromoAgent(BaseAgent):
    TOOL_NAMES: List[str] = [
        "promo.apply",
        "promo.remove",
    ]

    def __init__(self):
        super().__init__(
            name="promo_agent",
            description="Deterministic agent validating and applying promotional codes against day, date, branch, and subtotal rules.",
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
                "message": f"PromoAgent does not own tool '{tool_name}'.",
            }
        return registry.call(tool_name, session=session, args=args, **extra_deps)

    def run(self, message: str, session: Session, **kwargs: Any) -> Dict[str, Any]:
        tool_name = kwargs.pop("tool_name", "promo.remove")
        args = kwargs.pop("args", {})
        return self.execute_tool(tool_name, session=session, args=args, **kwargs)


promo_agent = PromoAgent()
