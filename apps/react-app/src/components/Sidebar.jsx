import { useState, useEffect } from 'react'
import { fetchTools } from '../api/agentAPI'

// Tool groups with their display config (matches Streamlit app order)
const TOOL_GROUPS = [
  { key: 'OpenTargets', label: '🎯 OpenTargets MCP', caption: null },
  { key: 'PubChem', label: '🧪 PubChem MCP', caption: null },
  { key: 'Chem Utils', label: '🛠️ Chem Utilities', caption: null },
  { key: 'PubMed', label: '📚 PubMed MCP', caption: null },
  { key: 'DrugBank', label: '💊 DrugBank Genie', caption: 'text-to-SQL of DrugBank' },
  { key: 'ZINC', label: '🔬 ZINC Vector Search', caption: 'similarity search' },
]

export default function Sidebar({
  projects = [],
  currentProjectId,
  onSelectProject,
  onNewProject,
  onRenameProject,
  onDeleteProject,
  workflows,
  workflowCaptions,
  selectedWorkflow,
  onSelectWorkflow,
  skillsEnabled,
  onToggleSkills,
  dbStatus,
}) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [tools, setTools] = useState({})
  const [expandedGroup, setExpandedGroup] = useState(null)

  // Load tools on mount
  useEffect(() => {
    fetchTools().then(setTools).catch(() => {})
  }, [])

  const startRename = (project) => {
    setRenamingId(project.id)
    setRenameValue(project.name)
  }

  const commitRename = () => {
    if (renamingId && renameValue.trim()) {
      onRenameProject(renamingId, renameValue.trim())
    }
    setRenamingId(null)
    setRenameValue('')
  }

  const handleRenameKeyDown = (e) => {
    if (e.key === 'Enter') commitRename()
    if (e.key === 'Escape') {
      setRenamingId(null)
      setRenameValue('')
    }
  }

  const handleDelete = (e, projectId) => {
    e.stopPropagation()
    if (window.confirm('Delete this project? This cannot be undone.')) {
      onDeleteProject(projectId)
    }
  }

  const toggleGroup = (key) => {
    setExpandedGroup(expandedGroup === key ? null : key)
  }

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <img src="/logo.svg" alt="AiChemy" className="logo-svg" />
      </div>

      {/* New Project button */}
      <button className="new-project-button" onClick={() => onNewProject()}>
        + New Project
      </button>

      {/* Project list */}
      <div className="sidebar-caption">Projects</div>
      <div className="project-list">
        {projects.map((project) => (
          <div
            key={project.id}
            className={`project-item${project.id === currentProjectId ? ' active' : ''}`}
            onClick={() => onSelectProject(project.id)}
          >
            <span className="icon">🧬</span>
            {renamingId === project.id ? (
              <input
                className="rename-input"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={commitRename}
                onKeyDown={handleRenameKeyDown}
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span
                className="project-name"
                onDoubleClick={(e) => { e.stopPropagation(); startRename(project) }}
              >
                {project.name}
              </span>
            )}
            <span className="project-actions">
              <button className="action-btn" title="Rename" onClick={(e) => { e.stopPropagation(); startRename(project) }}>✏️</button>
              <button className="action-btn" title="Delete" onClick={(e) => handleDelete(e, project.id)}>🗑️</button>
            </span>
          </div>
        ))}
      </div>

      <div className="sidebar-divider" />

      {/* Guided Workflows header with Skills checkbox */}
      <div className="guided-header">
        <div className="sidebar-caption" style={{ marginBottom: 0 }}>Guided workflows</div>
        <label className="skills-toggle">
          <input
            type="checkbox"
            checked={skillsEnabled}
            onChange={(e) => onToggleSkills(e.target.checked)}
          />
          <span className="skills-label">Skills</span>
          <span className="skills-help-icon" data-tooltip="Enable Skills (SLOW!) for detailed and consistent outputs">?</span>
        </label>
      </div>
      <div className="workflow-radio-group">
        {workflows.map((wf, idx) => (
          <label
            key={wf}
            className={`workflow-radio-item${selectedWorkflow === wf ? ' selected' : ''}`}
            onClick={() => onSelectWorkflow(selectedWorkflow === wf ? null : wf)}
          >
            <span className={`radio-dot${selectedWorkflow === wf ? ' active' : ''}`} />
            <span className="workflow-radio-content">
              <span className="workflow-radio-label">{wf}</span>
              <span className="workflow-radio-caption">{workflowCaptions[idx]}</span>
            </span>
          </label>
        ))}
      </div>

      <div className="sidebar-divider" />

      {/* Available Tools */}
      <div className="sidebar-caption">Available tools</div>
      <div className="tools-list">
        {TOOL_GROUPS.map(({ key, label, caption }) => (
          <div key={key} className="tool-group">
            <button
              className={`tool-group-header${expandedGroup === key ? ' expanded' : ''}`}
              onClick={() => toggleGroup(key)}
            >
              <span>{label}</span>
              <span className="chevron">{expandedGroup === key ? '▾' : '▸'}</span>
            </button>
            {expandedGroup === key && (
              <>
                {caption && <div className="tool-group-caption">{caption}</div>}
                {tools[key] && (
                  <div className="tool-group-items">
                    {tools[key].map((t) => (
                      <div key={t.name} className="tool-item">{t.name}</div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>

      {/* DB status indicator */}
      <div className="sidebar-spacer" />
      <div className="db-status-badge" title={dbStatus?.db_detail || ''}>
        <span className={`db-dot ${dbStatus?.db_backend === 'lakebase' ? 'connected' : 'local'}`} />
        <span className="db-label">
          {dbStatus?.db_backend === 'lakebase' ? 'Lakebase' : dbStatus?.db_backend === 'sqlite' ? 'SQLite (local)' : '…'}
        </span>
      </div>
    </aside>
  )
}
