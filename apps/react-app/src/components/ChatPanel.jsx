import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { WORKFLOWS_BY_NAME, PLACEHOLDER_LABELS } from '../workflows'

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
      </div>

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
