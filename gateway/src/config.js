import 'dotenv/config'

export const config = {
  brainUrl: process.env.BRAIN_URL ?? 'http://127.0.0.1:8000',
  brainTimeoutMs: Number(process.env.BRAIN_TIMEOUT_MS ?? 30000),
  authDir: 'auth_state',
  callRejectMessage:
    "Hi! 🍕 I can't take calls, but you can text me or send a voice note and I'll take your order.",
}