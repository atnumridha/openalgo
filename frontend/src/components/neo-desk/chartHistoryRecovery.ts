export function canAutoRetryHistory(error: unknown): boolean {
  const value = error as {code?: string; name?: string; response?: {status?: number}; message?: string}
  if (!value || value.code === 'ERR_CANCELED' || value.name === 'AbortError') return false
  const status = value.response?.status
  if (status != null && status >= 400 && status < 500 && status !== 408 && status !== 429) return false
  return ['ECONNABORTED','ETIMEDOUT','ERR_NETWORK'].includes(value.code ?? '')
    || status === 408 || status === 429 || (status != null && status >= 500)
    || /broker.*delayed|temporarily|timed? ?out|timeout|server disconnected|connection.*(lost|reset)/i.test(value.message ?? '')
}

/** Retry gently during an outage, and keep trying until a real response succeeds. */
export const chartHistoryRetryDelay = (attempt: number) => 15000 * 2 ** Math.min(2, Math.max(0, attempt))
