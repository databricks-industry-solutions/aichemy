import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function ElapsedTimer() {
  const [seconds, setSeconds] = useState(0)
  const ref = useRef(null)
  useEffect(() => {
    ref.current = setInterval(() => setSeconds(s => s + 1), 1000)
    return () => clearInterval(ref.current)
  }, [])
  return <span className="elapsed-timer">{seconds}s</span>
}

// Fallback workflow list (used if workflows prop not provided)
const DEFAULT_WORKFLOWS = [
  "🧬 Target identification",
  "⌬ Hit identification",
  "🧪 Lead optimization",
  "☠️ Safety assessment",
]

const COMPOUND_PROPS = [
  "Structure: SMILES, InChI, MW...",
  "ADME: LogP, Druglikeness, CYP3A4...",
  "Bioactivity: IC50...",
  "All",
]

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
  skillFolderByWorkflow,
  workflows,
}) {
  const [inputValue, setInputValue] = useState('')
  const [workflowInput, setWorkflowInput] = useState('')
  const [compoundProps, setCompoundProps] = useState([])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (inputValue.trim() && !isLoading) {
      onSendMessage(inputValue)
      setInputValue('')
    }
  }

  // Resolve the skill folder name for the current workflow (if skills enabled)
  const getSkillName = () => {
    if (!skillsEnabled || !selectedWorkflow || !workflows || !skillFolderByWorkflow) return undefined
    const idx = workflows.indexOf(selectedWorkflow)
    return idx >= 0 ? skillFolderByWorkflow[idx] : undefined
  }

  const handleWorkflowSubmit = (prompt) => {
    if (prompt && !isLoading) {
      const skillName = getSkillName()
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

  const wf = workflows || DEFAULT_WORKFLOWS

  // Build workflow prompt on Enter
  const handleWorkflowKeyDown = (e) => {
    if (e.key !== 'Enter' || !workflowInput.trim()) return

    if (selectedWorkflow === wf[0]) {
      handleWorkflowSubmit(
        `Use OpenTargets to find targets associated with ${workflowInput}. Show their scores if any and rank in descending order of scores.`
      )
    } else if (selectedWorkflow === wf[1]) {
      handleWorkflowSubmit(
        `Use OpenTargets to find drugs associated with ${workflowInput}. Show their scores if any and rank in descending order of scores.`
      )
    } else if (selectedWorkflow === wf[3]) {
      handleWorkflowSubmit(
        `Use PubChem and PubMed to find safety profile of ${workflowInput}. If citing studies, please state the strength of the evidence based on the study design.`
      )
    }
    // Lead optimization handled by pill selection
  }

  const handleLeadOptSubmit = () => {
    if (!workflowInput.trim() || compoundProps.length === 0) return
    const propsStr = compoundProps.join(', ')
    handleWorkflowSubmit(
      `Use PubChem to get ${propsStr} properties of ${workflowInput}.`
    )
  }

  return (
    <section className="chat-column">
      {/* Header */}
      <div className="chat-header">
        <h2>{projectName || 'Untitled Project'}</h2>
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
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              ) : (
                msg.content
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
            <button className="stop-button" onClick={onStop}>Stop</button>
          </div>
        )}
      </div>

      {/* Workflow-specific inputs */}
      {selectedWorkflow === wf[0] && (
        <div className="workflow-input-row">
          <input
            className="workflow-text-input"
            placeholder="e.g., breast cancer, Alzheimer's disease"
            value={workflowInput}
            onChange={(e) => setWorkflowInput(e.target.value)}
            onKeyDown={handleWorkflowKeyDown}
            disabled={isLoading}
          />
          <button className="clear-btn" onClick={onClearWorkflow}>Clear</button>
        </div>
      )}

      {selectedWorkflow === wf[1] && (
        <div className="workflow-input-row">
          <input
            className="workflow-text-input"
            placeholder="e.g., BRCA1, GLP-1"
            value={workflowInput}
            onChange={(e) => setWorkflowInput(e.target.value)}
            onKeyDown={handleWorkflowKeyDown}
            disabled={isLoading}
          />
          <button className="clear-btn" onClick={onClearWorkflow}>Clear</button>
        </div>
      )}

      {selectedWorkflow === wf[2] && (
        <div className="workflow-input-section">
          <div className="workflow-input-row">
            <input
              className="workflow-text-input"
              placeholder="e.g., acetaminophen, semaglutide, CHEMBL25"
              value={workflowInput}
              onChange={(e) => setWorkflowInput(e.target.value)}
              disabled={isLoading}
            />
            <button className="clear-btn" onClick={onClearWorkflow}>Clear</button>
          </div>
          {workflowInput.trim() && (
            <div className="compound-props">
              <span className="props-label">What do you want to know?</span>
              <div className="pills-row">
                {COMPOUND_PROPS.map(prop => (
                  <button
                    key={prop}
                    className={`pill${compoundProps.includes(prop) ? ' selected' : ''}`}
                    onClick={() => toggleProp(prop)}
                  >
                    {prop}
                  </button>
                ))}
              </div>
              {compoundProps.length > 0 && (
                <button className="submit-workflow-btn" onClick={handleLeadOptSubmit} disabled={isLoading}>
                  Search
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {selectedWorkflow === wf[3] && (
        <div className="workflow-input-row">
          <input
            className="workflow-text-input"
            placeholder="e.g., danuglipron, semaglutide"
            value={workflowInput}
            onChange={(e) => setWorkflowInput(e.target.value)}
            onKeyDown={handleWorkflowKeyDown}
            disabled={isLoading}
          />
          <button className="clear-btn" onClick={onClearWorkflow}>Clear</button>
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
          <input
            type="text"
            className="chat-input"
            placeholder="Ask AiChemy anything..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isLoading}
          />
          <button type="submit" className="send-button" disabled={isLoading || !inputValue.trim()}>
            Send
          </button>
        </form>
        <button className="reset-button" onClick={onReset} title="Reset chat">
          ↻ Reset
        </button>
      </div>
    </section>
  )
}
