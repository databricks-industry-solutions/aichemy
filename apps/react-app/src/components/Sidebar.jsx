import { useState, useEffect, useMemo } from 'react'
import { fetchSkills } from '../api/agentAPI'
import toolsTsv from '../../tools.txt?raw'

const GROUP_LABELS = {
  'PubChem': '🧪 PubChem MCP',
  'OpenTargets': '🎯 OpenTargets MCP',
  'PubMed': '📚 PubMed MCP',
  'Chem Utils': '🛠️ Chem Utilities',
}

function parseToolsTsv(tsv) {
  const groups = {}
  for (const line of tsv.trim().split('\n').slice(1)) {
    const parts = line.split('\t')
    if (parts.length < 3) continue
    const [agent, tool, desc] = parts.map(s => s.trim())
    if (!groups[agent]) groups[agent] = []
    groups[agent].push({ name: tool, description: desc })
  }
  return Object.entries(groups).map(([key, tools]) => ({
    key,
    label: GROUP_LABELS[key] || `🔧 ${key}`,
    tools,
  }))
}

const TOOL_GROUPS = parseToolsTsv(toolsTsv)

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
}) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [expandedGroup, setExpandedGroup] = useState(null)
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
      <div className="tools-section-header">
        <div className="sidebar-caption" style={{ marginBottom: 0 }}>Guided workflows</div>
        <label className="skills-toggle" title="Load Skills (SLOW!)">
          <input
            type="checkbox"
            checked={skillsEnabled}
            onChange={(e) => onToggleSkills(e.target.checked)}
          />
          Skills
          <span className="skills-tooltip" title="When enabled, each workflow uses a structured skill prompt for richer, more guided results">?</span>
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

      {/* Available Tools */}
      <div className="sidebar-caption">Available tools</div>
      <div className="tools-list">
        {TOOL_GROUPS.map(({ key, label, tools: groupTools }) => (
          <div key={key} className="tool-group">
            <button
              className={`tool-group-header${expandedGroup === key ? ' expanded' : ''}`}
              onClick={() => toggleGroup(key)}
            >
              <span>{label}</span>
              <span className="chevron">{expandedGroup === key ? '▾' : '▸'}</span>
            </button>
            {expandedGroup === key && groupTools.length > 0 && (
              <div className="tool-group-items">
                {groupTools.map((t) => (
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
    </aside>
  )
}
