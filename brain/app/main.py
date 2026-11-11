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
from app.voice.audio import AudioLimitError
from app.voice.stt import stt_service

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
        try:
            stt_res = stt_service.transcribe_b64(
                msg.audio_b64,
                mime=msg.audio_mime,
                declared_seconds=msg.audio_seconds,
            )
        except AudioLimitError as limit_err:
            log.info("user=%s audio rejected (%s): %s", msg.user_id, limit_err.code, limit_err.user_message)
            return BrainReply(
                reply_text=limit_err.user_message,
                meta=BrainReplyMeta(stage="browsing"),
            )
        except Exception as stt_err:
            log.warning("user=%s audio transcription failed: %s", msg.user_id, stt_err)
            return BrainReply(
                reply_text="Sorry, I couldn't quite hear that voice note clearly. Please try again or type your message 🙂",
                meta=BrainReplyMeta(stage="browsing"),
            )

        transcript = (stt_res.text or "").strip()
        if not transcript:
            return BrainReply(
                reply_text="I couldn't quite catch that voice note. Could you try speaking a bit closer or type your order? 🙂",
                meta=BrainReplyMeta(stage="browsing"),
            )

        msg.content = transcript
        msg.source = "voice"
        msg.stt_confidence = stt_res.confidence

    # All text, voice & location messages are orchestrated through the Central Orchestrator
    reply = await orchestrator.handle_message(msg)
    return reply


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
