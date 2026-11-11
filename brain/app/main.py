import sys
import logging
from pathlib import Path
from fastapi import FastAPI

# Ensure the 'brain' directory and local venv site-packages are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Auto-bind .venv site-packages if running from an unactivated environment
VENV_SITE = BASE_DIR / ".venv" / "Lib" / "site-packages"
if VENV_SITE.exists() and str(VENV_SITE) not in sys.path:
    sys.path.insert(0, str(VENV_SITE))

from app.schemas import IncomingMessage, BrainReply, BrainReplyMeta
from app.agents.orchestrator import orchestrator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("brain")

app = FastAPI(title="Pizza Agent Brain")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/message", response_model=BrainReply)
async def handle_message(msg: IncomingMessage) -> BrainReply:
    log.info("user=%s type=%s content=%r message_id=%s", msg.user_id, msg.type, msg.content, msg.message_id)

    if msg.type == "audio":
        return BrainReply(
            reply_text="Voice notes are coming soon! For now, please type your message or order 🙂",
            meta=BrainReplyMeta(stage="browsing"),
        )

    # All text & location messages are orchestrated through the Central Orchestrator
    reply = await orchestrator.handle_message(msg)
    return reply


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
