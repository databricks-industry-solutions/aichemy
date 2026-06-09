import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { WORKFLOWS_BY_NAME, PLACEHOLDER_LABELS } from '../workflows.js'

function ElapsedTimer() {
  const [seconds, setSeconds] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    ref.current = setInterval(() => setSeconds(s => s + 1), 1000)
    return () => clearInterval(ref.current)
  }, [])
  return <span className="elapsed-timer">{seconds}s</span>
}

const COMPOUND_PROPS = [
  "Structure: SMILES, InChI, MW...",
  "ADME: LogP, Druglikeness, CYP3A4...",
  "Bioactivity: IC50...",
  "All",
]

function fillTemplate(template, values) {
  return template.replace(/\$\{(\w+)\}/g, (_, key) =>
    values[key] != null && values[key] !== '' ? values[key] : `\${${key}}`
  )
}

function PromptPreview({ template, values }) {
  if (!template) return null
  const parts = template.split(/(\$\{\w+\})/g)
  return (
    <div className="workflow-prompt-preview">
      <div className="workflow-prompt-preview-label">Loads prompt:</div>
      <div className="workflow-prompt-preview-body">
        {parts.map((part, i) => {
          const match = part.match(/^\$\{(\w+)\}$/)
          if (!match) return <span key={i}>{part}</span>
          const key = match[1]
          const v = values[key]
          const filled = v != null && v !== ''
          return (
            <span key={i} className={`prompt-placeholder${filled ? ' filled' : ''}`}>
              {filled ? v : (PLACEHOLDER_LABELS[key] || part)}
            </span>
          )
        })}
      </div>
    </div>
  )
}

