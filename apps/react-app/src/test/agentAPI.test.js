import { beforeEach, describe, expect, it, vi } from 'vitest'
import { askAgentStream, extractMessageItemText } from '../api/agentAPI.js'

function mockSseFetch(events) {
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const event of events) {
        const payload = typeof event === 'string' ? event : JSON.stringify(event)
        controller.enqueue(encoder.encode(`data: ${payload}\n\n`))
      }
      controller.close()
    },
  })

  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    body,
  })
}

describe('extractMessageItemText', () => {
  it('extracts output text from ResponsesAgent message content', () => {
    expect(extractMessageItemText({
      type: 'message',
      content: [
        { type: 'output_text', text: 'First' },
        { type: 'output_text', text: 'Second' },
      ],
    })).toBe('First\nSecond')
  })

  it('handles missing content safely', () => {
    expect(extractMessageItemText({ type: 'message' })).toBe('')
    expect(extractMessageItemText(null)).toBe('')
  })
})

describe('askAgentStream', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('emits official AgentServer text deltas', async () => {
    mockSseFetch([
      { type: 'response.output_text.delta', item_id: 'msg-1', delta: 'Hel' },
      { type: 'response.output_text.delta', item_id: 'msg-1', delta: 'lo' },
      '[DONE]',
    ])

    const chunks = []
    await askAgentStream({ input: [], custom_inputs: { thread_id: 't1' } }, {
      onText: chunk => chunks.push(chunk),
    })

    expect(chunks.join('')).toBe('Hello')
  })

  it('falls back to completed message items when no deltas arrive', async () => {
    mockSseFetch([
      {
        type: 'response.output_item.done',
        item: {
          id: 'msg-1',
          type: 'message',
          content: [{ type: 'output_text', text: 'Final answer' }],
        },
      },
      '[DONE]',
    ])

    const chunks = []
    await askAgentStream({ input: [], custom_inputs: { thread_id: 't1' } }, {
      onText: chunk => chunks.push(chunk),
    })

    expect(chunks).toEqual(['Final answer'])
  })

  it('emits completed content parts before final output items', async () => {
    mockSseFetch([
      {
        type: 'response.content_part.done',
        item_id: 'msg-1',
        part: { type: 'output_text', text: 'Final answer' },
      },
      {
        type: 'response.output_item.done',
        item: {
          id: 'msg-1',
          type: 'message',
          content: [{ type: 'output_text', text: 'Final answer' }],
        },
      },
      '[DONE]',
    ])

    const chunks = []
    await askAgentStream({ input: [], custom_inputs: { thread_id: 't1' } }, {
      onText: chunk => chunks.push(chunk),
    })

    expect(chunks).toEqual(['Final answer'])
  })

  it('does not duplicate final message content after streaming deltas', async () => {
    mockSseFetch([
      { type: 'response.output_text.delta', item_id: 'msg-1', delta: 'Final answer' },
      {
        type: 'response.output_item.done',
        item: {
          id: 'msg-1',
          type: 'message',
          content: [{ type: 'output_text', text: 'Final answer' }],
        },
      },
      '[DONE]',
    ])

    const chunks = []
    await askAgentStream({ input: [], custom_inputs: { thread_id: 't1' } }, {
      onText: chunk => chunks.push(chunk),
    })

    expect(chunks).toEqual(['Final answer'])
  })

  it('surfaces tool calls and tool results from official events', async () => {
    mockSseFetch([
      {
        type: 'response.output_item.added',
        item: { id: 'fc-1', type: 'function_call', call_id: 'call-1', name: 'search', arguments: '' },
      },
      {
        type: 'response.output_item.done',
        item: { id: 'fc-1', type: 'function_call', call_id: 'call-1', name: 'search', arguments: '{"q":"EGFR"}' },
      },
      {
        type: 'response.output_item.done',
        item: { type: 'function_call_output', call_id: 'call-1', output: '{"ok":true}' },
      },
      '[DONE]',
    ])

    const starts = []
    const done = []
    const results = []
    await askAgentStream({ input: [], custom_inputs: { thread_id: 't1' } }, {
      onToolCallStart: data => starts.push(data),
      onToolCallDone: data => done.push(data),
      onToolCallResult: data => results.push(data),
    })

    expect(starts[0]).toMatchObject({ call_id: 'call-1', name: 'search' })
    expect(done[0]).toMatchObject({ call_id: 'call-1', arguments: '{"q":"EGFR"}' })
    expect(results[0]).toMatchObject({ call_id: 'call-1', output: '{"ok":true}' })
  })
})
