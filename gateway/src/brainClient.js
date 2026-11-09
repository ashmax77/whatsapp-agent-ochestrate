import { config } from './config.js'

export async function askBrain(payload) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), config.brainTimeoutMs)
  const url = `${config.brainUrl}/message`
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`Brain ${res.status} at ${url}: ${body}`)
    }
    return await res.json()
  } catch (err) {
    console.error('askBrain failed:', url, err.message, err.cause?.code ?? '')
    throw err
  } finally {
    clearTimeout(timer)
  }
}
