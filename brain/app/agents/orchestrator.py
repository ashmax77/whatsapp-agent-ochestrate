"""
Orchestrator Agent: Routes incoming customer messages to the appropriate specialized agent.
"""
from app.state.session import CustomerSession

class Orchestrator:
    def __init__(self):
        pass

    async def handle_message(self, session: CustomerSession, message: str) -> str:
        """
        Orchestrates routing between menu, order, delivery, promo, escalation, and post-order agents.
        """
        session.add_message("user", message)
        
        # Basic response placeholder until specialized agents are implemented (Phase 4-7)
        reply = "Hello! Welcome to Pizza Agent. How can I help you with your order today?"
        session.add_message("assistant", reply)
        return reply

orchestrator = Orchestrator()

