import { useState, useRef, useEffect, useCallback } from 'react'
import { v4 as uuidv4 } from 'uuid'
import Sidebar from './components/Sidebar'
import ChatPanel from './components/ChatPanel'
import AgentPanel from './components/AgentPanel'
import {
  askAgentStream,
  fetchUserInfo,
  fetchDbStatus,
  listProjects,
  createProject,
  loadProject,
  saveProject,
  deleteProject as deleteProjectAPI,
} from './api/agentAPI'

// Workflow definitions (matches Streamlit app)
const WORKFLOWS = [
  "🧬 Target identification",
  "⌬ Hit identification",
  "🧪 Lead optimization",
  "☠️ Safety assessment",
]

const WORKFLOW_CAPTIONS = [
  "Based on a disease, get its associated targets",
  "Based on a target, get its associated drugs",
  "Based on a compound, get its properties",
  "Based on a compound, get its safety info",
]

// Workflow index → skill folder name (used when skills checkbox is enabled)
const SKILL_FOLDER_BY_WORKFLOW = {
  0: 'target-identification',
  1: 'hit-identification',
  2: 'ADME-assessment',
  3: 'safety-assessment',
}

const EXAMPLE_QUESTIONS = [
  "Get the latest review study on the GI toxicity of danuglipron",
  "What diseases are associated with EGFR",
  "Show me compounds similar to vemurafenib. Display their structures",
  "List all the drugs in the GLP-1 agonists ATC class in DrugBank",
]

