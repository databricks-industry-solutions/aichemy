// API service for Databricks/MLflow agent calls

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/**
 * Call the agent endpoint via the backend proxy
 * @param {Object} inputDict - Input dictionary with messages and custom inputs
 * @returns {Promise<Object>} Response JSON from the agent
 */
export async function askAgent(inputDict) {
  const url = `${API_BASE_URL}/api/agent`
  
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(inputDict),
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`Request failed with status ${response.status}: ${errorText}`)
    }

    return await response.json()
  } catch (error) {
    console.error('Agent API error:', error)
    throw error
  }
}

/**
 * Call the streaming agent endpoint. Yields SSE events as they arrive.
 *
 * Handles both legacy (batch tool_calls/genie after stream) and new inline
 * tool call events (tool_call_start, tool_call_args_delta, tool_call_done,
 * tool_call_result) for immediate agent activity feedback.
 *
 * @param {Object} inputDict - Input dictionary with messages and custom inputs
 * @param {Object} callbacks
 * @param {AbortSignal} [callbacks.signal] - Optional abort signal
 * @param {function} callbacks.onText - Called with each text chunk
 * @param {function} [callbacks.onToolCallStart] - Called when a tool call begins: {id, call_id, name, arguments}
 * @param {function} [callbacks.onToolCallDone] - Called when a tool call completes: {id, call_id, name, arguments}
 * @param {function} [callbacks.onToolCallResult] - Called with tool result: {call_id, output}
 * @param {function} [callbacks.onToolCalls] - Legacy: called with batch tool calls array (from trace)
 * @param {function} [callbacks.onGenie] - Called with genie results
 * @param {function} [callbacks.onTraceId] - Called with MLflow trace_id
 * @param {function} [callbacks.onStatus] - Called with status message string
 * @param {function} [callbacks.onError] - Called with error string
 * @param {function} [callbacks.onDone] - Called when stream completes
 */
export async function askAgentStream(inputDict, {
  signal, onText, onToolCallStart, onToolCallDone, onToolCallResult,
  onToolCalls, onGenie, onTraceId, onStatus, onError, onDone,
} = {}) {
  const url = `${API_BASE_URL}/api/agent/stream`
  const streamedTextItemIds = new Set()
  const emittedFinalTexts = new Set()

  onStatus?.('Thinking...')

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inputDict),
    signal,
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Request failed with status ${response.status}: ${errorText}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const dataStr = line.slice(6)
      if (dataStr === '[DONE]') {
        onDone?.()
        return
      }
      try {
        const event = JSON.parse(dataStr)
        switch (event.type) {
          // Official ResponsesAgent stream events from AgentServer.
          case 'response.output_text.delta': {
            const delta = event.delta || ''
            if (delta) {
              if (event.item_id) streamedTextItemIds.add(event.item_id)
              onText?.(delta)
            }
            break
          }
          case 'response.output_item.added': {
            const item = event.item || {}
            if (item.type === 'function_call') {
              onToolCallStart?.({
                id: item.id || '',
                call_id: item.call_id || '',
                name: item.name || '',
                arguments: item.arguments || '',
              })
            }
            break
          }
          case 'response.function_call_arguments.delta':
            break
          case 'response.content_part.done': {
            const text = event.part?.text || ''
            if (text && event.item_id && !streamedTextItemIds.has(event.item_id)) {
              streamedTextItemIds.add(event.item_id)
              onText?.(text)
            }
            break
          }
          case 'response.output_item.done': {
            const item = event.item || {}
            if (item.type === 'function_call') {
              onToolCallDone?.({
                id: item.id || '',
                call_id: item.call_id || '',
                name: item.name || '',
                arguments: item.arguments || '',
              })
            } else if (item.type === 'function_call_output') {
              onToolCallResult?.({
                call_id: item.call_id || '',
                output: item.output || '',
              })
            } else if (item.type === 'message' && !streamedTextItemIds.has(item.id)) {
              const text = extractMessageItemText(item)
              if (text && !emittedFinalTexts.has(text)) {
                emittedFinalTexts.add(text)
                onText?.(text)
              }
            }
            break
          }
          case 'response.completed':
            if (event.response?.metadata?.trace_id) {
              onTraceId?.(event.response.metadata.trace_id)
            }
            break

          // Compatibility with the previous AiChemy custom SSE format.
          case 'text':
            onText?.(event.content)
            break
          case 'status':
            onStatus?.(event.content)
            break
          case 'tool_call_start':
            onToolCallStart?.(event.data)
            break
          case 'tool_call_done':
            onToolCallDone?.(event.data)
            break
          case 'tool_call_result':
            onToolCallResult?.(event.data)
            break
          case 'tool_call_args_delta':
            break
          case 'tool_calls':
            onToolCalls?.(event.data)
            break
          case 'genie':
            onGenie?.(event.data)
            break
          case 'trace_id':
            onTraceId?.(event.trace_id)
            break
          case 'error':
            onError?.(event.content || event.error?.message || JSON.stringify(event.error || event))
            break
          case 'done':
            onDone?.()
            return
        }
      } catch {
        // skip malformed JSON
      }
    }
  }
  onDone?.()
}

