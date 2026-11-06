import { evaluateBatch, type ScanRequest } from './engine'
self.onmessage = (event: MessageEvent<ScanRequest>) => {
  try {
    self.postMessage(evaluateBatch(event.data))
  } catch {
    self.postMessage({
      revision: event.data.revision,
      error: 'The screen could not be evaluated. Check the conditions.',
    })
  }
}
