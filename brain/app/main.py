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
from app.agents.knowledge_agent import knowledge_agent

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

    if msg.type == "text":
        content = (msg.content or "").strip()
        if not content:
            text = "Hello! How can I help you today? 🍕"
        else:
            result = knowledge_agent.ask(question=content, session=session)
            text = result.get("answer", "")
    elif msg.type == "audio":
        text = "Voice notes are coming soon! For now, please type your order 🙂"
    else:
        text = "I can only read text messages for now."

    return BrainReply(reply_text=text)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
