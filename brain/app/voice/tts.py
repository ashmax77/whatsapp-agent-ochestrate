"""
(Phase 6) Text-to-Speech (TTS) audio synthesis module.
Replies with a voice note (audio/ogg; codecs=opus) ONLY when:
1. settings.TTS_ENABLED is True
2. Customer sent a voice note (source == "voice")
3. Language is supported (falls back gracefully to text-only for Sinhala/Tamil or on error).
Text always accompanies the reply so receipts and LKR totals remain readable.
"""

import base64
import io
import logging
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings
from app.voice.audio import find_ffmpeg

log = logging.getLogger("brain.voice.tts")


def _generate_minimal_tone_wav(duration_s: float = 0.25, sample_rate: int = 16000) -> bytes:
    """Generates a tiny, valid 16 kHz mono WAV buffer for stub TTS testing."""
    buf = io.BytesIO()
    n_samples = int(duration_s * sample_rate)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            val = int(4000 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _convert_to_ogg_opus(raw_audio: bytes, in_ext: str = ".wav") -> Tuple[bytes, str]:
    """Converts audio bytes to OGG/Opus via ffmpeg if available; cleans up temp files immediately."""
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        return raw_audio, "audio/ogg; codecs=opus"

    with tempfile.TemporaryDirectory(prefix="pizza_tts_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_file = tmp_path / f"tts_in{in_ext}"
        out_file = tmp_path / "tts_out.ogg"
        in_file.write_bytes(raw_audio)

        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-i",
            str(in_file),
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-vbr",
            "on",
            "-f",
            "ogg",
            str(out_file),
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10.0,
                check=False,
            )
            if proc.returncode == 0 and out_file.exists():
                return out_file.read_bytes(), "audio/ogg; codecs=opus"
        except Exception as exc:
            log.warning("ffmpeg OGG/Opus conversion failed: %s", exc)

    return raw_audio, "audio/ogg; codecs=opus"


class TTSService:
    def synthesize_for_reply(
        self,
        text: str,
        language: str = "en",
        source: str = "text",
    ) -> Optional[Tuple[str, str]]:
        """
        Returns (audio_b64, audio_mime) when TTS is enabled, the customer sent a voice note,
        and the language is supported. Otherwise returns None (falling back to text-only).
        """
        if not settings.TTS_ENABLED:
            return None
        if source != "voice":
            return None
        if not text or not text.strip():
            return None

        # Sinhala ("si") and Tamil ("ta") TTS often have poor pronunciation for local names/LKR;
        # fall back to text per Phase 6 design (section 9).
        if language in ("si", "ta"):
            log.info("TTS skipped for language='%s'; falling back to text reply", language)
            return None

        provider = (settings.TTS_PROVIDER or "openai").lower().strip()

        if provider == "stub":
            wav_bytes = _generate_minimal_tone_wav()
            return base64.b64encode(wav_bytes).decode("ascii"), "audio/ogg; codecs=opus"

        try:
            api_key = settings.CODECRAFT_KEY or settings.OPENAI_API_KEY
            if not api_key:
                log.warning("TTS enabled but no API key found; falling back to text")
                return None

            from openai import OpenAI

            client_kwargs = {"api_key": api_key, "timeout": 15.0}
            if settings.OPENAI_BASE_URL:
                client_kwargs["base_url"] = settings.OPENAI_BASE_URL
            client = OpenAI(**client_kwargs)

            # Strip heavy receipt formatting lines so voice output stays concise
            spoken_text = " ".join(line.strip() for line in text.splitlines() if line.strip())
            if len(spoken_text) > 500:
                spoken_text = spoken_text[:500]

            resp = client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=spoken_text,
                response_format="opus",
            )
            raw_bytes = resp.read() if hasattr(resp, "read") else bytes(resp.content)
            if not raw_bytes:
                return None
            ogg_bytes, mime = _convert_to_ogg_opus(raw_bytes, in_ext=".ogg")
            return base64.b64encode(ogg_bytes).decode("ascii"), mime
        except Exception as exc:
            log.warning("TTS synthesis failed (%s); falling back to text-only reply", exc)
            return None


tts_service = TTSService()


async def synthesize_speech(text: str) -> bytes:
    """Backward-compatible async helper."""
    res = tts_service.synthesize_for_reply(text, language="en", source="voice")
    if not res:
        return b""
    return base64.b64decode(res[0])
