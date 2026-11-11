import { downloadMediaMessage } from '@whiskeysockets/baileys'

/**
 * (Phase 6) Media handling utilities: voice note download/send.
 */

/**
 * Downloads incoming audio / voice note media from a WhatsApp message.
 * @param {Object} msg - Baileys message object
 * @returns {Promise<{b64: string, mime: string, seconds: number, byteLength: number}>}
 */
export async function downloadAudio(msg) {
  const audioMsg = msg?.message?.audioMessage
  if (!audioMsg) {
    throw new Error('No audioMessage payload present on message')
  }

  const buffer = await downloadMediaMessage(msg, 'buffer', {})
  const b64 = Buffer.from(buffer).toString('base64')
  const mime = audioMsg.mimetype || 'audio/ogg; codecs=opus'
  const seconds = Number(audioMsg.seconds || 0)

  return {
    b64,
    mime,
    seconds,
    byteLength: buffer.length,
  }
}

// Keep downloadVoiceNote as an alias for backward compatibility
export const downloadVoiceNote = downloadAudio

/**
 * Sends a generated voice note (OGG/Opus PTT) back to customer.
 * @param {Object} sock - Baileys socket
 * @param {string} jid - Recipient JID
 * @param {Buffer|string} audioB64OrBuffer - Base64 string or Buffer of audio
 * @param {string} [mime='audio/ogg; codecs=opus'] - Audio MIME type
 */
export async function sendVoiceNote(sock, jid, audioB64OrBuffer, mime = 'audio/ogg; codecs=opus') {
  if (!audioB64OrBuffer) return
  const buffer = Buffer.isBuffer(audioB64OrBuffer)
    ? audioB64OrBuffer
    : Buffer.from(audioB64OrBuffer, 'base64')

  await sock.sendMessage(jid, {
    audio: buffer,
    mimetype: mime,
    ptt: true,
  })
}