export default function ChatPanel({
  messages,
  projectName,
  exampleQuestions,
  onSendMessage,
  onReset,
  onStop,
  isLoading,
  statusMessage,
  chatHistoryRef,
  selectedWorkflow,
  onClearWorkflow,
  skillsEnabled,
}) {
  const [inputValue, setInputValue] = useState('')
  const [workflowInput, setWorkflowInput] = useState('')
  const [compoundProps, setCompoundProps] = useState([])
  const [helpOpen, setHelpOpen] = useState(false)
  const textareaRef = useRef(null)

  // Auto-grow the textarea as content expands
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${ta.scrollHeight}px`
  }, [inputValue])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (inputValue.trim() && !isLoading) {
      const skillName = skillsEnabled && selectedWorkflow ? selectedWorkflow : undefined
      onSendMessage(inputValue, { skillName })
      setInputValue('')
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const handleWorkflowSubmit = (prompt) => {
    if (prompt && !isLoading) {
      const skillName = skillsEnabled && selectedWorkflow ? selectedWorkflow : undefined
      onSendMessage(prompt, { skillName })
      setWorkflowInput('')
      setCompoundProps([])
    }
  }

  const handleExampleClick = (question) => {
    if (!isLoading) {
      onSendMessage(question)
    }
  }

  const toggleProp = (prop) => {
    setCompoundProps(prev =>
      prev.includes(prop) ? prev.filter(p => p !== prop) : [...prev, prop]
    )
  }

  const handleWorkflowEnter = () => {
    if (!workflowInput.trim()) return
    const wf = WORKFLOWS_BY_NAME[selectedWorkflow]
    if (!wf?.canned_prompt) return
    handleWorkflowSubmit(fillTemplate(wf.canned_prompt, { workflowInput }))
  }

  const handleWorkflowKeyDown = (e) => {
    if (e.key === 'Enter') handleWorkflowEnter()
  }

  const handleLeadOptSubmit = () => {
    if (!workflowInput.trim() || compoundProps.length === 0) return
    const wf = WORKFLOWS_BY_NAME['ADME-assessment']
    handleWorkflowSubmit(
      fillTemplate(wf.canned_prompt, {
        workflowInput,
        compoundProps: compoundProps.join(', '),
      })
    )
  }

  const currentWorkflow = selectedWorkflow ? WORKFLOWS_BY_NAME[selectedWorkflow] : null

  return (
    <section className="chat-column">
      {/* Header */}
      <div className="chat-header">
        <h2>{projectName || 'Chat'}</h2>
        <div className="header-buttons">
          <a
            className="header-btn"
            href="https://www.databricks.com/blog/aichemy-next-generation-agent-mcp-skills-and-custom-data-drug-discovery"
            target="_blank"
            rel="noopener noreferrer"
            title="Read the blog post"
          >
            📖 Blog
          </a>
          <a
            className="header-btn"
            href="https://e2-demo-west.cloud.databricks.com/apps-v2/app/aichemy/overview?o=2556758628403379"
            target="_blank"
            rel="noopener noreferrer"
            title="View code"
          >
            Code
          </a>
          <button className="header-btn" onClick={() => setHelpOpen(true)} title="Open help">
            ? Help
          </button>
        </div>
      </div>

      {/* Help Dialog */}
      {helpOpen && (
        <div className="help-overlay" onClick={() => setHelpOpen(false)}>
          <div className="help-dialog" onClick={e => e.stopPropagation()}>
            <div className="help-dialog-header">
              <h3>Help</h3>
              <button className="help-close-btn" onClick={() => setHelpOpen(false)} aria-label="Close">✕</button>
            </div>
            <div className="help-dialog-body">
              <h4>Recommended demo setup</h4>
              <ol>
                <li>Select Claude Sonnet 4.5, PubChem, ZINC and Chem Utils.</li>
                <li>Hit <strong>Refresh</strong>.</li>
                <li>Click on the <strong>+ New Project</strong> button to start a new conversation.</li>
              </ol>

              <h4>Demo tips</h4>
              <ul>
                <li>Click on the <strong>Blog</strong> button and show the architecture diagram, as well as get the <a href="https://aichemy-1.onrender.com" target="_blank" rel="noopener noreferrer">public app</a> and code from the blog.</li>
                <li>Click on the <strong>Code</strong> button to go to the app page for experiment traces, source code, logs.</li>
              </ul>

              <h4>Suggested prompts</h4>
                <h5>Persona: Researcher</h5>
                <ol>
                  <li>(First example on New Project page) Show me the molecule image of orforglipron.</li>
                  <li>Find in the ZINC vector search 3 molecules most similar to it</li>
                  <li>Predict the ADMET properties of the most similar molecule</li>
                </ol>
                <br />
                <h5>Persona: Commercial Analyst</h5>
                <ol>
                  <li>Select Web, PubMed, OpenTargets, Clinical Trials, Census, CMS MCP servers and hit <strong>Refresh</strong>.</li>
                  <li>Choose the <strong>Market Sizing</strong> workflow and input the drug <strong>orforglipron</strong></li>
                </ol>

              <h4>Settings</h4>
              <p>Select a model (Claude Sonnet 4.5 recommended) and MCP servers and hit <strong>Refresh</strong>.<br />
              Avoid selecting too many MCP servers at once.</p>
                
              <h4>Workflows</h4> 
              <p>Select a workflow to activate a guided, structured prompt. Fill in the workflow inputs and click <strong>Enter</strong> to start the workflow.</p>
 
              <h4>Cancel a query</h4>
              <p>Hit <strong>Stop</strong> to cancel the current request.</p>

              <h4>Reset the current thread/project</h4>
              <p>Hit <strong>↻ Reset</strong> to clear the <i>current</i> conversation.</p>

              <h4>Start a new thread/project</h4>
              <p>Hit <strong>+ New Project</strong> to start a <i>new</i> conversation.</p>

              <h4>Troubleshooting</h4>
              <p>
                <ul>
                  <li>Avoid changing projects while waiting for a response. The response may sometimes show up in the wrong project.</li>
                  <li>Click on the <strong>Code</strong> button to check the app logs for errors.</li>
                  <li>MCP status in orange or red means that the MCP server may be down. </li>
                </ul>
                <ol>        
                  Two options:
                  <li>Hit <strong>Reboot</strong> to reconnect all MCP servers, or</li>
                  <li>Unselect the MCP server in Settings and hit <strong>Refresh</strong>.</li>
                </ol>
              </p>
              <p>Check <a href={`${window.location.origin}/api/health`} target="_blank" rel="noopener noreferrer">{window.location.origin}/api/health</a> for more error details.</p>
            </div>
          </div>
        </div>
      )}

      {/* Chat History */}
      <div className="chat-history" ref={chatHistoryRef}>
        {messages.map((msg, idx) => (
          <div key={idx} className={`chat-message ${msg.role}`}>
            <div className={`message-avatar ${msg.role}`}>
              {msg.role === 'user' ? '👤' : '🤖'}
            </div>
            <div className="message-content">
              {msg.role === 'assistant' ? (
                <>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  {msg.traceId && (
                    <div className="trace-id-row">
                      <a
                        className="trace-link"
                        href={`${import.meta.env.VITE_API_URL || ''}/api/trace/${msg.traceId}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`View trace ${msg.traceId}`}
                      >
                        {msg.traceId}
                      </a>
                    </div>
                  )}
                </>
              ) : (
                <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
              )}
            </div>
          </div>
        ))}

        {/* Status / Thinking indicator */}
        {isLoading && (
          <div className="status-bar">
            <span className="spinner" />
            <span className="status-text">{statusMessage || 'Thinking...'}</span>
            <ElapsedTimer />
            <button type="button" className="stop-button" onClick={onStop}>Stop</button>
          </div>
        )}
      </div>

      {/* Workflow-specific inputs */}
      {currentWorkflow?.variant === 'adme' && (
        <div className="workflow-input-section">
          <PromptPreview
            template={currentWorkflow.canned_prompt}
            values={{
              workflowInput,
              compoundProps: compoundProps.length > 0 ? compoundProps.join(', ') : '',
            }}
          />
          <div className="workflow-input-row">
            <input
              className="workflow-text-input"
              placeholder={currentWorkflow.input_placeholder}
              value={workflowInput}
              onChange={(e) => setWorkflowInput(e.target.value)}
              disabled={isLoading}
            />
            <button type="button" className="clear-btn" onClick={onClearWorkflow}>Clear</button>
          </div>
          {workflowInput.trim() && (
            <div className="compound-props">
              <span className="props-label">What do you want to know?</span>
              <div className="pills-row">
                {COMPOUND_PROPS.map(prop => (
                  <button
                    key={prop}
                    type="button"
                    className={`pill${compoundProps.includes(prop) ? ' selected' : ''}`}
                    onClick={() => toggleProp(prop)}
                  >
                    {prop}
                  </button>
                ))}
              </div>
              {compoundProps.length > 0 && (
                <button type="button" className="submit-workflow-btn" onClick={handleLeadOptSubmit} disabled={isLoading}>
                  Search
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {currentWorkflow && !currentWorkflow.variant && (
        <div className="workflow-input-section">
          <PromptPreview
            template={currentWorkflow.canned_prompt}
            values={{ workflowInput }}
          />
          <div className="workflow-input-row">
            <input
              className="workflow-text-input"
              placeholder={currentWorkflow.input_placeholder}
              value={workflowInput}
              onChange={(e) => setWorkflowInput(e.target.value)}
              onKeyDown={handleWorkflowKeyDown}
              disabled={isLoading}
            />
            <button type="button" className="workflow-enter-btn" onClick={handleWorkflowEnter} disabled={isLoading || !workflowInput.trim()}>Enter</button>
            <button type="button" className="clear-btn" onClick={onClearWorkflow}>Clear</button>
          </div>
        </div>
      )}

      {/* Example Questions — only when no workflow selected and chat is empty */}
      {!selectedWorkflow && messages.length === 0 && (
        <div className="example-questions">
          <p className="caption"><strong>Try these example questions:</strong></p>
          <div className="pills-row example-pills">
            {exampleQuestions.map((question, idx) => (
              <button
                key={idx}
                type="button"
                className="pill example-pill"
                onClick={() => handleExampleClick(question)}
                disabled={isLoading}
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Chat Input + Reset */}
      <div className="chat-input-row">
        <form className="chat-input-container" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder="Ask me anything... (Shift+Enter for new line)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={1}
          />
          <button type="submit" className="send-button" disabled={isLoading || !inputValue.trim()}>
            Send
          </button>
        </form>
        <button type="button" className="reset-button" onClick={onReset} title="Reset chat">
          ↻ Reset
        </button>
      </div>
    </section>
  )
}
