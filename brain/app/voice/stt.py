"""
(Phase 6) Speech-to-Text transcription module with Faster-Whisper, OpenAI Audio API fallback,
and deterministic stub support for automated testing and voice evaluation.
"""

import logging
import math
from pathlib import Path
from typing import Callable, Optional
from pydantic import BaseModel

from app.config import settings
from app.services.language import detect_language
from app.voice.audio import ephemeral_wav_file

log = logging.getLogger("brain.voice.stt")

# Domain vocabulary prompt to bias Whisper toward accurate Sri Lankan area names & Pizza Hut menu items
DOMAIN_PROMPT = (
    "Pizza Hut Sri Lanka order: Margherita, Supreme, Veggie Delight, Chicken Tikka, "
    "BBQ Chicken, Devilled Chicken, Cheese Lover, Garlic Bread, Cheesy Garlic Bread, "
    "Chicken Wings, Potato Wedges, Chicken Alfredo Pasta, Chocolate Lava Cake, Ice Cream Cup, "
    "Family Combo, personal, medium, large, classic pan, thin crispy, cheese stuffed, "
    "Colombo 07, Cinnamon Gardens, Bambalapitiya, Kollupitiya, Wellawatte, Borella, "
    "Nugegoda, Maharagama, Delkanda, Kohuwala, Nawala, Kotte, Kandy, Peradeniya, Katugastota, "
    "delivery, pickup, FRIDAY10, STUDENT15, LKR."
)


class TranscriptionResult(BaseModel):
    text: str
    language: str = "en"  # "en" | "si" | "ta" | "mixed"
    confidence: float = 0.90
    duration_s: float = 0.0
    provider: str = "stub"


def _load_audio_input(wav_path: Path):
    """Loads a 16 kHz mono 16-bit PCM WAV directly into a float32 NumPy array (bypasses PyAV)."""
    try:
        import wave
        import numpy as np

        with wave.open(str(wav_path), "rb") as wf:
            if wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getframerate() == 16000:
                pcm = wf.readframes(wf.getnframes())
                return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        pass
    return str(wav_path)


def _normalize_whisper_lang(raw_lang: Optional[str], transcript: str) -> str:
    script_lang = detect_language(transcript)
    if script_lang in ("si", "ta"):
        return script_lang
    code = (raw_lang or "en").lower().strip()
    if code in ("si", "sin", "sinhala"):
        return "si"
    if code in ("ta", "tam", "tamil"):
        return "ta"
    return "en"


