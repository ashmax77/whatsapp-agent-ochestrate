from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Session:
    user_id: str
    stage: str = "browsing"  # browsing -> building_cart -> collecting_address -> confirming -> placed
    cart: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    message_count: int = 0
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_SESSIONS: dict[str, Session] = {}  # in-memory for now; swap for Redis later


def get_session(user_id: str) -> Session:
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = Session(user_id=user_id)
    session = _SESSIONS[user_id]
    session.last_seen = datetime.now(timezone.utc)
    return session