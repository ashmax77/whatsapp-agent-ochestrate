/**
 * (Phase 7) Outbound WhatsApp message sender helper for staff notifications and order updates.
 */

export function normalizeJid(jidOrPhone) {
  if (!jidOrPhone) return null
  const clean = String(jidOrPhone).trim()
  if (!clean) return null
  if (clean.includes('@')) return clean
  const digits = clean.replace(/[^0-9]/g, '')
  return digits ? `${digits}@s.whatsapp.net` : null
}

/**
 * Sends a text message to a customer or staff JID/phone number.
 * @param {Object} sock - Active Baileys socket
 * @param {string} jidOrPhone - Recipient JID or phone number
 * @param {string} text - Message text
 */
export async function sendTextToJid(sock, jidOrPhone, text) {
  const jid = normalizeJid(jidOrPhone)
  if (!jid || !text) {
    throw new Error('Both jid and text are required to send a WhatsApp message')
  }
  if (!sock) {
    throw new Error('WhatsApp socket is not connected')
  }
  await sock.sendMessage(jid, { text: String(text) })
  return { ok: true, jid }
}

