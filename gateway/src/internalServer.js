import http from 'node:http'
import { config } from './config.js'
import { sendTextToJid } from './sender.js'

/**
 * (Phase 7) Minimal internal HTTP server on INTERNAL_PORT (default 3001)
 * allowing the Python Brain's notifier service to push outbound WhatsApp messages
 * to branch staff, area managers, and customers.
 * Requires header `X-Internal-Secret`.
 */

let currentSock = null
let serverInstance = null

export function setActiveSocket(sock) {
  currentSock = sock
}

export function startInternalServer(sock, logger) {
  currentSock = sock
  if (serverInstance) return serverInstance

  serverInstance = http.createServer(async (req, res) => {
    const sendJson = (statusCode, payload) => {
      res.writeHead(statusCode, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(payload))
    }

    if (req.method === 'GET' && req.url === '/health') {
      return sendJson(200, {
        status: 'ok',
        whatsappConnected: Boolean(currentSock),
      })
    }

    if (req.method === 'POST' && req.url === '/send') {
      const secret = req.headers['x-internal-secret']
      if (!config.internalSecret || secret !== config.internalSecret) {
        return sendJson(401, { ok: false, error: 'UNAUTHORIZED' })
      }

      let body = ''
      for await (const chunk of req) {
        body += chunk
      }

      try {
        const parsed = JSON.parse(body || '{}')
        const { jid, text } = parsed
        if (!jid || !text) {
          return sendJson(400, { ok: false, error: 'MISSING_JID_OR_TEXT' })
        }

        const result = await sendTextToJid(currentSock, jid, text)
        return sendJson(200, result)
      } catch (err) {
        logger?.error(err, 'Internal /send failed')
        return sendJson(500, { ok: false, error: err.message || 'SEND_FAILED' })
      }
    }

    return sendJson(404, { ok: false, error: 'NOT_FOUND' })
  })

  serverInstance.listen(config.internalPort, '127.0.0.1', () => {
    logger?.info(
      { port: config.internalPort },
      'Gateway internal notification server listening'
    )
  })

  return serverInstance
}

