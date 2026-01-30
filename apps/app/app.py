import logging
import streamlit as st
from mlflow.deployments import get_deploy_client
from utils import get_user_info, ask_agent_mlflowclient, extract_text_content, parse_tool_calls, strip_tool_call_tags, parse_genie_results
from uuid import uuid4
from pprint import pformat
import time
from io import BytesIO
import pandas as pd
import sys
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# w = WorkspaceClient()
client = get_deploy_client("databricks")
user_info = get_user_info()

# Add project root to sys.path using absolute path
project_root = Path(__file__).resolve().parent.parent.parent
app_root = Path(__file__).resolve().parent
sys.path.insert(0, str(app_root))
sys.path.insert(0, str(project_root))
print(f"sys.path: {sys.path}")

# ============================================================================
# Page Config
# ============================================================================

st.set_page_config(page_title="AiChemy", page_icon="⚗️", layout="wide", initial_sidebar_state="expanded")

# ============================================================================
# Custom CSS
# ============================================================================

st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)

# ============================================================================
# Data
# ============================================================================
EXAMPLE_QUESTIONS = [
    "Get the latest review study on the GI toxicity of danuglipron",
    "What diseases are associated with EGFR",
    "Show me compounds similar to vemurafenib. Display their structures",
    "List all the drugs in the GLP-1 agonists ATC class in DrugBank",
]

WORKFLOWS = [
    "🧬 Target identification", 
    "⌬ Hit identification", 
    "🧪 Lead optimization", 
    "☠️ Safety assessment"
]

workflow_captions = [
    "Based on a disease, get its associated targets", 
    "Based on a target, get its associated drugs", 
    "Based on a compound, get its properties", 
    "Based on a compound, get its safety info"
]

compound_info_options = [
    "Structure: SMILES, InChI, MW...",
    "ADME: LogP, Druglikeness, CYP3A4...",
    "Bioactivity: IC50...",
    "All"
]

AGENT_PLAN = [
    {"name": "PubChem agent", "description": "Search for compounds matching query"},
    {"name": "OpenTargets agent", "description": "Retrieve target evidence and associations"},
    {"name": "Hit identification agent", "description": "Rank hits by structural similarity"},
]

# TODO: mock data for agent execution. To parse from response.json()
agents = [
    ("Plan created", "Execution plan ready"),
    ("PubChem agent", "2,143 candidates found"),
    ("OpenTargets agent", "target evidence retrieved"),
    ("VS agent", "clustered 50 diverse hits"),
]

# Load tools from tab-delimited file
df_tools = pd.read_csv(f"{app_root}/tools.txt", sep="\t")
TOOLS = list(df_tools.itertuples(index=False, name=None))

# ============================================================================
# Session State
# ============================================================================
if "user_id" not in st.session_state:
    st.session_state.user_id = user_info.get("user_id")
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "tool_calls" not in st.session_state:
    st.session_state.tool_calls = []
if "genie" not in st.session_state:
    st.session_state.genie = []
if "workflow" not in st.session_state:
    st.session_state.workflow = None
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False
if "last_processed_input" not in st.session_state:
    st.session_state.last_processed_input = None
if "stop" not in st.session_state:
    st.session_state.stop = False
if "prompts_w_tools" not in st.session_state:
    st.session_state.prompts_w_tools = []
if "prompts_w_genie" not in st.session_state:
    st.session_state.prompts_w_genie = []
if "workflow_input" not in st.session_state:
    st.session_state.workflow_input = None

def clear_workflow():
    st.session_state.workflow = None
    st.session_state.workflow_input = None


def stop_processing():
    # Handle the case where stop was requested
    if st.session_state.stop and st.session_state.is_processing:
        # Remove the user message we just added since we're cancelling
        if len(st.session_state.messages) > 0 and st.session_state.messages[-1]["input"][-1]["role"] == "user":
            st.session_state.messages.pop()
        st.session_state.last_processed_input = None
        st.session_state.is_processing = False
        st.session_state.workflow = None
        st.warning("⚠️ Query cancelled by user.")
        
# ============================================================================
# Sidebar
# ============================================================================

