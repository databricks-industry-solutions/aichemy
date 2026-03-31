import { useState, useEffect, useMemo } from 'react'
import { fetchTools } from '../api/agentAPI'

// Tool groups with their display config (matches Streamlit app order)
// const TOOL_GROUPS = [
//   { key: 'OpenTargets', label: '🎯 OpenTargets MCP', caption: null },
//   { key: 'PubChem', label: '🧪 PubChem MCP', caption: null },
//   { key: 'Chem Utils', label: '🛠️ Chem Utilities', caption: null },
//   { key: 'PubMed', label: '📚 PubMed MCP', caption: null },
//   { key: 'DrugBank', label: '💊 DrugBank Genie', caption: 'text-to-SQL of DrugBank' },
//   { key: 'ZINC', label: '🔬 ZINC Vector Search', caption: 'similarity search' },
// ]

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
  userInfo,
}) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [tools, setTools] = useState({})
  const [expandedGroup, setExpandedGroup] = useState(null)
  const [toolSearch, setToolSearch] = useState('')

  useEffect(() => {
    fetchTools().then(setTools).catch(() => {})
  }, [])

  const filteredTools = useMemo(() => {
    if (!toolSearch.trim()) return tools
    const q = toolSearch.toLowerCase()
    const result = {}
    for (const [agent, agentTools] of Object.entries(tools)) {
      if (agent.toLowerCase().includes(q)) {
        result[agent] = agentTools
        continue
      }
      const matched = agentTools.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          (t.description && t.description.toLowerCase().includes(q))
      )
      if (matched.length > 0) result[agent] = matched
    }
    return result
  }, [tools, toolSearch])

  const totalToolCount = useMemo(
    () => Object.values(tools).reduce((sum, arr) => sum + arr.length, 0),
    [tools]
  )

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

      {/* Welcome banner */}
      {userInfo?.user_name && (
        <div className="sidebar-welcome">Welcome, {userInfo.user_name}</div>
      )}

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
      <div className="tools-section-header">
        <div className="sidebar-caption" style={{ marginBottom: 0 }}>
          Available tools
          {totalToolCount > 0 && <span className="tool-count-badge">{totalToolCount}</span>}
        </div>
      </div>
      <div className="tools-search-wrapper">
        <input
          className="tools-search-input"
          type="text"
          placeholder="Search tools…"
          value={toolSearch}
          onChange={(e) => setToolSearch(e.target.value)}
        />
        {toolSearch && (
          <button className="tools-search-clear" onClick={() => setToolSearch('')}>×</button>
        )}
      </div>
      <div className="tools-list">
        {Object.keys(filteredTools).length === 0 && toolSearch && (
          <div className="tools-empty">No tools match "{toolSearch}"</div>
        )}
        {Object.entries(filteredTools).map(([agentName, agentTools]) => (
          <div key={agentName} className="tool-group">
            <button
              className={`tool-group-header${expandedGroup === agentName ? ' expanded' : ''}`}
              onClick={() => toggleGroup(agentName)}
            >
              <span className="tool-group-label">
                <span className="tool-group-name">{agentName}</span>
                <span className="tool-group-count">{agentTools.length}</span>
              </span>
              <span className="chevron">{expandedGroup === agentName ? '▾' : '▸'}</span>
            </button>
            {expandedGroup === agentName && (
              <div className="tool-group-items">
                {agentTools.map((t) => (
                  <div key={t.name} className="tool-item">
                    <span className="tool-item-name">{t.name}</span>
                    {t.description && <span className="tool-item-desc">{t.description}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="sidebar-spacer" />
      <a href="/api/tools" target="_blank" rel="noopener noreferrer" className="sidebar-tools-link">
        View all tools
      </a>
    </aside>
  )
}
