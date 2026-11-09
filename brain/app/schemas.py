from typing import Literal, Optional
from pydantic import BaseModel


class IncomingMessage(BaseModel):
    user_id: str
    type: Literal["text", "audio", "location", "image", "other"]
    content: Optional[str] = None
    message_id: Optional[str] = None
    push_name: Optional[str] = None


class BrainReply(BaseModel):
    reply_text: Optional[str] = None
    reply_audio_url: Optional[str] = None  # used in Phase 6