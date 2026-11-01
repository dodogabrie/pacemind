/**
 * Parse SSE events from a text buffer.
 * Returns { events: [{event, data}], remaining: string }
 * where remaining is the incomplete trailing text.
 */
export function parseSSEEvents(buffer) {
  const events = []
  const blocks = buffer.split('\n\n')
  // Last element may be incomplete
  const remaining = blocks.pop()

  for (const block of blocks) {
    if (!block.trim()) continue
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) {
        event = line.slice(7)
      } else if (line.startsWith('data: ')) {
        data = line.slice(6)
      }
    }
    if (data) {
      try {
        events.push({ event, data: JSON.parse(data) })
      } catch {
        events.push({ event, data })
      }
    }
  }

  return { events, remaining: remaining || '' }
}