class STTService:
    def __init__(self):
        self._whisper_model = None
        self._whisper_model_name: Optional[str] = None
        self._stub_handler: Optional[Callable[[Path, float], TranscriptionResult]] = None

    def set_stub_handler(
        self, handler: Optional[Callable[[Path, float], TranscriptionResult]]
    ) -> None:
        """Allows unit/integration tests to inject a deterministic STT stub."""
        self._stub_handler = handler

    def _get_faster_whisper(self):
        model_name = settings.STT_MODEL or "small"
        if self._whisper_model is None or self._whisper_model_name != model_name:
            from faster_whisper import WhisperModel  # type: ignore

            log.info("Loading faster-whisper model '%s' on CPU (int8)...", model_name)
            self._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            self._whisper_model_name = model_name
        return self._whisper_model

    def preload_model(self) -> None:
        """Warm-loads the configured faster-whisper model into memory."""
        if (settings.STT_PROVIDER or "").lower().strip() == "faster_whisper":
            self._get_faster_whisper()

    def transcribe_file(self, wav_path: Path, duration_s: float = 0.0) -> TranscriptionResult:
        """Transcribes a 16 kHz mono WAV file using the configured STT provider."""
        if self._stub_handler is not None:
            return self._stub_handler(wav_path, duration_s)

        provider = (settings.STT_PROVIDER or "faster_whisper").lower().strip()

        if provider == "stub":
            return TranscriptionResult(
                text="",
                language="en",
                confidence=0.0,
                duration_s=duration_s,
                provider="stub",
            )

        if provider == "faster_whisper":
            try:
                return self._transcribe_with_faster_whisper(wav_path, duration_s)
            except Exception as fw_err:
                log.warning(
                    "faster-whisper transcription failed (%s); attempting API fallback", fw_err
                )
                return self._transcribe_with_openai(wav_path, duration_s)

        if provider == "openai":
            return self._transcribe_with_openai(wav_path, duration_s)

        # Default fallback chain
        try:
            return self._transcribe_with_faster_whisper(wav_path, duration_s)
        except Exception:
            return self._transcribe_with_openai(wav_path, duration_s)

    def _transcribe_with_faster_whisper(
        self, wav_path: Path, duration_s: float
    ) -> TranscriptionResult:
        model = self._get_faster_whisper()
        audio_input = _load_audio_input(wav_path)
        try:
            segments_gen, info = model.transcribe(
                audio_input,
                beam_size=5,
                initial_prompt=DOMAIN_PROMPT,
                vad_filter=True,
            )
            segments = list(segments_gen)
        except ValueError:
            segments = []
            info = None

        texts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        full_text = " ".join(texts).strip()

        # Very short voice notes ("yes", "no", "delivery") can be clipped by Silero VAD; retry unfiltered
        if not full_text:
            segments_gen, info = model.transcribe(
                audio_input,
                beam_size=5,
                initial_prompt=DOMAIN_PROMPT,
                vad_filter=False,
            )
            segments = list(segments_gen)
            texts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
            full_text = " ".join(texts).strip()

        if not segments or not full_text:
            return TranscriptionResult(
                text="",
                language="en",
                confidence=0.0,
                duration_s=duration_s or float(getattr(info, "duration", 0.0) or 0.0),
                provider="faster_whisper",
            )

        # Compute confidence from average segment log-probabilities and no_speech_prob
        probs = []
        for seg in segments:
            avg_lp = float(getattr(seg, "avg_logprob", -0.3) or -0.3)
            no_speech = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            seg_conf = max(0.0, min(1.0, math.exp(avg_lp))) * (1.0 - 0.5 * no_speech)
            probs.append(seg_conf)

        confidence = round(sum(probs) / len(probs), 3) if probs else 0.80
        lang = _normalize_whisper_lang(getattr(info, "language", "en"), full_text)
        actual_duration = duration_s or float(getattr(info, "duration", 0.0) or 0.0)

        return TranscriptionResult(
            text=full_text,
            language=lang,
            confidence=confidence,
            duration_s=actual_duration,
            provider="faster_whisper",
        )

    def _transcribe_with_openai(
        self, wav_path: Path, duration_s: float
    ) -> TranscriptionResult:
        api_key = settings.CODECRAFT_KEY or settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("No API key available for OpenAI STT fallback")

        from openai import OpenAI

        client_kwargs = {"api_key": api_key, "timeout": 15.0}
        if settings.OPENAI_BASE_URL:
            client_kwargs["base_url"] = settings.OPENAI_BASE_URL
        client = OpenAI(**client_kwargs)

        model_name = (
            settings.STT_MODEL
            if settings.STT_MODEL and "whisper" in settings.STT_MODEL.lower()
            else "whisper-1"
        )

        with open(wav_path, "rb") as audio_file:
            resp = client.audio.transcriptions.create(
                model=model_name,
                file=audio_file,
                prompt=DOMAIN_PROMPT,
            )

        text = (getattr(resp, "text", "") or "").strip()
        lang = _normalize_whisper_lang(getattr(resp, "language", "en"), text)
        return TranscriptionResult(
            text=text,
            language=lang,
            confidence=0.88 if text else 0.0,
            duration_s=duration_s,
            provider="openai",
        )

    def transcribe_b64(
        self,
        audio_b64: Optional[str],
        mime: Optional[str] = None,
        declared_seconds: Optional[float] = None,
    ) -> TranscriptionResult:
        """
        Validates base64 audio, converts to 16 kHz mono WAV in an ephemeral temp file,
        transcribes it, and guarantees immediate deletion of all raw/converted audio files.
        """
        with ephemeral_wav_file(
            audio_b64, mime=mime, declared_seconds=declared_seconds
        ) as (wav_path, duration_s):
            return self.transcribe_file(wav_path, duration_s=duration_s)


stt_service = STTService()


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Backward-compatible helper that transcribes raw audio bytes."""
    import base64

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    res = stt_service.transcribe_b64(b64)
    return res.text
