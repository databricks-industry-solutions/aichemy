import { useState, useEffect, useMemo } from 'react'
import { fetchTools, fetchSkills } from '../api/agentAPI'

export default function Sidebar({
  projects = [],
  currentProjectId,
  onSelectProject,
  onNewProject,
  onRenameProject,
  onDeleteProject,
  selectedWorkflow,
  onSelectWorkflow,
  userInfo,
}) {
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [tools, setTools] = useState({})
  const [expandedGroup, setExpandedGroup] = useState(null)
  const [toolSearch, setToolSearch] = useState('')
  const [skills, setSkills] = useState({})
  const [skillSearch, setSkillSearch] = useState('')

  useEffect(() => {
    fetchTools().then(setTools).catch(() => {})
    fetchSkills().then(setSkills).catch(() => {})
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

  const filteredSkillEntries = useMemo(() => {
    const entries = Object.entries(skills)
    if (!skillSearch.trim()) return entries
    const q = skillSearch.toLowerCase()
    return entries.filter(
      ([name, meta]) =>
        name.toLowerCase().includes(q) ||
        meta.label?.toLowerCase().includes(q) ||
        meta.description?.toLowerCase().includes(q)
    )
  }, [skills, skillSearch])

  const totalSkillCount = useMemo(() => Object.keys(skills).length, [skills])

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

      {/* Available Skills */}
      <div className="tools-section-header">
        <div className="sidebar-caption" style={{ marginBottom: 0 }}>
          Available skills
          {totalSkillCount > 0 && <span className="tool-count-badge">{totalSkillCount}</span>}
        </div>
      </div>
      <div className="tools-search-wrapper">
        <input
          className="tools-search-input"
          type="text"
          placeholder="Search skills…"
          value={skillSearch}
          onChange={(e) => setSkillSearch(e.target.value)}
        />
        {skillSearch && (
          <button className="tools-search-clear" onClick={() => setSkillSearch('')}>×</button>
        )}
      </div>
      <div className="skills-list">
        {filteredSkillEntries.length === 0 && skillSearch && (
          <div className="tools-empty">No skills match &ldquo;{skillSearch}&rdquo;</div>
        )}
        {filteredSkillEntries.map(([name, meta]) => (
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
      <a href="/api/skills" target="_blank" rel="noopener noreferrer" className="sidebar-view-link">
        View all skills
      </a>

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
      <a href="/api/tools" target="_blank" rel="noopener noreferrer" className="sidebar-view-link">
        View all tools
      </a>
    </aside>
  )
}
