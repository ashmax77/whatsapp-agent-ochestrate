import { config } from './config.js'

export async function askBrain(payload) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), config.brainTimeoutMs)
  try {
    const res = await fetch(`${config.brainUrl}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(`Brain returned ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}