export default function App() {
  // Project state
  const [projects, setProjects] = useState([])
  const [currentProjectId, setCurrentProjectId] = useState(null)
  const [currentProjectName, setCurrentProjectName] = useState('')

  // Chat state
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const [abortController, setAbortController] = useState(null)

  // Agent activity state
  const [toolCallGroups, setToolCallGroups] = useState([])
  const [genieGroups, setGenieGroups] = useState([])

  // Workflow state
  const [selectedWorkflow, setSelectedWorkflow] = useState(null)
  const [skillsEnabled, setSkillsEnabled] = useState(false)

  // User identity (fetched from backend on mount)
  const [userInfo, setUserInfo] = useState({ user_id: null, user_name: '', user_email: '' })

  // DB backend status
  const [dbStatus, setDbStatus] = useState(null)

  const chatHistoryRef = useRef(null)

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (chatHistoryRef.current) {
      chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight
    }
  }, [messages, isLoading])

  // ---------------------------------------------------------------------------
  // Project persistence
  // ---------------------------------------------------------------------------

  useEffect(() => {
    async function init() {
      try {
        const [user, status] = await Promise.all([fetchUserInfo(), fetchDbStatus()])
        setUserInfo(user)
        setDbStatus(status)
        const list = await listProjects(user.user_id)
        setProjects(list)
        if (list.length > 0) {
          await switchToProject(list[0].id)
        } else {
          await handleNewProject('Project 1')
        }
      } catch (err) {
        console.error('Failed to load projects:', err)
        setCurrentProjectId(uuidv4())
        setCurrentProjectName('Project 1')
      }
    }
    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-save messages + agent steps (debounced)
  const autoSaveRef = useRef(null)
  useEffect(() => {
    if (!currentProjectId || messages.length === 0) return
    clearTimeout(autoSaveRef.current)
    autoSaveRef.current = setTimeout(() => {
      saveProject(currentProjectId, {
        messages,
        agent_steps: { toolCallGroups, genieGroups },
      }).catch(err =>
        console.error('Auto-save failed:', err)
      )
    }, 500)
    return () => clearTimeout(autoSaveRef.current)
  }, [messages, toolCallGroups, genieGroups, currentProjectId])

  const refreshProjectList = useCallback(async () => {
    try {
      const list = await listProjects(userInfo.user_id)
      setProjects(list)
    } catch (err) {
      console.error('Failed to refresh project list:', err)
    }
  }, [userInfo.user_id])

  const switchToProject = async (projectId) => {
    if (projectId === currentProjectId) return
    try {
      const project = await loadProject(projectId)
      setCurrentProjectId(project.id)
      setCurrentProjectName(project.name)
      setMessages(project.messages || [])
      // Restore agent activity from persisted agent_steps
      const steps = project.agent_steps || {}
      setToolCallGroups(steps.toolCallGroups || [])
      setGenieGroups(steps.genieGroups || [])
      setSelectedWorkflow(null)
      setIsLoading(false)
    } catch (err) {
      console.error('Failed to load project:', err)
    }
  }

  const handleNewProject = async (name) => {
    try {
      const project = await createProject(name || 'Untitled Project', userInfo.user_id)
      await refreshProjectList()
      setCurrentProjectId(project.id)
      setCurrentProjectName(project.name)
      setMessages([])
      setToolCallGroups([])
      setGenieGroups([])
      setSelectedWorkflow(null)
      setIsLoading(false)
    } catch (err) {
      console.error('Failed to create project:', err)
    }
  }

  const handleRenameProject = async (projectId, newName) => {
    try {
      await saveProject(projectId, { name: newName })
      if (projectId === currentProjectId) setCurrentProjectName(newName)
      await refreshProjectList()
    } catch (err) {
      console.error('Failed to rename project:', err)
    }
  }

  const handleDeleteProject = async (projectId) => {
    try {
      await deleteProjectAPI(projectId)
      const updatedList = projects.filter(p => p.id !== projectId)
      setProjects(updatedList)
      if (projectId === currentProjectId) {
        if (updatedList.length > 0) {
          await switchToProject(updatedList[0].id)
        } else {
          await handleNewProject('Project 1')
        }
      }
    } catch (err) {
      console.error('Failed to delete project:', err)
    }
  }

  // ---------------------------------------------------------------------------
  // Chat actions
  // ---------------------------------------------------------------------------

  const handleReset = async () => {
    setMessages([])
    setToolCallGroups([])
    setGenieGroups([])
    setSelectedWorkflow(null)
    setIsLoading(false)
    setStatusMessage('')
    if (currentProjectId) {
      saveProject(currentProjectId, {
        messages: [],
        agent_steps: { toolCallGroups: [], genieGroups: [] },
      }).catch(err =>
        console.error('Failed to save reset:', err)
      )
    }
  }

  const handleStop = () => {
    if (abortController) {
      abortController.abort()
      setAbortController(null)
    }
    setIsLoading(false)
    setStatusMessage('')
  }

  const handleSendMessage = async (prompt, { skillName } = {}) => {
    if (!prompt.trim() || isLoading) return

    setIsLoading(true)
    setSelectedWorkflow(null)

    // Add user message + placeholder assistant message for streaming
    const userMessage = { role: 'user', content: prompt }
    setMessages(prev => [...prev, userMessage, { role: 'assistant', content: '' }])

    const controller = new AbortController()
    setAbortController(controller)

    try {
      const inputDict = {
        input: [{ role: 'user', content: prompt }],
        custom_inputs: { thread_id: currentProjectId },
      }
      // If skills are enabled, attach the skill_name so the backend wraps the prompt
      if (skillName) {
        inputDict.skill_name = skillName
      }

      // Stream text chunks into the last (assistant) message
      await askAgentStream(inputDict, {
        signal: controller.signal,
        onStatus: (msg) => {
          setStatusMessage(msg)
        },
        onText: (chunk) => {
          setStatusMessage('')  // clear status once text starts flowing
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            updated[updated.length - 1] = { ...last, content: last.content + chunk }
            return updated
          })
        },
        onToolCalls: (toolCalls) => {
          setToolCallGroups(prev => [...prev, { prompt, toolCalls }])
        },
        onGenie: (results) => {
          setGenieGroups(prev => [...prev, { prompt, results }])
        },
        onError: (errMsg) => {
          setMessages(prev => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              role: 'assistant',
              content: `Error: ${errMsg}. Please try again or reset the chat.`,
            }
            return updated
          })
        },
        onDone: () => {
          refreshProjectList()
        },
      })
    } catch (error) {
      if (error.name === 'AbortError') return
      console.error('Error calling agent:', error)
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant' && !last.content) {
          updated[updated.length - 1] = {
            role: 'assistant',
            content: `Error: ${error.message}. Please try again or reset the chat.`,
          }
        }
        return updated
      })
    } finally {
      setIsLoading(false)
      setStatusMessage('')
      setAbortController(null)
    }
  }

  return (
    <div className="app-container">
      <Sidebar
        projects={projects}
        currentProjectId={currentProjectId}
        onSelectProject={switchToProject}
        onNewProject={handleNewProject}
        onRenameProject={handleRenameProject}
        onDeleteProject={handleDeleteProject}
        workflows={WORKFLOWS}
        workflowCaptions={WORKFLOW_CAPTIONS}
        selectedWorkflow={selectedWorkflow}
        onSelectWorkflow={setSelectedWorkflow}
        skillsEnabled={skillsEnabled}
        onToggleSkills={setSkillsEnabled}
        dbStatus={dbStatus}
      />
      <main className="main-content">
        <ChatPanel
          messages={messages}
          projectName={currentProjectName}
          exampleQuestions={EXAMPLE_QUESTIONS}
          onSendMessage={handleSendMessage}
          onReset={handleReset}
          onStop={handleStop}
          isLoading={isLoading}
          statusMessage={statusMessage}
          chatHistoryRef={chatHistoryRef}
          selectedWorkflow={selectedWorkflow}
          onClearWorkflow={() => setSelectedWorkflow(null)}
          skillsEnabled={skillsEnabled}
          skillFolderByWorkflow={SKILL_FOLDER_BY_WORKFLOW}
          workflows={WORKFLOWS}
        />
        <AgentPanel
          toolCallGroups={toolCallGroups}
          genieGroups={genieGroups}
          isLoading={isLoading}
        />
      </main>
    </div>
  )
}
