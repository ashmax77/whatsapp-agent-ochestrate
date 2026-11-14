import asyncio
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Query, Response

# Ensure the 'brain' directory and local venv site-packages are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Auto-bind .venv site-packages if running from an unactivated environment
VENV_SITE = BASE_DIR / ".venv" / "Lib" / "site-packages"
if VENV_SITE.exists() and str(VENV_SITE) not in sys.path:
    sys.path.insert(0, str(VENV_SITE))

from app.config import settings
from app.schemas import IncomingMessage, BrainReply, BrainReplyMeta
from app.agents.orchestrator import orchestrator
from app.services.metrics import metrics
from app.db.order_repo import order_repo
from app.state.session import get_session_store
from app.voice.audio import AudioLimitError
from app.voice.stt import stt_service

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("brain")

app = FastAPI(title="Pizza Agent Brain")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/extended")
def health_extended():
    """Detailed health check for container probes and monitoring."""
    db_ok = False
    try:
        with order_repo._connect() as conn:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
    except Exception as e:
        log.warning("Health check DB error: %s", e)

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "session_store": "active",
        "uptime_seconds": round(time.time() - metrics.start_time, 1),
    }


@app.get("/metrics")
def get_metrics(format: Optional[str] = Query(default=None)):
    """Prometheus telemetry and JSON statistics endpoint."""
    if format == "json":
        return metrics.to_dict()
    return Response(content=metrics.to_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/admin/forget")
async def forget_customer(payload: dict, x_internal_secret: Optional[str] = Header(None)):
    """GDPR / Right-to-be-forgotten privacy endpoint."""
    if not settings.INTERNAL_SECRET or x_internal_secret != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    res = order_repo.forget_customer(user_id)
    # Clear active session in memory/Redis
    session_store = get_session_store()
    session = await session_store.get(user_id)
    session.history.clear()
    session.cart.clear()
    session.stage = "browsing"
    await session_store.save(session)

    log.info("admin forget completed for user=%s: %s", user_id, res)
    return {"ok": True, "result": res}


async def _run_blocking(fn, *args, **kwargs):
    """Offload CPU-heavy audio work to a thread pool under asyncio without breaking coro-stepped tests."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


@app.post("/message", response_model=BrainReply)
async def handle_message(msg: IncomingMessage) -> BrainReply:
    t0 = time.time()
    log.info("user=%s type=%s content=%r message_id=%s", msg.user_id, msg.type, msg.content, msg.message_id)
    metrics.record_message(msg.type)

    if msg.type == "audio":
        try:
            stt_res = await _run_blocking(
                stt_service.transcribe_b64,
                msg.audio_b64,
                mime=msg.audio_mime,
                declared_seconds=msg.audio_seconds,
            )
        except AudioLimitError as limit_err:
            log.info("user=%s audio rejected (%s): %s", msg.user_id, limit_err.code, limit_err.user_message)
            metrics.record_request("/message", 200, time.time() - t0)
            return BrainReply(
                reply_text=limit_err.user_message,
                meta=BrainReplyMeta(stage="browsing"),
            )
        except Exception as stt_err:
            log.warning("user=%s audio transcription failed: %s", msg.user_id, stt_err)
            metrics.record_request("/message", 200, time.time() - t0)
            return BrainReply(
                reply_text="Sorry, I couldn't quite hear that voice note clearly. Please try again or type your message 🙂",
                meta=BrainReplyMeta(stage="browsing"),
            )

        transcript = (stt_res.text or "").strip()
        if not transcript:
            metrics.record_request("/message", 200, time.time() - t0)
            return BrainReply(
                reply_text="I couldn't quite catch that voice note. Could you try speaking a bit closer or type your order? 🙂",
                meta=BrainReplyMeta(stage="browsing"),
            )

        msg.content = transcript
        msg.source = "voice"
        msg.stt_confidence = stt_res.confidence

    # All text, voice & location messages are orchestrated through the Central Orchestrator
    try:
        reply = await orchestrator.handle_message(msg)
        status_code = 200
    except Exception as e:
        status_code = 500
        metrics.record_request("/message", status_code, time.time() - t0)
        raise e

    metrics.record_request("/message", status_code, time.time() - t0)
    return reply


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