export function extractMessageItemText(item) {
  const parts = []
  for (const part of item?.content || []) {
    if (typeof part === 'string') {
      parts.push(part)
    } else if (part && typeof part === 'object') {
      const text = part.text || part.content
      if (text) parts.push(text)
    }
  }
  return parts.join('\n')
}

/**
 * Extract parsed response from backend (text, tool_calls, genie).
 * The backend now returns a `parsed` field with pre-processed data.
 * @param {Object} responseJson - Response JSON from the agent
 * @returns {{text: string, tool_calls: Array, genie: Array}}
 */
export function extractParsedResponse(responseJson) {
  if (responseJson?.parsed) {
    return responseJson.parsed
  }
  // Fallback: extract text content the old way
  const textContents = []
  for (const outputItem of responseJson?.output || []) {
    if (outputItem?.type === 'message') {
      const newText = outputItem?.content?.[0]?.text
      if (newText && !textContents.includes(newText)) {
        textContents.push(newText)
      }
    }
  }
  return {
    text: textContents.join('\n\n') || 'No response. Retry or reset the chat.',
    tool_calls: [],
    genie: [],
  }
}

/**
 * Fetch available tools grouped by agent from the backend.
 * @returns {Promise<Object>} Map of agent name -> [{name, description}]
 */
export async function fetchTools() {
  const response = await fetch(`${API_BASE_URL}/api/tools`)
  if (!response.ok) return {}
  return response.json()
}

/**
 * Fetch discovered skills metadata from the backend.
 * @returns {Promise<Object>} Map of skill name -> {description, path, label, caption}
 */
export async function fetchSkills() {
  const response = await fetch(`${API_BASE_URL}/api/skills`)
  if (!response.ok) return {}
  return response.json()
}

/**
 * Fetch user info from the backend.
 * In Databricks Apps, the backend reads X-Forwarded-* headers.
 * Locally, falls back to defaults (configurable via env vars).
 * @returns {Promise<{user_name: string, user_email: string, user_id: string}>}
 */
export async function fetchUserInfo() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/user`)
    if (response.ok) return response.json()
  } catch {
    // fall through to defaults
  }
  return { user_name: null, user_email: null, user_id: null }
}

/**
 * Fetch the current agent configuration (llm_endpoint, mcp_servers, enabled_mcps).
 * @returns {Promise<{llm_endpoint: string, mcp_servers: string[], enabled_mcps: string[]}>}
 */
export async function fetchAgentConfig() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/config`)
    if (response.ok) return response.json()
  } catch {
    // ignore
  }
  return { llm_endpoint: '', mcp_servers: [], enabled_mcps: [] }
}

/**
 * Trigger an agent rebuild with new model and/or MCP selection.
 * Returns immediately; poll fetchAgentStatus() to know when ready.
 * @param {{llmEndpoint?: string, enabledMcps?: string[]}} options
 * @returns {Promise<{ok: boolean, detail: string}>}
 */
