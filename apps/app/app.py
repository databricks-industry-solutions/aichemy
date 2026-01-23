import logging
import streamlit as st
from mlflow.deployments import get_deploy_client
from utils import get_user_info, ask_agent_mlflowclient, extract_text_content
from uuid import uuid4
from pprint import pprint
import time
from io import BytesIO

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# w = WorkspaceClient()
client = get_deploy_client("databricks")
user_info = get_user_info()

# ============================================================================
# Page Config
# ============================================================================

st.set_page_config(
    page_title="AiChemy",
    page_icon="⚗️",
    layout="wide",
    initial_sidebar_state="expanded"
)
# st.logo("logo.svg", size="large", link=None)

# ============================================================================
# Custom CSS
# ============================================================================

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background-color: #f5f5f5; }
    [data-testid="stSidebar"] { background-color: white; }
    .block-container { 
        padding-top: 2rem !important; 
        padding-left: 1rem; 
        padding-right: 1rem;
        max-width: 100% !important;
    }
    
    .stButton > button {
        border-radius: 20px;
    }
    .stButton > button[kind="primary"] {
        background-color: #4a9d7c !important;
        border: none !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #3d8a6a !important;
    }
    
    /* Custom scrollbar for chat history container */
    [data-testid="stVerticalBlock"] > div:has(> div > div[data-testid="stChatMessage"]) {
        overflow-y: auto !important;
        scrollbar-width: thin;
        scrollbar-color: #4a9d7c #f0f0f0;
    }
    
    /* Webkit browsers (Chrome, Safari, Edge) */
    [data-testid="stVerticalBlock"] > div:has(> div > div[data-testid="stChatMessage"])::-webkit-scrollbar {
        width: 8px;
    }
    
    [data-testid="stVerticalBlock"] > div:has(> div > div[data-testid="stChatMessage"])::-webkit-scrollbar-track {
        background: #f0f0f0;
        border-radius: 4px;
    }
    
    [data-testid="stVerticalBlock"] > div:has(> div > div[data-testid="stChatMessage"])::-webkit-scrollbar-thumb {
        background: #4a9d7c;
        border-radius: 4px;
    }
    
    [data-testid="stVerticalBlock"] > div:has(> div > div[data-testid="stChatMessage"])::-webkit-scrollbar-thumb:hover {
        background: #3d8a6a;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# Data
# ============================================================================
# TODO: retrieve from agent metadata
AGENT_PLAN = [
    {"name": "PubChem agent", "description": "Search for compounds matching query"},
    {"name": "OpenTargets agent", "description": "Retrieve target evidence and associations"},
    {"name": "Hit identification agent", "description": "Rank hits by structural similarity"},
]

EXAMPLE_QUESTIONS = [
    "Get the latest review study on the GI toxicity of danuglipron",
    "What diseases are associated with EGFR",
    "Show me compounds similar to vemurafenib. Display their structures",
    "List all the drugs in the GLP-1 agonists ATC class in DrugBank",
]

# TODO: mock data for agent execution. To parse from response.json()
agents = [
    ("Plan created", "Execution plan ready"),
    ("PubChem agent", "2,143 candidates found"),
    ("OpenTargets agent", "target evidence retrieved"),
    ("VS agent", "clustered 50 diverse hits"),
]

# ============================================================================
# Session State
# ============================================================================
if "user_id" not in st.session_state:
    st.session_state.user_id = user_info.get("user_id")
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent_steps" not in st.session_state:
    st.session_state.agent_steps = []
if "state" not in st.session_state:
    st.session_state.state = "idle"  # idle, awaiting_approval, executing, complete
if "current_query" not in st.session_state:
    st.session_state.current_query = None
if "auto_approve" not in st.session_state:
    st.session_state.auto_approve = True
if "pending_response" not in st.session_state:
    st.session_state.pending_response = None
if "trigger_query" not in st.session_state:
    st.session_state.trigger_query = None

# Add reset button
if st.button("🔄 Reset Chat"):
    st.session_state.thread_id = str(uuid4())
    st.session_state.messages = []
    st.rerun()

# ============================================================================
# Callbacks
# ============================================================================

def on_approve():
    st.session_state.state = "executing"

def on_cancel():
    st.session_state.state = "idle"
    st.session_state.agent_steps = []
    st.session_state.current_query = None

# ============================================================================
# Sidebar
# ============================================================================

with st.sidebar:
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 20px;">
        <div style="width: 32px; height: 32px; background: #4a9d7c; border-radius: 8px; 
                    display: flex; align-items: center; justify-content: center; color: white;">⚗️</div>
        <span style="font-size: 18px; font-weight: 600;">AiChemy</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="background: #e6f4ef; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px;
                border-left: 3px solid #4a9d7c;">
        🧬 <b>Project 1</b>
    </div>
    <div style="padding: 10px 12px; color: #666;">
        🧬 Project 2
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    st.caption("WORKFLOWS")
    st.markdown("🎯 Target identification")
    st.markdown("🎯 Hit identification")
    st.markdown("⚗️ Lead optimization")
    st.markdown("☠️ Safety assessment")


# ============================================================================
# Main Layout
# ============================================================================

col_chat, col_agents = st.columns([3, 1])

# ============================================================================
# Chat Column
# ============================================================================

with col_chat:
    st.markdown("### Project 1")
    st.caption("Sort and manage results")

    # Chat input at the top
    print(st.session_state.state)
    disabled = st.session_state.state not in ["idle", "complete"]

    # Display chat history in a container
    chat_history_container = st.container(height=500)
    with chat_history_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["input"][-1]["role"]):
                st.markdown(msg["input"][-1]["content"])
    
    # Example questions - show only when chat is empty
    if len(st.session_state.messages) == 0:
        st.caption("**Try these example questions:**")
        cols = st.columns(2)
        for idx, question in enumerate(EXAMPLE_QUESTIONS):
            with cols[idx % 2]:
                if st.button(question, key=f"example_{idx}", use_container_width=True):
                    st.session_state.trigger_query = question

    # Check for triggered query from example buttons or chat input
    prompt = st.session_state.trigger_query or st.chat_input(
        "Ask AiChemy anything about your R&D project...", 
        key="chat_input",
        disabled=disabled
    )
    
    if prompt:
        # Clear trigger if it was set
        if st.session_state.trigger_query:
            st.session_state.trigger_query = None
        
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.current_query = prompt
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.current_query = prompt
        # Add query to chat history
        st.session_state.messages.append({
            "input": [{"role": "user", "content": prompt}],
            "custom_inputs": {"thread_id": st.session_state.thread_id},
#            "databricks_options": {"return_trace": True},
        })
        
        with st.spinner("🤖 Thinking..."):
            print(f"Last msg:{st.session_state.messages[-1]}")
            # Query the agent endpoint
            response_json = ask_agent_mlflowclient(
                input_dict=st.session_state.messages[-1], client=client
            )  # returns response.json()
            # pprint(response_json)
            text_contents = extract_text_content(response_json)
            if len(text_contents) > 0:
                # # Join all text contents
                assistant_response = (
                    "\n\n".join(text_contents) if text_contents else ""
                )
            else:
                assistant_response = "No response. Retry or reset the chat."        
            # Store assistant response to display after agent execution
            st.session_state.pending_response = assistant_response
            print(assistant_response)
            
            custom_outputs = response_json.get("custom_outputs", {})

            try:
                tool_call = response_json.get("output", [])[-1].get("name", '').replace("transfer_to_", "")
            except Exception as e:  
                print(e)
                tool_call = None
            if tool_call:
                print(f"Tool call: {tool_call}")

            st.session_state.agent_steps = [
                {"name": "Plan created", "status": "completed", "result": "Execution plan ready"}
            ] + [
                {"name": agent["name"], "status": "pending", "result": agent["description"]}
                for agent in AGENT_PLAN
            ]
            
            if st.session_state.auto_approve:
                st.session_state.state = "executing"
            else:
                st.session_state.state = "awaiting_approval"
        st.rerun()
                
            # if msg.get("has_results"):
            #     st.success(f"Found {len(MOLECULES)} candidates")
                
            #     for mol in MOLECULES:
            #         c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            #         with c1:
            #             img = get_molecule_image(mol["smiles"])
            #             if img:
            #                 if isinstance(img, tuple) and img[0] == "svg":
            #                     st.markdown(img[1], unsafe_allow_html=True)
            #                 elif isinstance(img, bytes):
            #                     st.image(img, width=120)
            #             else:
            #                 st.code(mol["smiles"][:20])
            #         with c2:
            #             st.metric("IC₅₀", f"{mol['ic50']} nM")
            #         with c3:
            #             st.metric("ClogP", mol["clogp"])
            #         with c4:
            #             st.caption(mol["notes"])
                
            #     suggestions = get_suggestions(msg.get("original_query", ""))
            #     st.write("")
            #     st.caption("**Suggested follow-ups:**")
            #     cols = st.columns(len(suggestions))
            #     for idx, (col, suggestion) in enumerate(zip(cols, suggestions)):
            #         with col:
            #             if st.button(suggestion, key=f"s_{msg.get('id', 0)}_{idx}", use_container_width=True):
            #                 st.session_state.trigger_query = suggestion
    
    # Show awaiting approval state
    if st.session_state.state == "awaiting_approval":
        st.write("Please approve or cancel in the right panel →")
    
    # Execute agents
    elif st.session_state.state == "executing":
        # Add assistant message to chat history
        if st.session_state.pending_response:
            st.markdown(st.session_state.pending_response)
            st.session_state.messages.append({
                "input": [{"role": "assistant", "content": st.session_state.pending_response}],
                "custom_inputs": {"thread_id": st.session_state.thread_id},
                # "has_results": True,
                # "original_query": original_query
            })
        st.session_state.state = "complete"
        st.session_state.current_query = None
        st.session_state.pending_response = None
        st.rerun()
    
