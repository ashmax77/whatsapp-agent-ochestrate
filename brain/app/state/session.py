import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

StageType = Literal[
    "browsing",
    "building_cart",
    "collecting_fulfilment",
    "confirming",
    "placed",
    "handoff",
]

FulfilmentType = Literal["delivery", "pickup"]


class CartLine(BaseModel):
    item_id: str  # item or combo id
    size: str = "regular"
    qty: int = 1
    notes: Optional[str] = None
    options: Optional[Dict[str, Any]] = None  # crust, extra_toppings, sauce, flavour
    combo_choices: Optional[Dict[str, str]] = None  # e.g. {"large_pizza": "pz_supreme", "medium_pizza": "pz_veggie"}

    def same_identity(self, other: "CartLine") -> bool:
        """Two cart lines merge if item_id, size, notes, options and combo_choices all match."""
        return (
            self.item_id == other.item_id
            and self.size.lower() == other.size.lower()
            and (self.notes or "").strip().lower() == (other.notes or "").strip().lower()
            and (self.options or {}) == (other.options or {})
            and (self.combo_choices or {}) == (other.combo_choices or {})
        )


class Session(BaseModel):
    user_id: str
    stage: StageType = "browsing"
    fulfilment: Optional[FulfilmentType] = None
    branch_id: Optional[str] = None  # colombo07 | nugegoda | kandy
    cart: List[CartLine] = Field(default_factory=list)
    address: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    delivery_zone: Optional[str] = None
    promo_code: Optional[str] = None
    summary_hash: Optional[str] = None  # hash of cart+fulfilment+branch+promo shown to customer
    summary_msg_no: Optional[int] = None  # message_count when summary was shown
    language: Optional[str] = None  # "en" | "si" | "ta" | "mixed"
    history: List[Dict[str, str]] = Field(default_factory=list)  # last N turns, trimmed (N=12)
    message_count: int = 0
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    handoff_until: Optional[datetime] = None
    last_order_no: Optional[str] = None
    pending_voice_transcript: Optional[str] = None

    def add_history(self, role: str, content: str, max_turns: int = 12) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > max_turns:
            self.history = self.history[-max_turns:]
        self.last_seen = datetime.now(timezone.utc)

    def compute_summary_hash(self) -> str:
        """Deterministic SHA-256 fingerprint of cart + fulfilment + branch + zone + promo."""
        payload = {
            "branch_id": self.branch_id,
            "fulfilment": self.fulfilment,
            "address": (self.address or "").strip().lower() if self.fulfilment == "delivery" else None,
            "delivery_zone": self.delivery_zone if self.fulfilment == "delivery" else None,
            "promo_code": self.promo_code,
            "cart": [
                {
                    "item_id": line.item_id,
                    "size": line.size.lower(),
                    "qty": line.qty,
                    "notes": (line.notes or "").strip(),
                    "options": line.options or {},
                    "combo_choices": line.combo_choices or {},
                }
                for line in self.cart
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def invalidate_summary(self) -> None:
        """Any mutation to cart, fulfilment, branch, address or promo invalidates a prior summary."""
        self.summary_hash = None
        self.summary_msg_no = None
        if self.stage == "confirming":
            if not self.cart:
                self.stage = "browsing"
            elif self.fulfilment:
                self.stage = "collecting_fulfilment"
            else:
                self.stage = "building_cart"

    def reset_cart(self) -> None:
        self.cart = []
        self.fulfilment = None
        self.branch_id = None
        self.address = None
        self.location = None
        self.delivery_zone = None
        self.promo_code = None
        self.summary_hash = None
        self.summary_msg_no = None
        self.pending_voice_transcript = None
        self.stage = "browsing"


_SESSIONS: Dict[str, Session] = {}
_STORE_INSTANCE = None


def get_session_store():
    """Returns singleton SessionStore (RedisSessionStore if configured, else MemorySessionStore)."""
    global _STORE_INSTANCE
    if _STORE_INSTANCE is None:
        from app.config import settings

        if settings.REDIS_URL:
            from app.state.redis_store import RedisSessionStore
            _STORE_INSTANCE = RedisSessionStore(settings.REDIS_URL)
        else:
            from app.state.memory_store import MemorySessionStore
            _STORE_INSTANCE = MemorySessionStore()
    return _STORE_INSTANCE


def get_session(user_id: str) -> Session:
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = Session(user_id=user_id)
    session = _SESSIONS[user_id]
    session.last_seen = datetime.now(timezone.utc)
    return session


def clear_sessions() -> None:
    global _STORE_INSTANCE
    _SESSIONS.clear()
    if _STORE_INSTANCE is not None and hasattr(_STORE_INSTANCE, "clear"):
        _STORE_INSTANCE.clear()
