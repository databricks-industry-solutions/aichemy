import { useState, useEffect, useRef, useCallback } from 'react'
import { fetchAgentStatus, warmupAgent } from '../api/agentAPI'

export default function AgentPanel({
  toolCallGroups,  // [{prompt, toolCalls: [{function_name, parameters, thinking}]}]
  genieGroups,     // [{prompt, results: [{description, query, result}]}]
  isLoading,
}) {
  const [agentStatus, setAgentStatus] = useState({ ready: false, building: true, error: null })
  const [warmingUp, setWarmingUp] = useState(false)
  const pollRef = useRef(null)

  const poll = useCallback(async () => {
    const status = await fetchAgentStatus()
    setAgentStatus(status)
    if (status.ready) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => {
    poll()
    pollRef.current = setInterval(poll, 5000)
    return () => clearInterval(pollRef.current)
  }, [poll])

  const handleWarmup = async () => {
    setWarmingUp(true)
    await warmupAgent()
    setTimeout(() => setWarmingUp(false), 8000)
  }

  const lightColor = agentStatus.error
    ? 'red'
    : agentStatus.ready
      ? 'green'
      : 'amber'

  return (
    <aside className="agent-column">
      <div className="agent-header-row">
        <h3 className="agent-title">Agent Activity</h3>
        <div className="agent-status-indicator">
          <span className={`traffic-light ${lightColor}`} title={
            agentStatus.error
              ? `Error: ${agentStatus.error}`
              : agentStatus.ready
                ? 'Agent ready'
                : 'Agent launching…'
          } />
          <span className="agent-status-label">
            {agentStatus.error ? 'Error' : agentStatus.ready ? 'Ready' : 'Launching agent…'}
          </span>
          {agentStatus.ready && (
            <button
              className="warmup-btn"
              onClick={handleWarmup}
              disabled={warmingUp}
              title="Send a warmup query to pre-warm LLM endpoints"
            >
              {warmingUp ? 'Rebooting…' : 'Reboot'}
            </button>
          )}
        </div>
      </div>
      <div className="agent-divider" />

      <div className="agent-activity-scroll">
        {/* Tool call groups (most recent first) */}
        {[...toolCallGroups].reverse().map((group, gi) => (
          <div key={`tc-${gi}`} className="activity-group">
            <div className="activity-group-prompt">
              Tool: <em>{group.prompt.slice(0, 80)}...</em>
            </div>
            {group.toolCalls.map((tc, ti) => (
              <ToolCallExpander key={ti} index={ti + 1} toolCall={tc} />
            ))}
            <div className="agent-divider" />
          </div>
        ))}

        {/* Genie SQL groups (most recent first) */}
        {[...genieGroups].reverse().map((group, gi) => (
          <div key={`ge-${gi}`} className="activity-group">
            {group.results.map((g, ri) => (
              <GenieExpander key={ri} genie={g} prompt={group.prompt} />
            ))}
            <div className="agent-divider" />
          </div>
        ))}

        {/* Empty state */}
        {toolCallGroups.length === 0 && genieGroups.length === 0 && !isLoading && (
          <div className="status-info">🤖 Enter a query to see agent activity</div>
        )}

        {isLoading && (
          <div className="status-info">
            <span className="spinner" /> Thinking...
          </div>
        )}
      </div>
    </aside>
  )
}

function ToolCallExpander({ index, toolCall }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="expander">
      <button className="expander-header" onClick={() => setOpen(!open)}>
        <span className="expander-title">
          <span className="tool-badge">{index}.</span>
          <span className="tool-icon">🔧</span>
          <span className="tool-fn-name">{toolCall.function_name}</span>
        </span>
        <span className="chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="expander-body">
          {toolCall.parameters && Object.entries(toolCall.parameters).map(([k, v]) => (
            <div key={k} className="tool-param">
              <strong>{k}:</strong> {v}
            </div>
          ))}
          {toolCall.results && (
            <pre className="tool-results">{toolCall.results.length > 1060 ? toolCall.results.slice(0, 1060) + '...' : toolCall.results}</pre>
          )}
        </div>
      )}
    </div>
  )
}

function GenieExpander({ genie, prompt }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="expander">
      <button className="expander-header" onClick={() => setOpen(!open)}>
        <span className="expander-title">
          <span className="tool-badge genie">SQL:</span>
          <em>{prompt.slice(0, 80)}...</em>
        </span>
        <span className="chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="expander-body">
          {genie.description && <div className="tool-param">{genie.description}</div>}
          {genie.query && <pre className="genie-sql">{genie.query}</pre>}
        </div>
      )}
    </div>
  )
}
