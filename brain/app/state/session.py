from typing import Dict, Any, Optional
from datetime import datetime, timezone

class CustomerSession:
    def __init__(self, sender_id: str):
        self.sender_id = sender_id
        self.history: list[dict[str, str]] = []
        self.current_order: dict[str, Any] = {"items": [], "address": None}
        self.stage: str = "initial"
        self.last_active: datetime = datetime.now(timezone.utc)

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        self.last_active = datetime.now(timezone.utc)

class SessionManager:
    """
    In-memory session manager for per-customer sessions.
    Can be replaced or backed by Redis later.
    """
    def __init__(self):
        self._sessions: Dict[str, CustomerSession] = {}

    def get_or_create(self, sender_id: str) -> CustomerSession:
        if sender_id not in self._sessions:
            self._sessions[sender_id] = CustomerSession(sender_id)
        return self._sessions[sender_id]

    def get(self, sender_id: str) -> Optional[CustomerSession]:
        return self._sessions.get(sender_id)

    def clear(self, sender_id: str):
        if sender_id in self._sessions:
            del self._sessions[sender_id]

session_manager = SessionManager()