with st.sidebar:
    st.logo(f"{app_root}/logo.svg", size="large", link=None)
    st.markdown(
        """
    <div style="background: #e6f4ef; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px;
                border-left: 3px solid #4a9d7c;">
        🧬 <b>Project 1</b>
    </div>
    <div style="padding: 10px 12px; color: #666;">
        🧬 Project 2
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.divider()

    # Workflow selector
    st.markdown("**Guided workflows**")
    st.session_state.workflow = st.radio(
        "", WORKFLOWS, index=None, captions=workflow_captions, label_visibility="collapsed"
    )

    st.divider()

    # Available tools 
    st.markdown("**Available tools**")
    opentargets_expander = st.expander("🎯OpenTargets MCP", expanded=False)
    pubchem_expander = st.expander("🧪 PubChem MCP", expanded=False)        
    utils_expander = st.expander("🛠️ Chem Utilities", expanded=False)
    pubmed_expander = st.expander("📚 PubMed MCP", expanded=False)
    drugbank_expander = st.expander("💊 DrugBank Genie", expanded=False)
    drugbank_expander.caption("text-to-SQL of DrugBank")
    zinc_expander = st.expander("🔬 ZINC Vector Search", expanded=False)
    zinc_expander.caption("similarity search")

    for tool in TOOLS:
        if tool[0] == "OpenTargets":
            opentargets_expander.caption(tool[1])
        elif tool[0] == "PubChem":
            pubchem_expander.caption(tool[1])
        elif tool[0] == "Chem Utils":
            utils_expander.caption(tool[1])
        elif tool[0] == "PubMed":
            pubmed_expander.caption(tool[1])
        elif tool[0] == "DrugBank":
            drugbank_expander.caption(tool[1])
        elif tool[0] == "ZINC":
            zinc_expander.caption(tool[1])

# ============================================================================
# Main Layout
# ============================================================================

col_chat, col_agents = st.columns([3, 1])

# ============================================================================
# Chat Column
# ============================================================================

with col_chat:
    # Display chat history in a container
    chat_history_container = st.container(height=500)
    with chat_history_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["input"][-1]["role"]):
                st.markdown(msg["input"][-1]["content"])

    # Reset prompt and input key
    prompt = None
    input_key = None  # Track which input generated the prompt

    # Chat input with reset button
    input_col, reset_col = st.columns([7, 1])
    with input_col:
        if prompt := st.chat_input("Ask AiChemy anything...", key="chat_input", on_submit=clear_workflow):
            input_key = f"chat:{prompt}"
    with reset_col:
        if st.button("Reset", key="reset", icon=":material/replay:"):
            st.session_state.thread_id = str(uuid4())
            st.session_state.messages = []
            st.session_state.tool_calls = []
            st.session_state.genie = []
            st.session_state.workflow = None
            st.session_state.is_processing = False
            st.session_state.last_processed_input = None            
            st.session_state.stop = False
            st.session_state.prompts_w_tools = []
            st.session_state.prompts_w_genie = [] 
            st.rerun()

    if st.session_state.workflow == WORKFLOWS[0]:
        # Show text input for disease of interest
        col1, col2 = st.columns([7, 1])
        with col1:
            if disease_input := st.text_input(
                "Enter the disease of interest", key="workflow_input", placeholder="e.g., breast cancer, Alzheimer's disease"
            ):
                input_key = f"disease:{disease_input}"
                prompt = f"Use OpenTargets to find targets associated with {st.session_state.workflow_input}. Show their scores if any and rank in descending order of scores."

        with col2:# Align with input
            st.button("Clear", key="clear_disease", icon=":material/clear:", on_click=clear_workflow)


    elif st.session_state.workflow == WORKFLOWS[1]:
        # Show text input for target of interest
        col1, col2 = st.columns([7, 1])
        with col1:
            if target_input := st.text_input("Enter the target of interest", key="workflow_input", placeholder="e.g., BRCA1, GLP-1"):
                input_key = f"target:{target_input}"
                prompt = f"Use OpenTargets to find drugs associated with {st.session_state.workflow_input}. Show their scores if any and rank in descending order of scores."
        with col2:
            st.button("Clear", key="clear_target", icon=":material/clear:", on_click=clear_workflow)


    elif st.session_state.workflow == WORKFLOWS[2]:
        # Show text input for compound of interest
        col1, col2 = st.columns([5, 1])
        with col1:
            if compound_input := st.text_input(
                "Enter the compound of interest", key="workflow_input", placeholder="e.g., acetaminophen, semaglutide, CHEMBL25"
            ):
                input_key = f"compound:{compound_input}"
                # Show pills for compound properties selection
                if compound_info := st.pills(
                    label="What do you want to know about this compound?",
                    options=compound_info_options,
                    selection_mode="multi",
                ):
                    properties_str = ", ".join(compound_info)
                    input_key = f"{input_key}:{properties_str}"
                    prompt = f"Use PubChem to get {properties_str} properties of {st.session_state.workflow_input}."
        with col2:
            st.button("Clear", key="clear_compound", icon=":material/clear:", on_click=clear_workflow)

    elif st.session_state.workflow == WORKFLOWS[3]:
        # Show text input for target of interest
        col1, col2 = st.columns([7, 1])
        with col1:
            if compound_input := st.text_input("Enter the compound of interest", key="workflow_input", placeholder="e.g., BRCA1, GLP-1"):
                input_key = f"compound:{compound_input}:safety"
                prompt = f"Use PubChem and PubMed to find safety profile of {st.session_state.workflow_input}. If citing studies, please state the strength of the evidence based on the study design."
        with col2:
            st.button("Clear", key="clear_target", icon=":material/clear:", on_click=clear_workflow)
        
    else:
        # Example questions - show only when chat is empty
        if len(st.session_state.messages) == 0:
            st.caption("**Try these example questions:**")
            selected_question = st.pills(
                "example_pills", EXAMPLE_QUESTIONS, selection_mode="single", label_visibility="collapsed", default=None
            )

            if selected_question:
                input_key = f"example:{selected_question}"
                prompt = selected_question

    # Only process if we have a new input (not already processed) and not stopped
    if prompt and input_key != st.session_state.last_processed_input and not st.session_state.stop:
        # Mark this input as processed
        st.session_state.last_processed_input = input_key
        with st.chat_message("user"):
            st.markdown(prompt)

        input_dict = {
            "input": [{"role": "user", "content": prompt}],
            "custom_inputs": {"thread_id": st.session_state.thread_id},
            "databricks_options": {"return_trace": True}
        }

        # Append query to messages
        st.session_state.messages.append(input_dict)
        print(f"Last msg:{pformat(input_dict, width=120)}")
    
        # Check if we need to actually make the API call
        # (last message should be a user message without a corresponding assistant response)
        if len(st.session_state.messages) > 0 and st.session_state.messages[-1]["input"][-1]["role"] == "user":
            with st.status("🤖 Thinking...", expanded=True) as status:
                st.session_state.is_processing = True
                # Add stop button inside the status widget
                st.button("Stop", type="primary", key="stop", icon=":material/stop_circle:", on_click=stop_processing)
                
                if st.session_state.is_processing and not st.session_state.stop:
                    # Query the agent endpoint
                    response_json = ask_agent_mlflowclient(
                        input_dict, client=client
                    )  # returns response.json()
                    # Write response to file
                    # with open("response_json.txt", "w") as f:
                    #     f.write(pformat(response_json, width=120))
                    text_contents = extract_text_content(response_json)
                    genie_results = parse_genie_results(response_json)
                    if len(text_contents) > 0:
                        # Parse tool calls from the text content
                        all_tool_calls = []
                        cleaned_texts = []
                        # agent keeps appending according to thread_id so just get the last one
                        response_list = [text_contents[-1]]
                        for text_content in response_list:
                            tool_calls = parse_tool_calls(text_content)
                            all_tool_calls.extend(tool_calls)
                            # Strip tool call tags from the text
                            cleaned_text = strip_tool_call_tags(text_content)
                            if cleaned_text:  # Only add non-empty cleaned text
                                cleaned_texts.append(cleaned_text)
                        if len(all_tool_calls) > 0:
                            st.session_state.tool_calls.append(all_tool_calls)
                            st.session_state.prompts_w_tools.append(prompt)
                        if len(genie_results) > 0:
                            st.session_state.genie.append(genie_results)
                            st.session_state.prompts_w_genie.append(prompt)
                        # Join cleaned text contents
                        assistant_response = "\n\n".join(cleaned_texts) if cleaned_texts else ""
                    else:
                        assistant_response = "No response. Retry or reset the chat."
                    # print(assistant_response)
                    # Append answer to messages
                    st.session_state.messages.append(
                        {
                            "input": [{"role": "assistant", "content": assistant_response}],
                            "custom_inputs": {"thread_id": st.session_state.thread_id},
                            # "has_results": True,
                            # "original_query": original_query
                        }
                    )
                    
                    status.update(label="✅ Complete!", state="complete", expanded=False)

            st.session_state.is_processing = False
            st.session_state.workflow = None
            st.rerun()

# ============================================================================
# Agent Activity Column
# ============================================================================

with col_agents:
    st.markdown("#### Agent Activity")
    st.divider()

    # Display tool calls in expanders
    if st.session_state.tool_calls:
        reversed_prompts = list(reversed(st.session_state.prompts_w_tools))
        for j, tool_group in enumerate(reversed(st.session_state.tool_calls)):
            st.markdown(f"**Tools calls:** _{reversed_prompts[j][:80]}..._")
            for idx, tool_call in enumerate(tool_group):
                # Create badge for function name
                with st.expander(rf":green[{idx+1}. 🔧{tool_call['function_name']}]", expanded=False):
                    # Display parameters as captions
                    if tool_call["parameters"]:
                        for param_name, param_value in tool_call["parameters"].items():
                            st.caption(f"**{param_name}:** {param_value}")

                    # Display thinking
                    if tool_call["thinking"]:
                        st.info(tool_call["thinking"])
            st.divider()

    if st.session_state.genie:
        reversed_prompts_genie = list(reversed(st.session_state.prompts_w_genie))
        for p, genie_group in enumerate(reversed(st.session_state.genie)):
            for k, g in enumerate(genie_group):
                with st.expander(rf":green[**SQL:**] _{reversed_prompts_genie[p][:80]}..._", expanded=False):
                    # Display parameters as captions
                    st.caption(g['description'])
                    st.code(g['query'], wrap_lines=True)
            st.divider()
