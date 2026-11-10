from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class LocationPayload(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    address: Optional[str] = None


class IncomingMessage(BaseModel):
    user_id: str
    type: Literal["text", "audio", "location", "image", "other"] = "text"
    content: Optional[str] = None
    message_id: Optional[str] = None
    push_name: Optional[str] = None
    location: Optional[LocationPayload] = None
    audio_b64: Optional[str] = None
    audio_mime: Optional[str] = None
    timestamp: Optional[int] = None


class BrainReplyMeta(BaseModel):
    stage: Optional[str] = "browsing"
    branch_id: Optional[str] = None
    trace_id: Optional[str] = None


class BrainReply(BaseModel):
    reply_text: Optional[str] = None
    reply_audio_url: Optional[str] = None  # backward-compatible helper
    reply_audio_b64: Optional[str] = None
    reply_audio_mime: Optional[str] = None
    meta: BrainReplyMeta = Field(default_factory=BrainReplyMeta)
