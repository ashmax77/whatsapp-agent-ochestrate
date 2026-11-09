import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import qrcode from 'qrcode-terminal'
import pino from 'pino'
import { config } from './config.js'
import { askBrain } from './brainClient.js'

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

function messageType(msg) {
  const m = msg.message ?? {}
  if (m.conversation || m.extendedTextMessage) return 'text'
  if (m.audioMessage) return 'audio'
  if (m.locationMessage) return 'location'
  if (m.imageMessage) return 'image'
  return 'other'
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
      logger.info({ jid, msgType, text }, 'Incoming message')

      try {
        const reply = await askBrain({
          user_id: jid.split('@')[0],
          type: msgType,
          content: text,
          message_id: msg.key.id,
          push_name: msg.pushName ?? null,
        })
        if (reply?.reply_text) {
          await sock.sendMessage(jid, { text: reply.reply_text })
        }
      } catch (err) {
        logger.error(err, 'Brain call failed')
        await sock.sendMessage(jid, {
          text: 'Sorry, something went wrong on our side. Please try again in a moment 🙏',
        })
      }
    }
  })
}

start()