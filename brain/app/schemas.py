from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    senderId: str = Field(..., description="Customer WhatsApp ID or phone number")
    message: str = Field(..., description="Incoming message text")
    messageId: Optional[str] = Field(None, description="WhatsApp message ID")
    timestamp: Optional[int] = Field(None, description="Unix timestamp of message")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="Reply message text to send back to customer")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional debug/tracing metadata")

