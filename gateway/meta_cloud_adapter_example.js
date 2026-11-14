/**
 * Reference Meta WhatsApp Cloud API Gateway Adapter.
 * Drop-in alternative to Baileys socket in gateway/src/index.js.
 * 
 * Maps Meta Cloud API Webhook events -> Python Brain POST /message
 * Maps Python Brain POST /send -> Meta Graph API POST /messages
 */

import express from 'express';
import crypto from 'node:crypto';

const app = express();
app.use(express.json({
  verify: (req, res, buf) => {
    req.rawBody = buf;
  }
}));

const PORT = process.env.PORT || 3000;
const BRAIN_URL = process.env.BRAIN_URL || 'http://127.0.0.1:8000';
const VERIFY_TOKEN = process.env.WHATSAPP_VERIFY_TOKEN || 'pizza_verify_token_123';
const APP_SECRET = process.env.WHATSAPP_APP_SECRET || '';
const ACCESS_TOKEN = process.env.WHATSAPP_ACCESS_TOKEN || '';
const PHONE_NUMBER_ID = process.env.WHATSAPP_PHONE_NUMBER_ID || '';
const INTERNAL_SECRET = process.env.INTERNAL_SECRET || 'change-me';

// 1. Webhook Verification Handshake (GET /webhook)
app.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];

  if (mode === 'subscribe' && token === VERIFY_TOKEN) {
    console.log('[Webhook] Verified challenge from Meta');
    return res.status(200).send(challenge);
  }
  return res.sendStatus(403);
});

// Helper: HMAC SHA-256 signature verification
function verifySignature(req) {
  if (!APP_SECRET) return true; // Bypass in local testing if no secret configured
  const sigHeader = req.headers['x-hub-signature-256'];
  if (!sigHeader || !sigHeader.startsWith('sha256=')) return false;

  const signature = sigHeader.substring(7);
  const expected = crypto.createHmac('sha256', APP_SECRET).update(req.rawBody).digest('hex');
  return crypto.timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'));
}

// 2. Incoming Messages Webhook (POST /webhook)
app.post('/webhook', async (req, res) => {
  if (!verifySignature(req)) {
    console.warn('[Webhook] Invalid HMAC signature detected');
    return res.sendStatus(401);
  }

  // Acknowledge receipt to Meta immediately (< 3s)
  res.sendStatus(200);

  const entry = req.body.entry?.[0]?.changes?.[0]?.value;
  const message = entry?.messages?.[0];
  if (!message) return;

  const contact = entry?.contacts?.[0];
  const from = message.from; // Phone number e.g. "94771234567"

  let normalized = {
    user_id: from,
    message_id: message.id,
    push_name: contact?.profile?.name || 'Customer',
    timestamp: parseInt(message.timestamp, 10),
    type: message.type,
    content: null,
    location: null,
    audio_b64: null,
    audio_mime: null,
  };

  try {
    if (message.type === 'text') {
      normalized.content = message.text.body;
    } else if (message.type === 'location') {
      normalized.type = 'location';
      normalized.location = {
        lat: message.location.latitude,
        lng: message.location.longitude,
        name: message.location.name,
        address: message.location.address,
      };
    } else if (message.type === 'audio') {
      normalized.type = 'audio';
      // Download audio via Meta Graph API
      const mediaMetaRes = await fetch(`https://graph.facebook.com/v21.0/${message.audio.id}`, {
        headers: { Authorization: `Bearer ${ACCESS_TOKEN}` }
      });
      const mediaMetaData = await mediaMetaRes.json();
      if (mediaMetaData.url) {
        const audioBufferRes = await fetch(mediaMetaData.url, {
          headers: { Authorization: `Bearer ${ACCESS_TOKEN}` }
        });
        const arrayBuf = await audioBufferRes.arrayBuffer();
        normalized.audio_b64 = Buffer.from(arrayBuf).toString('base64');
        normalized.audio_mime = message.audio.mime_type;
      }
    } else {
      normalized.type = 'other';
    }

    // Forward to Python Brain
    const brainRes = await fetch(`${BRAIN_URL}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(normalized),
    });

    if (brainRes.ok) {
      const reply = await brainRes.json();
      if (reply.reply_text) {
        await sendGraphTextMessage(from, reply.reply_text);
      }
    }
  } catch (err) {
    console.error('[Gateway] Failed to process message from ' + from, err);
  }
});

// Helper: Outbound Graph API message
async function sendGraphTextMessage(to, text) {
  const url = `https://graph.facebook.com/v21.0/${PHONE_NUMBER_ID}/messages`;
  await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${ACCESS_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      messaging_product: 'whatsapp',
      recipient_type: 'individual',
      to,
      type: 'text',
      text: { body: text },
    }),
  });
}

// 3. Internal Push Endpoint for Brain Staff Alerts (POST /send)
app.post('/send', async (req, res) => {
  const secret = req.headers['x-internal-secret'];
  if (!INTERNAL_SECRET || secret !== INTERNAL_SECRET) {
    return res.status(401).json({ ok: false, error: 'UNAUTHORIZED' });
  }

  const { jid, text } = req.body;
  if (!jid || !text) {
    return res.status(400).json({ ok: false, error: 'MISSING_FIELDS' });
  }

  try {
    const to = jid.replace('@s.whatsapp.net', '');
    await sendGraphTextMessage(to, text);
    return res.json({ ok: true });
  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Meta Cloud API Gateway reference listening on port ${PORT}`);
});
