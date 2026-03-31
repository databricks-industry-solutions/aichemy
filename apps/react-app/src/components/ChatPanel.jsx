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
}) {
  const [inputValue, setInputValue] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (inputValue.trim() && !isLoading) {
      const skillName = selectedWorkflow || undefined
      onSendMessage(inputValue, { skillName })
      setInputValue('')
    }
  }

  const handleExampleClick = (question) => {
    if (!isLoading) {
      onSendMessage(question)
    }
  }

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

      {/* Example Questions — only when no skill selected and chat is empty */}
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
            placeholder="Ask me anything..."
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
