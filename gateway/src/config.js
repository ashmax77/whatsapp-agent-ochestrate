import 'dotenv/config'

export const config = {
  brainUrl: process.env.BRAIN_URL ?? 'http://127.0.0.1:8000',
  brainTimeoutMs: Number(process.env.BRAIN_TIMEOUT_MS ?? 30000),
  authDir: 'auth_state',
  maxAudioSeconds: Number(process.env.MAX_AUDIO_SECONDS ?? 60),
  maxAudioBytes: Number(process.env.MAX_AUDIO_BYTES ?? 2 * 1024 * 1024),
  maxReplyChars: Number(process.env.MAX_REPLY_CHARS ?? 1000),
  callRejectMessage:
    "Hi! 🍕 I can't take calls, but you can text me or send a voice note and I'll take your order.",
}