export async function rebuildAgent({ llmEndpoint, enabledMcps } = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/agent/rebuild`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm_endpoint: llmEndpoint, enabled_mcps: enabledMcps }),
    })
    if (response.ok) return response.json()
    return { ok: false, detail: `HTTP ${response.status}` }
  } catch (e) {
    return { ok: false, detail: e.message }
  }
}

/**
 * Fetch DB backend status from the health endpoint.
 * @returns {Promise<{db_backend: string, db_detail: string}>}
 */
export async function fetchDbStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`)
    if (response.ok) {
      const data = await response.json()
      return { db_backend: data.db_backend, db_detail: data.db_detail }
    }
  } catch {
    // ignore
  }
  return { db_backend: 'unknown', db_detail: '' }
}

/**
 * Fetch external MCP server health status (OpenTargets, PubChem, PubMed).
 * @returns {Promise<Object>} Map of server name -> {ok, status_code, status, detail}
 */
export async function fetchMcpStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`)
    if (response.ok) {
      const data = await response.json()
      const status = {}
      for (const srv of data.mcp_servers || []) {
        status[srv.name] = srv
      }
      return status
    }
  } catch {
    // ignore
  }
  return {}
}

// ---------------------------------------------------------------------------
// Agent status + warmup
// ---------------------------------------------------------------------------

/**
 * Check whether the backend agent is ready to serve requests.
 * @returns {Promise<{ready: boolean, building: boolean, error: string|null}>}
 */
export async function fetchAgentStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/agent/status`)
    if (response.ok) return response.json()
  } catch {
    // agent server unreachable
  }
  return { ready: false, building: true, error: null }
}

/**
 * Trigger a warmup query on the agent to pre-warm LLM endpoints, Lakebase, etc.
 * @returns {Promise<{ok: boolean, detail: string}>}
 */
export async function warmupAgent() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/agent/warmup`, { method: 'POST' })
    if (response.ok) return response.json()
    return { ok: false, detail: `HTTP ${response.status}` }
  } catch (e) {
    return { ok: false, detail: e.message }
  }
}

// ---------------------------------------------------------------------------
// Project persistence API
// ---------------------------------------------------------------------------

/**
 * List all projects for a user, ordered by most recently updated.
 * @param {string} [userId] - User ID (resolved from Databricks auth on backend)
 * @returns {Promise<Array<{id: string, name: string, created_at: string, updated_at: string}>>}
 */
export async function listProjects(userId) {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  const response = await fetch(`${API_BASE_URL}/api/projects${params}`)
  if (!response.ok) throw new Error(`Failed to list projects: ${response.status}`)
  return response.json()
}

/**
 * Create a new project.
 * @param {string} name - Project name
 * @param {string} [userId] - User ID
 * @returns {Promise<{id: string, name: string, messages: Array, agent_steps: Array, created_at: string, updated_at: string}>}
 */
export async function createProject(name, userId) {
  const body = { name }
  if (userId) body.user_id = userId
  const response = await fetch(`${API_BASE_URL}/api/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`Failed to create project: ${response.status}`)
  return response.json()
}

/**
 * Load a project with its full messages and agent steps.
 * @param {string} projectId
 * @returns {Promise<{id: string, name: string, messages: Array, agent_steps: Array, created_at: string, updated_at: string}>}
 */
export async function loadProject(projectId) {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}`)
  if (!response.ok) throw new Error(`Failed to load project: ${response.status}`)
  return response.json()
}

/**
 * Update a project (name, messages, and/or agent_steps).
 * @param {string} projectId
 * @param {{name?: string, messages?: Array, agent_steps?: Array}} updates
 * @returns {Promise<Object>} Updated project
 */
export async function saveProject(projectId, updates) {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!response.ok) throw new Error(`Failed to save project: ${response.status}`)
  return response.json()
}

/**
 * Delete a project.
 * @param {string} projectId
 * @returns {Promise<{ok: boolean}>}
 */
export async function deleteProject(projectId) {
  const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(`Failed to delete project: ${response.status}`)
  return response.json()
}
