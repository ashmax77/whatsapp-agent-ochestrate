from abc import ABC, abstractmethod
from typing import Optional, Tuple
from contextlib import asynccontextmanager
from app.state.session import Session
from app.schemas import BrainReply


class SessionStore(ABC):
    @abstractmethod
    async def get(self, user_id: str) -> Session:
        """Retrieves session for user_id, initializing a new one if not present."""
        pass

    @abstractmethod
    async def save(self, session: Session) -> None:
        """Persists the session."""
        pass

    @abstractmethod
    async def delete(self, user_id: str) -> None:
        """Deletes the session."""
        pass

    @abstractmethod
    @asynccontextmanager
    async def lock(self, user_id: str):
        """Asynchronous per-user lock context manager."""
        pass

    @abstractmethod
    async def is_duplicate_message(self, user_id: str, message_id: str) -> bool:
        """Checks if a message_id was already processed recently."""
        pass

    @abstractmethod
    async def get_cached_reply(self, user_id: str, message_id: str) -> Optional[BrainReply]:
        """Gets cached reply for a duplicate message if available."""
        pass

    @abstractmethod
    async def record_message_reply(self, user_id: str, message_id: str, reply: BrainReply) -> None:
        """Caches message_id and its reply with TTL (default 10 min) for deduplication."""
        pass

    @abstractmethod
    async def check_rate_limit(self, user_id: str, limit: int = 20, window_secs: int = 60) -> Tuple[bool, int]:
        """Checks if user has exceeded rate limit. Returns (is_allowed, remaining_quota)."""
        pass

