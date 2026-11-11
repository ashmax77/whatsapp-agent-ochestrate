import asyncio
import base64
import io
import math
import struct
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.llm.client import LLMResponse
from app.main import handle_message
from app.schemas import IncomingMessage
from app.state.session import get_session_store
from app.voice.audio import (
    AudioLimitError,
    convert_to_wav_16k,
    ephemeral_wav_file,
    validate_and_decode_audio,
)
from app.voice.stt import TranscriptionResult, stt_service
from eval.runners.voice_eval import run_voice_eval


def _run_async(coro):
    """Drives a pure in-memory coroutine to completion without requiring OS loopback sockets."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value


def _make_wav_b64(duration_s: float = 0.5, sample_rate: int = 16000) -> str:
    buf = io.BytesIO()
    n_samples = int(duration_s * sample_rate)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            val = int(3000 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return base64.b64encode(buf.getvalue()).decode("ascii")


class TestPhase6Voice(unittest.TestCase):
    def setUp(self):
        stt_service.set_stub_handler(None)

    def tearDown(self):
        stt_service.set_stub_handler(None)

    def test_audio_validation_and_limits(self):
        # 1. Valid short WAV
        valid_b64 = _make_wav_b64(duration_s=0.5)
        raw = validate_and_decode_audio(valid_b64, audio_seconds=0.5)
        self.assertGreater(len(raw), 100)

        # 2. Duration > 60s rejected
        with self.assertRaises(AudioLimitError) as ctx_dur:
            validate_and_decode_audio(valid_b64, audio_seconds=65.0)
        self.assertEqual(ctx_dur.exception.code, "duration_exceeded")

        # 3. Size > 2 MB rejected
        oversized_b64 = base64.b64encode(b"x" * (settings.MAX_AUDIO_BYTES + 1024)).decode("ascii")
        with self.assertRaises(AudioLimitError) as ctx_size:
            validate_and_decode_audio(oversized_b64, audio_seconds=5.0)
        self.assertEqual(ctx_size.exception.code, "size_exceeded")

        # 4. Empty audio rejected
        with self.assertRaises(AudioLimitError) as ctx_empty:
            validate_and_decode_audio("", audio_seconds=1.0)
        self.assertEqual(ctx_empty.exception.code, "empty_audio")

    def test_ephemeral_wav_file_deletes_immediately(self):
        valid_b64 = _make_wav_b64(duration_s=0.4)
        captured_path: Path | None = None

        with ephemeral_wav_file(valid_b64, mime="audio/wav", declared_seconds=0.4) as (
            wav_path,
            duration_s,
        ):
            captured_path = wav_path
            self.assertTrue(wav_path.exists())
            self.assertGreater(duration_s, 0.0)

        self.assertIsNotNone(captured_path)
        self.assertFalse(captured_path.exists(), "Raw/converted audio must be deleted immediately")

        # Also verify deletion when an exception occurs inside the block
        err_path: Path | None = None
        try:
            with ephemeral_wav_file(valid_b64, mime="audio/wav", declared_seconds=0.4) as (
                wav_path,
                _,
            ):
                err_path = wav_path
                self.assertTrue(err_path.exists())
                raise RuntimeError("Simulated STT crash")
        except RuntimeError:
            pass
        self.assertIsNotNone(err_path)
        self.assertFalse(err_path.exists(), "Audio file must be deleted even on STT failure")

    def test_voice_order_confirmation_and_equivalence_with_text(self):
        async def _run():
            store = get_session_store()
            text_user = "test_voice_eq_text"
            voice_user = "test_voice_eq_audio"
            await store.delete(text_user)
            await store.delete(voice_user)

            # Scripted LLM tool call for "2 large Supreme please"
            call_counter = {"n": 0}

            def fake_complete(system, messages, model=None, tools=None, **kwargs):
                last_msg = messages[-1]
                if last_msg.get("role") == "tool":
                    return LLMResponse(
                        text="Added 2 large Supreme pizzas (LKR 7,600) to your cart. Anything else?",
                        tool_calls=[],
                        model="fake",
                    )
                call_counter["n"] += 1
                return LLMResponse(
                    text="",
                    tool_calls=[
                        {
                            "id": f"call_{call_counter['n']}",
                            "function": {
                                "name": "cart.add_item",
                                "arguments": '{"item_id": "pz_supreme", "size": "large", "qty": 2}',
                            },
                        }
                    ],
                    model="fake",
                )

            with patch("app.agents.orchestrator.llm_client.complete", side_effect=fake_complete):
                # A. Equivalent text flow
                text_reply = await handle_message(
                    IncomingMessage(
                        user_id=text_user,
                        type="text",
                        content="2 large Supreme please",
                        message_id="m_txt_1",
                    )
                )
                text_session = await store.get(text_user)
                self.assertEqual(len(text_session.cart), 1)
                self.assertEqual(text_session.cart[0].item_id, "pz_supreme")
                self.assertEqual(text_session.cart[0].size, "large")
                self.assertEqual(text_session.cart[0].qty, 2)

                # B. Voice flow: stub STT returns "2 large Supreme please"
                stt_service.set_stub_handler(
                    lambda wav_path, dur: TranscriptionResult(
                        text="2 large Supreme please",
                        language="en",
                        confidence=0.91,
                        duration_s=dur,
                        provider="stub",
                    )
                )

                voice_b64 = _make_wav_b64(duration_s=1.0)
                voice_reply_1 = await handle_message(
                    IncomingMessage(
                        user_id=voice_user,
                        type="audio",
                        audio_b64=voice_b64,
                        audio_mime="audio/ogg; codecs=opus",
                        audio_seconds=1.0,
                        message_id="m_aud_1",
                    )
                )

                # First turn must trigger Transcript Confirmation Rule and NOT mutate cart yet
                self.assertIn('I heard: "2 large Supreme please"', voice_reply_1.reply_text)
                voice_session = await store.get(voice_user)
                self.assertEqual(len(voice_session.cart), 0)
                self.assertEqual(
                    voice_session.pending_voice_transcript, "2 large Supreme please"
                )

                # Customer confirms with "yes" -> executes the held transcript and matches text cart!
                voice_reply_2 = await handle_message(
                    IncomingMessage(
                        user_id=voice_user,
                        type="text",
                        content="yes",
                        message_id="m_aud_2",
                    )
                )
                voice_session_after = await store.get(voice_user)
                self.assertIsNone(voice_session_after.pending_voice_transcript)
                self.assertEqual(len(voice_session_after.cart), len(text_session.cart))
                self.assertEqual(
                    voice_session_after.cart[0].item_id, text_session.cart[0].item_id
                )
                self.assertEqual(voice_session_after.cart[0].size, text_session.cart[0].size)
                self.assertEqual(voice_session_after.cart[0].qty, text_session.cart[0].qty)
                self.assertEqual(voice_reply_2.reply_text, text_reply.reply_text)

        _run_async(_run())

    def test_low_confidence_voice_triggers_confirmation_and_can_cancel(self):
        async def _run():
            store = get_session_store()
            user_id = "test_voice_low_conf"
            await store.delete(user_id)

            stt_service.set_stub_handler(
                lambda wav_path, dur: TranscriptionResult(
                    text="What time do you close",
                    language="en",
                    confidence=0.52,  # Below 0.75 threshold
                    duration_s=dur,
                    provider="stub",
                )
            )

            reply = await handle_message(
                IncomingMessage(
                    user_id=user_id,
                    type="audio",
                    audio_b64=_make_wav_b64(0.5),
                    audio_mime="audio/ogg",
                    audio_seconds=0.5,
                    message_id="m_low_1",
                )
            )
            self.assertIn('I heard: "What time do you close"', reply.reply_text)

            # Cancel with "no"
            cancel_reply = await handle_message(
                IncomingMessage(
                    user_id=user_id,
                    type="text",
                    content="no",
                    message_id="m_low_2",
                )
            )
            self.assertIn("cancelled that voice note", cancel_reply.reply_text)
            sess = await store.get(user_id)
            self.assertIsNone(sess.pending_voice_transcript)

        _run_async(_run())

    def test_oversized_audio_rejected_gracefully_at_endpoint(self):
        async def _run():
            reply = await handle_message(
                IncomingMessage(
                    user_id="test_voice_too_long",
                    type="audio",
                    audio_b64=_make_wav_b64(0.3),
                    audio_mime="audio/ogg",
                    audio_seconds=75.0,
                    message_id="m_long_1",
                )
            )
            self.assertIn("too long", reply.reply_text.lower())

        _run_async(_run())

    def test_optional_tts_behavior_and_language_fallback(self):
        async def _run():
            store = get_session_store()
            user_id = "test_voice_tts"
            await store.delete(user_id)

            stt_service.set_stub_handler(
                lambda wav_path, dur: TranscriptionResult(
                    text="1 medium Margherita",
                    language="en",
                    confidence=0.90,
                    duration_s=dur,
                    provider="stub",
                )
            )

            with patch.object(settings, "TTS_ENABLED", True), patch.object(
                settings, "TTS_PROVIDER", "stub"
            ):
                # 1. English voice note gets both reply_text and reply_audio_b64
                reply_en = await handle_message(
                    IncomingMessage(
                        user_id=user_id,
                        type="audio",
                        audio_b64=_make_wav_b64(0.4),
                        audio_mime="audio/ogg",
                        audio_seconds=0.4,
                        message_id="m_tts_1",
                    )
                )
                self.assertIsNotNone(reply_en.reply_text)
                self.assertIsNotNone(reply_en.reply_audio_b64)
                self.assertEqual(reply_en.reply_audio_mime, "audio/ogg; codecs=opus")

                # 2. Sinhala voice note falls back to text-only (no TTS audio)
                stt_service.set_stub_handler(
                    lambda wav_path, dur: TranscriptionResult(
                        text="මට පීසා 1ක් ඕනේ",
                        language="si",
                        confidence=0.68,
                        duration_s=dur,
                        provider="stub",
                    )
                )
                reply_si = await handle_message(
                    IncomingMessage(
                        user_id=user_id,
                        type="audio",
                        audio_b64=_make_wav_b64(0.4),
                        audio_mime="audio/ogg",
                        audio_seconds=0.4,
                        message_id="m_tts_2",
                    )
                )
                self.assertIsNotNone(reply_si.reply_text)
                self.assertIsNone(reply_si.reply_audio_b64)

        _run_async(_run())

    def test_voice_eval_suite_passes_gates(self):
        report = run_voice_eval()
        self.assertGreaterEqual(report["total_cases"], 30)
        self.assertEqual(report["low_confidence_confirmation_recall"], 1.0)
        self.assertEqual(report["overall_confirmation_rule_accuracy"], 1.0)
        for lang in ("en", "mixed", "si", "ta"):
            self.assertIn(lang, report["by_language"])
            self.assertEqual(report["by_language"][lang]["slot_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()

