import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import qrcode from 'qrcode-terminal'
import pino from 'pino'
import { config } from './config.js'
import { askBrain } from './brainClient.js'
import { downloadAudio, sendVoiceNote } from './media.js'

const logger = pino({ level: 'info' })

function extractText(msg) {
  const m = msg.message
  if (!m) return null
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    null
  )
}

function extractLocation(msg) {
  const loc = msg.message?.locationMessage
  if (!loc) return null
  return {
    lat: Number(loc.degreesLatitude),
    lng: Number(loc.degreesLongitude),
    name: loc.name || null,
    address: loc.address || null,
  }
}

function messageType(msg) {
  const m = msg.message ?? {}
  if (m.conversation || m.extendedTextMessage) return 'text'
  if (m.audioMessage) return 'audio'
  if (m.locationMessage) return 'location'
  if (m.imageMessage) return 'image'
  return 'other'
}

function splitLongReply(text, maxChars = config.maxReplyChars) {
  if (!text || text.length <= maxChars) return [text]
  const chunks = []
  let remaining = text
  while (remaining.length > maxChars) {
    let splitIdx = remaining.lastIndexOf('\n', maxChars)
    if (splitIdx <= 0) splitIdx = remaining.lastIndexOf(' ', maxChars)
    if (splitIdx <= 0) splitIdx = maxChars
    chunks.push(remaining.slice(0, splitIdx).trim())
    remaining = remaining.slice(splitIdx).trim()
  }
  if (remaining) chunks.push(remaining)
  return chunks
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir)
  const { version } = await fetchLatestBaileysVersion()

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log('Scan this QR with WhatsApp > Linked devices:')
      qrcode.generate(qr, { small: true })
    }
    if (connection === 'open') logger.info('WhatsApp connected ✅')
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      const loggedOut = code === DisconnectReason.loggedOut
      logger.warn({ code }, 'Connection closed')
      if (!loggedOut) start() // reconnect
      else logger.error('Logged out. Delete auth_state/ and scan the QR again.')
    }
  })

  // Incoming calls: reject and redirect to chat
  sock.ev.on('call', async (calls) => {
    for (const call of calls) {
      if (call.status === 'offer') {
        try {
          await sock.rejectCall(call.id, call.from)
          await sock.sendMessage(call.from, { text: config.callRejectMessage })
        } catch (err) {
          logger.error(err, 'Failed to reject call')
        }
      }
    }
  })

  // Incoming messages
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return // ignore history sync

    for (const msg of messages) {
      const jid = msg.key.remoteJid
      if (!jid || msg.key.fromMe) continue
      if (jid === 'status@broadcast' || jid.endsWith('@g.us')) continue // no status/groups

      const msgType = messageType(msg)
      const text = extractText(msg)
      const location = extractLocation(msg)
      logger.info({ jid, msgType, text }, 'Incoming message')

      try {
        await sock.sendPresenceUpdate('composing', jid)

        const payload = {
          user_id: jid.split('@')[0],
          type: msgType,
          content: text,
          message_id: msg.key.id,
          push_name: msg.pushName ?? null,
          location,
        }

        if (msgType === 'audio') {
          const audioMsg = msg.message?.audioMessage
          const declaredSeconds = Number(audioMsg?.seconds || 0)
          const declaredBytes = Number(audioMsg?.fileLength || 0)

          if (declaredSeconds > config.maxAudioSeconds) {
            await sock.sendMessage(jid, {
              text: `That voice note is a bit too long (${declaredSeconds}s). Please keep voice notes under ${config.maxAudioSeconds} seconds or type your order 🙂`,
            })
            continue
          }

          if (declaredBytes > config.maxAudioBytes) {
            await sock.sendMessage(jid, {
              text: 'That voice note file is too large (max 2 MB). Please send a shorter voice note or type your message 🙂',
            })
            continue
          }

          const audioData = await downloadAudio(msg)
          if (audioData.byteLength > config.maxAudioBytes) {
            await sock.sendMessage(jid, {
              text: 'That voice note file is too large (max 2 MB). Please send a shorter voice note or type your message 🙂',
            })
            continue
          }

          payload.audio_b64 = audioData.b64
          payload.audio_mime = audioData.mime
          payload.audio_seconds = audioData.seconds
        }

        const reply = await askBrain(payload)

        if (reply?.reply_text) {
          for (const part of splitLongReply(reply.reply_text)) {
            await sock.sendMessage(jid, { text: part })
          }
        }

        if (reply?.reply_audio_b64) {
          await sendVoiceNote(
            sock,
            jid,
            reply.reply_audio_b64,
            reply.reply_audio_mime || 'audio/ogg; codecs=opus'
          )
        }
      } catch (err) {
        logger.error(err, 'Brain call failed')
        await sock.sendMessage(jid, {
          text: 'Sorry, something went wrong on our side. Please try again in a moment 🙏',
        })
      } finally {
        try {
          await sock.sendPresenceUpdate('paused', jid)
        } catch {
          // ignore presence error
        }
      }
    }
  })
}

start()
