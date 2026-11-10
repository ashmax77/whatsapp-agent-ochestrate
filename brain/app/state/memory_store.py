import asyncio
import time
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Tuple
from app.state.session import Session
from app.state.session_store import SessionStore
from app.schemas import BrainReply
from app.config import settings

log = logging.getLogger("brain.memory_store")


class MemorySessionStore(SessionStore):
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._dedupe_cache: Dict[str, Tuple[float, BrainReply]] = {}  # key -> (expiry_ts, reply)
        self._rate_limits: Dict[str, List[float]] = {}  # user_id -> [timestamps]

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    @asynccontextmanager
    async def lock(self, user_id: str):
        lock = self._get_lock(user_id)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    async def get(self, user_id: str) -> Session:
        if user_id not in self._sessions:
            self._sessions[user_id] = Session(user_id=user_id)
        session = self._sessions[user_id]
        return session

    async def save(self, session: Session) -> None:
        self._sessions[session.user_id] = session

    async def delete(self, user_id: str) -> None:
        self._sessions.pop(user_id, None)

    def _cleanup_dedupe(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _) in self._dedupe_cache.items() if now > exp]
        for k in expired:
            self._dedupe_cache.pop(k, None)

    async def is_duplicate_message(self, user_id: str, message_id: str) -> bool:
        if not message_id:
            return False
        self._cleanup_dedupe()
        key = f"{user_id}:{message_id}"
        return key in self._dedupe_cache

    async def get_cached_reply(self, user_id: str, message_id: str) -> Optional[BrainReply]:
        if not message_id:
            return None
        self._cleanup_dedupe()
        key = f"{user_id}:{message_id}"
        entry = self._dedupe_cache.get(key)
        return entry[1] if entry else None

    async def record_message_reply(self, user_id: str, message_id: str, reply: BrainReply) -> None:
        if not message_id:
            return
        key = f"{user_id}:{message_id}"
        expiry = time.time() + settings.DEDUPE_TTL_SECONDS
        self._dedupe_cache[key] = (expiry, reply)

    async def check_rate_limit(
        self, user_id: str, limit: Optional[int] = None, window_secs: int = 60
    ) -> Tuple[bool, int]:
        max_msgs = limit if limit is not None else settings.RATE_LIMIT_PER_MINUTE
        now = time.time()
        window_start = now - window_secs

        timestamps = self._rate_limits.get(user_id, [])
        # Prune older than window
        timestamps = [ts for ts in timestamps if ts > window_start]
        if len(timestamps) >= max_msgs:
            self._rate_limits[user_id] = timestamps
            return False, 0

        timestamps.append(now)
        self._rate_limits[user_id] = timestamps
        remaining = max(0, max_msgs - len(timestamps))
        return True, remaining

    def clear(self) -> None:
        self._sessions.clear()
        self._dedupe_cache.clear()
        self._rate_limits.clear()

