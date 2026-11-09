import sys
import logging
from pathlib import Path
from fastapi import FastAPI

# Ensure the 'brain' directory is in sys.path so 'import app...' works from anywhere
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.schemas import IncomingMessage, BrainReply
from app.state.session import get_session

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("brain")

app = FastAPI(title="Pizza Agent Brain")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/message", response_model=BrainReply)
def handle_message(msg: IncomingMessage):
    session = get_session(msg.user_id)
    session.message_count += 1
    log.info("user=%s type=%s content=%r", msg.user_id, msg.type, msg.content)

    # Phase 2: fixed reply, just proves the loop and session state work.
    # Later this line becomes: reply = orchestrator.run(session, msg)
    if msg.type == "text":
        text = (
            f"Hi {msg.push_name or 'there'}! 🍕 This is the Pizza Hut assistant. "
            f"(message #{session.message_count} in this session) "
            f"You said: {msg.content}"
        )
    elif msg.type == "audio":
        text = "Voice notes are coming soon! For now, please type your order 🙂"
    else:
        text = "I can only read text messages for now."

    return BrainReply(reply_text=text)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
