import makeWASocket, { DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import { config } from "./config.js";
import { brainClient } from "./brainClient.js";

async function connectToWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);

  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: true,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("[Gateway] Scan the QR code above to connect WhatsApp.");
    }

    if (connection === "close") {
      const shouldReconnect =
        (lastDisconnect?.error instanceof Boom)?.output?.statusCode !==
        DisconnectReason.loggedOut;
      console.log(
        "[Gateway] Connection closed. Reconnecting:",
        shouldReconnect
      );
      if (shouldReconnect) {
        connectToWhatsApp();
      }
    } else if (connection === "open") {
      console.log("[Gateway] WhatsApp connection established successfully.");
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue;

      const senderId = msg.key.remoteJid;
      const messageText =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        "";

      if (!messageText) continue;

      console.log(`[Gateway] Received from ${senderId}: ${messageText}`);

      try {
        const brainResponse = await brainClient.sendMessage({
          senderId,
          message: messageText,
          messageId: msg.key.id,
          timestamp: msg.messageTimestamp,
        });

        if (brainResponse && brainResponse.reply) {
          await sock.sendMessage(senderId, { text: brainResponse.reply });
        }
      } catch (err) {
        console.error("[Gateway] Failed to handle message:", err.message);
      }
    }
  });
}

connectToWhatsApp().catch((err) =>
  console.error("[Gateway] Fatal startup error:", err)
);

