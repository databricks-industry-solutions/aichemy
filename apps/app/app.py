import os
import logging
import streamlit as st
from mlflow.deployments import get_deploy_client
from utils import get_user_info, ask_agent_mlflowclient, extract_text_content
from uuid import uuid4
from pprint import pprint

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# w = WorkspaceClient()
client = get_deploy_client("databricks")
user_info = get_user_info()

st.set_page_config(page_title="AiChemy", layout="wide")
st.logo("logo.svg", size="large", link=None)

# Streamlit app
if "visibility" not in st.session_state:
    st.session_state.visibility = "visible"
    st.session_state.disabled = False

# Initialize chat history
if "user_id" not in st.session_state:
    st.session_state.user_id = user_info.get("user_id")
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

# Add reset button
if st.button("🔄 Reset Chat"):
    st.session_state.thread_id = str(uuid4())
    st.session_state.messages = []
    st.rerun()

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["input"][-1]["role"]):
        st.markdown(message["input"][-1]["content"])

# Accept user input
if prompt := st.chat_input("Example: What is ozempic and its molecular weight?"):
    # Add user message to chat history
    st.session_state.messages.append({
            "input": [{"role": "user", "content": prompt}],
            "custom_inputs": {"thread_id": st.session_state.thread_id},
#            "databricks_options": {"return_trace": True},
    })
    
    # If using requests, input_dict is expected
    # If using mlflow client, messages_dict is expected
    # just swap input key for messages key
    # for i in st.session_state.messages:
    #     i["messages"] = i.pop("input")
    #     i.pop("custom_inputs")

    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        # Query the Databricks serving endpoint
        # print(f"Last msg:{st.session_state.messages[-1]}")
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
        print(assistant_response)
        st.markdown(assistant_response)

        custom_outputs = response_json.get("custom_outputs", {})

        try:
            tool_call = response_json.get("output", [])[-1].get("name", '').replace("transfer_to_", "")
        except Exception as e:  
            print(e)
            tool_call = None
        if tool_call:
            st.markdown(tool_call)
        
        # Add assistant message to chat history
        st.session_state.messages.append({
            "input": [{"role": "assistant", "content": assistant_response if len(text_contents) > 0 else None}],
            "custom_inputs": {"thread_id": st.session_state.thread_id},
#            "databricks_options": {"return_trace": True}
        })
