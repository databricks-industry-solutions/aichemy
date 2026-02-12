// API service for Databricks/MLflow agent calls

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
 * @param {Object} inputDict - Input dictionary with messages and custom inputs
 * @param {AbortSignal} [signal] - Optional abort signal
 * @param {function} onText - Called with each text chunk: onText(chunk)
 * @param {function} [onToolCalls] - Called with tool calls array
 * @param {function} [onGenie] - Called with genie results array
 * @param {function} [onStatus] - Called with status message string
 * @param {function} [onError] - Called with error string
 * @param {function} [onDone] - Called when stream completes
 */
export async function askAgentStream(inputDict, { signal, onText, onToolCalls, onGenie, onStatus, onError, onDone } = {}) {
  const url = `${API_BASE_URL}/api/agent/stream`

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
    buffer = lines.pop() // keep incomplete line in buffer

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const dataStr = line.slice(6)
      try {
        const event = JSON.parse(dataStr)
        switch (event.type) {
          case 'text':
            onText?.(event.content)
            break
          case 'status':
            onStatus?.(event.content)
            break
          case 'tool_calls':
            onToolCalls?.(event.data)
            break
          case 'genie':
            onGenie?.(event.data)
            break
          case 'error':
            onError?.(event.content)
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
 * @returns {Promise<{skills: Object, labels: string[], captions: string[]}>}
 */
export async function fetchSkills() {
  const response = await fetch(`${API_BASE_URL}/api/skills`)
  if (!response.ok) return { skills: {}, labels: [], captions: [] }
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
