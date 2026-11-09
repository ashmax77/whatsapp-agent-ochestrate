/**
 * (Phase 6) Media handling utilities: voice note download/send.
 */

/**
 * Downloads incoming audio / voice note media from WhatsApp message.
 * @param {Object} message - Baileys message object
 * @returns {Promise<Buffer>}
 */
export async function downloadVoiceNote(message) {
  // TODO: Implement Baileys downloadMediaMessage in Phase 6
  console.log("[Media] Voice note download placeholder");
  return null;
}

/**
 * Sends a generated voice note / audio back to customer.
 * @param {Object} sock - Baileys socket
 * @param {string} jid - Recipient JID
 * @param {Buffer|string} audio - Audio buffer or URL/path
 */
export async function sendVoiceNote(sock, jid, audio) {
  // TODO: Implement audio message sending in Phase 6
  console.log(`[Media] Voice note send placeholder to ${jid}`);
}

