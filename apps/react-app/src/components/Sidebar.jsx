import { useState, useEffect, useMemo } from 'react'
import { fetchSkills } from '../api/agentAPI'
import modelsTxt from '/models.txt?raw'

// Display names for MCP server names returned by the backend
const MCP_DISPLAY = {
  pubchem: '🧪 PubChem',
  pubmed: '📚 PubMed',
  opentargets: '🎯 OpenTargets',
}

// Load model list from public/models.txt
const MODEL_OPTIONS = modelsTxt
  .split('\n')
  .map(l => l.trim())
  .filter(Boolean)
  .map(v => ({ value: v, label: v }))

export default function Sidebar({
  projects = [],
  currentProjectId,
  onSelectProject,
  onNewProject,
  onRenameProject,
  onDeleteProject,
  selectedWorkflow,
  onSelectWorkflow,
  skillsEnabled,
  onToggleSkills,
  userInfo,
  mcpServers = [],
  enabledGroups = {},
  onToggleGroup,
  selectedModel = '',
  onModelChange,
  onRebuildAgent,
  isRebuilding = false,
}) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [skills, setSkills] = useState({})

  useEffect(() => {
    fetchSkills().then(setSkills).catch(() => {})
  }, [])

  const SKILL_RANK = {
    'target-identification': 0,
    'hit-identification': 1,
    'ADME-assessment': 2,
    'safety-assessment': 3,
  }

  const sortedSkillEntries = useMemo(() => {
    return Object.entries(skills).sort(
      ([a], [b]) => (SKILL_RANK[a] ?? Infinity) - (SKILL_RANK[b] ?? Infinity)
    )
  }, [skills])

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
      <div className="tools-section-header">
        <div className="sidebar-caption" style={{ marginBottom: 0 }}>Guided workflows</div>
        <label className="skills-toggle">
          <input
            type="checkbox"
            checked={skillsEnabled}
            onChange={(e) => onToggleSkills(e.target.checked)}
          /> Skills (SLOW!)
        </label>
      </div>
      <div className="skills-list">
        {sortedSkillEntries.map(([name, meta]) => (
          <label
            key={name}
            className={`skill-item${selectedWorkflow === name ? ' selected' : ''}`}
            onClick={() => onSelectWorkflow(selectedWorkflow === name ? null : name)}
          >
            <span className={`radio-dot${selectedWorkflow === name ? ' active' : ''}`} />
            <span className="skill-item-content">
              <span className="skill-item-label">{meta.label}</span>
              {meta.caption && <span className="skill-item-caption">{meta.caption}</span>}
            </span>
          </label>
        ))}
      </div>
      <div className="sidebar-divider" />

      {/* Agent configuration: model + MCP + rebuild */}
      <div className="sidebar-caption">Agent</div>

      {/* Model selector */}
      <div className="model-selector-row">
        <select
          className="model-selector"
          value={selectedModel}
          onChange={e => onModelChange?.(e.target.value)}
        >
          {!MODEL_OPTIONS.find(m => m.value === selectedModel) && selectedModel && (
            <option value={selectedModel}>{selectedModel}</option>
          )}
          {MODEL_OPTIONS.map(m => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>

      {/* Data Sources (MCP servers) */}
      <div className="mcp-list">
        {mcpServers.length === 0 && (
          <div className="mcp-item-empty">Loading…</div>
        )}
        {mcpServers.map(srv => {
          const isEnabled = enabledGroups[srv] !== false
          return (
            <label
              key={srv}
              className={`mcp-item${!isEnabled ? ' mcp-item-off' : ''}`}
            >
              <input
                type="checkbox"
                checked={isEnabled}
                onChange={e => onToggleGroup?.(srv, e.target.checked)}
              />
              <span className="mcp-item-label">
                {MCP_DISPLAY[srv] || srv}
              </span>
            </label>
          )
        })}
      </div>

      {/* Rebuild button — directly under MCP servers */}
      <button
        className={`rebuild-button${isRebuilding ? ' rebuilding' : ''}`}
        onClick={onRebuildAgent}
        disabled={isRebuilding}
        title="Rebuild the agent with the selected model and data sources"
      >
        {isRebuilding ? '⟳ Refreshing…' : '⟳ Refresh'}
      </button>

      <div className="sidebar-spacer" />
    </aside>
  )
}