# ============================================================================
# Agent Activity Column
# ============================================================================

with col_agents:
    st.markdown("#### Agent Plan")
    # Auto-approve checkbox
    st.session_state.auto_approve = st.checkbox("Auto-approve", value=st.session_state.auto_approve)
    st.divider()
    
    if st.session_state.agent_steps:
        for step in st.session_state.agent_steps:
            status = step["status"]
            if status == "completed":
                st.markdown(f"✅ **{step['name']}**")
            elif status == "running":
                st.markdown(f"🔄 **{step['name']}**")
            else:
                st.markdown(f"⏳ **{step['name']}**")
            
            if step.get("result"):
                st.caption(step["result"])

        st.divider()

        # Approve/Cancel - only when awaiting
        if st.session_state.state == "awaiting_approval":
            st.info(f"📋 **Plan created for:** {st.session_state.current_query}")
            st.write("The following agents will be executed:")
            # TODO: parse plan from response.json()
            for agent in AGENT_PLAN:
                st.write(f"• **{agent['name']}** - {agent['description']}")
            st.write("Please approve or cancel in the right panel →")
            c1, c2 = st.columns(2)
            with c1:
                st.button("✓ Approve", type="primary", use_container_width=True, on_click=on_approve)
            with c2:
                st.button("✗ Cancel", use_container_width=True, on_click=on_cancel)

        elif st.session_state.state == "executing":
            progress_placeholder = st.empty()
            
            steps = []
            for name, result in agents:
                steps.append({"name": name, "status": "running", "result": None})
                st.session_state.agent_steps = steps.copy()
                progress_placeholder.write(f"🔄 Running **{name}**...")
#                time.sleep(0.6)  # Allow user to see the progress
                
                steps[-1]["status"] = "completed"
                steps[-1]["result"] = result
                st.session_state.agent_steps = steps.copy()
                progress_placeholder.write(f"✅ **{name}**: {result}")

        elif st.session_state.state == "complete":
            completed = sum(1 for s in st.session_state.agent_steps if s["status"] == "completed")
            st.success(f"{completed} agents completed")
    else:
        st.info("🤖 Enter a query to create a plan")


