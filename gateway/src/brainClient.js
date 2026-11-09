import { config } from "./config.js";

/**
 * Client for interacting with the Python Brain backend.
 */
export class BrainClient {
  constructor(baseUrl = config.brainUrl) {
    this.baseUrl = baseUrl;
  }

  /**
   * Forward incoming WhatsApp message to the Brain agent.
   * @param {Object} payload - { senderId, message, messageId, timestamp }
   * @returns {Promise<Object>}
   */
  async sendMessage(payload) {
    try {
      const response = await fetch(`${this.baseUrl}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Brain API responded with status ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error("[BrainClient] Error sending message to Brain:", error);
      throw error;
    }
  }
}

export const brainClient = new BrainClient();

