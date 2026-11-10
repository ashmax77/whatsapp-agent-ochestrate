import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, Tuple
from app.state.session import Session
from app.state.session_store import SessionStore
from app.state.memory_store import MemorySessionStore
from app.schemas import BrainReply
from app.config import settings

log = logging.getLogger("brain.redis_store")


class RedisSessionStore(SessionStore):
    """
    Redis session store with JSON serialization, TTL, and distributed locks.
    Falls back gracefully to MemorySessionStore if Redis is unavailable or unconfigured.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url if redis_url is not None else settings.REDIS_URL
        self._fallback = MemorySessionStore()
        self._redis = None
        self._available = False

        if self.redis_url:
            try:
                import redis.asyncio as aioredis  # type: ignore

                self._redis = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                )
                self._available = True
                log.info("RedisSessionStore initialized for %s", self.redis_url)
            except Exception as e:
                log.warning("Could not initialize Redis client (%s). Using in-memory fallback.", e)
                self._available = False

    @asynccontextmanager
    async def lock(self, user_id: str):
        if not self._available or not self._redis:
            async with self._fallback.lock(user_id):
                yield
            return

        lock_key = f"lock:user:{user_id}"
        lock = self._redis.lock(lock_key, timeout=30, blocking_timeout=10)
        acquired = await lock.acquire()
        try:
            yield
        finally:
            if acquired:
                try:
                    await lock.release()
                except Exception:
                    pass

    async def get(self, user_id: str) -> Session:
        if not self._available or not self._redis:
            return await self._fallback.get(user_id)

        key = f"session:{user_id}"
        try:
            raw = await self._redis.get(key)
            if raw:
                data = json.loads(raw)
                return Session(**data)
        except Exception as e:
            log.warning("Redis get error for %s (%s). Falling back to memory.", user_id, e)

        return await self._fallback.get(user_id)

    async def save(self, session: Session) -> None:
        if not self._available or not self._redis:
            return await self._fallback.save(session)

        key = f"session:{session.user_id}"
        try:
            raw = session.model_dump_json()
            await self._redis.set(key, raw, ex=settings.SESSION_TTL_SECONDS)
        except Exception as e:
            log.warning("Redis save error for %s (%s).", session.user_id, e)
            await self._fallback.save(session)

    async def delete(self, user_id: str) -> None:
        if not self._available or not self._redis:
            return await self._fallback.delete(user_id)

        try:
            await self._redis.delete(f"session:{user_id}")
        except Exception:
            pass
        await self._fallback.delete(user_id)

    async def is_duplicate_message(self, user_id: str, message_id: str) -> bool:
        if not self._available or not self._redis:
            return await self._fallback.is_duplicate_message(user_id, message_id)

        if not message_id:
            return False
        key = f"dedupe:{user_id}:{message_id}"
        try:
            exists = await self._redis.exists(key)
            return bool(exists)
        except Exception:
            return await self._fallback.is_duplicate_message(user_id, message_id)

    async def get_cached_reply(self, user_id: str, message_id: str) -> Optional[BrainReply]:
        if not self._available or not self._redis:
            return await self._fallback.get_cached_reply(user_id, message_id)

        if not message_id:
            return None
        key = f"dedupe:{user_id}:{message_id}"
        try:
            raw = await self._redis.get(key)
            if raw:
                return BrainReply(**json.loads(raw))
        except Exception:
            pass
        return await self._fallback.get_cached_reply(user_id, message_id)

    async def record_message_reply(self, user_id: str, message_id: str, reply: BrainReply) -> None:
        if not self._available or not self._redis:
            return await self._fallback.record_message_reply(user_id, message_id, reply)

        if not message_id:
            return
        key = f"dedupe:{user_id}:{message_id}"
        try:
            await self._redis.set(key, reply.model_dump_json(), ex=settings.DEDUPE_TTL_SECONDS)
        except Exception:
            await self._fallback.record_message_reply(user_id, message_id, reply)

    async def check_rate_limit(
        self, user_id: str, limit: Optional[int] = None, window_secs: int = 60
    ) -> Tuple[bool, int]:
        if not self._available or not self._redis:
            return await self._fallback.check_rate_limit(user_id, limit=limit, window_secs=window_secs)

        max_msgs = limit if limit is not None else settings.RATE_LIMIT_PER_MINUTE
        key = f"ratelimit:{user_id}"
        try:
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, window_secs)
            if current > max_msgs:
                return False, 0
            return True, max(0, max_msgs - current)
        except Exception:
            return await self._fallback.check_rate_limit(user_id, limit=limit, window_secs=window_secs)

