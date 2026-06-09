import { useState } from 'react'
import { WORKFLOWS } from '../workflows.js'
import modelsTxt from '/models.txt?raw'

// Display names for all agent component keys returned by the backend
const MCP_DISPLAY = {
  // external_mcp
  pubchem:               '🧪 PubChem',
  // custom_mcp
  opentargets:           '🎯 OpenTargets',
  // uc_connections
  pubmed:                '📚 PubMed',
  'bio/medrxiv':         '📄 bioRxiv / medRxiv',
  clinical_trials:       '🏥 ClinicalTrials',
  openfda:               '🏛️ OpenFDA',
  US_census:             '🇺🇸 US Census',
  cms:                   '📋 CMS Coverage',
  bioportal:             '🔗 BioPortal',
  biocontext:            '🧬 BioContext',
  kythera:               '🇰 Kythera',
  atropos:               '🇦 Atropos Health',
  // retriever
  zinc_vector_search: '🔍 ZINC Search',
  // genie
  drugbank:              '💊 DrugBank',
  claims:                '💊 Claims',
  // uc_functions
  chem_utils:            '🛠️ Chem Utils',
  web:                   '🌐 Web Search'
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

      {/* Section 1: Projects */}
      <div className="sidebar-section">
        <button type="button" className="new-project-button" onClick={() => onNewProject()}>
          + New Project
        </button>
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
                <button type="button" className="action-btn" title="Rename" onClick={(e) => { e.stopPropagation(); startRename(project) }}>✏️</button>
                <button type="button" className="action-btn" title="Delete" onClick={(e) => handleDelete(e, project.id)}>🗑️</button>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Section 2: Guided Workflows */}
      <div className="sidebar-section">
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
          {WORKFLOWS.map((workflow) => (
            <label
              key={workflow.name}
              className={`skill-item${selectedWorkflow === workflow.name ? ' selected' : ''}`}
              onClick={() => onSelectWorkflow(selectedWorkflow === workflow.name ? null : workflow.name)}
              title={workflow.caption || ''}
            >
              <span className={`radio-dot${selectedWorkflow === workflow.name ? ' active' : ''}`} />
              <span className="skill-item-content">
                <span className="skill-item-label">{workflow.label}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Section 3: Settings */}
      <div className="sidebar-section">
        <div className="sidebar-caption">Settings</div>
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
        <button
          type="button"
          className={`rebuild-button${isRebuilding ? ' rebuilding' : ''}`}
          onClick={onRebuildAgent}
          disabled={isRebuilding}
          title="Rebuild the agent with the selected model and data sources"
        >
          {isRebuilding ? '⟳ Refreshing…' : '⟳ Refresh'}
        </button>
      </div>
    </aside>
  )
}
