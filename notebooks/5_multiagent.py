# Databricks notebook source
# MAGIC %md
# MAGIC # Create multi-agent supervisor
# MAGIC Manages:
# MAGIC 1. Drugbank Genie agent
# MAGIC 2. ZINC Vector Search
# MAGIC 3. PubChem MCP
# MAGIC 4. OpenTargets MCP
# MAGIC 5. get_embedding function

# COMMAND ----------

# MAGIC %pip install -r ../requirements.txt
# MAGIC # %pip install -U databricks-connect # ensure 17+
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# MAGIC %pip freeze > requirements_agent.txt

# COMMAND ----------

# Test that databricks-langchain[memory] was installed
from databricks_ai_bridge.lakebase import AsyncLakebasePool

# COMMAND ----------

import mlflow
from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")

mlflow.langchain.autolog()

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from src.utils import get_SP_credentials

# Enter client_id, client_secret of SP if any or get from WorkspaceClient.secrets
# Do not use dbutils.secrets.get(scope="yen", key="client_secret") which is unsupported in mlflow logging in Driver
# client_id, client_secret = get_SP_credentials(
#     scope='aichemy',
#     client_id_key='client_id', #if retrieving secrets (but doesn't work with mlflow logging)
#     client_secret_key='client_secret', #if retrieving secrets (but doesn't work with mlflow logging)
#     # must provide hardcoded values as mlflow log_model cannot retrieve secrets
#     client_id_value = "client_id", # Hardcode client_id if any
#     client_secret_value = "client_secret" # Hardcode client_secret if any
# )
# ws_client = WorkspaceClient(
#     host=cfg.get("host"),
#     client_id=client_id,
#     client_secret=client_secret
# )
ws_client = WorkspaceClient()

# COMMAND ----------

from databricks_langchain import ChatDatabricks

llm = ChatDatabricks(endpoint=cfg.get("llm_endpoint"))

# COMMAND ----------

from databricks_langchain.uc_ai import UCFunctionToolkit
from langchain.agents import create_agent

uc_functions = cfg.get("uc_functions")
python_tools = UCFunctionToolkit(function_names=uc_functions).tools
python_prompt = "You are a python function that can generate ECFP molecular fingerprint embeddings from SMILES and display molecule PNG images from the PubChem website by CID in markdown."
util_agent = create_agent(
    llm, tools=python_tools, system_prompt=python_prompt, name="chem_utils"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Collect tools to display in Apps

# COMMAND ----------

# tools = []
# chem_tool_data = [('Chem Utils', i.name.split("__")[-1], i.description) for i in python_tools]
# n_chem_tool_data = len(chem_tool_data)
# tools.extend(chem_tool_data)
# [i for i in tools]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create text-to-SQL Genie agent to chat with Drugbank

# COMMAND ----------

from databricks_langchain.genie import GenieAgent

# Get you Genie space ID from the URL 
# https://workspace_host/genie/rooms/<genie_id>/chats/...
genie_space_id = cfg.get("genie_space_id")
drugbank_agent = GenieAgent(genie_space_id, genie_agent_name="drugbank")

# COMMAND ----------

# tools.append(('DrugBank', drugbank_agent.name, drugbank_agent.description))
# tools

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create retriever agent
# MAGIC To do similarity search on ZINC vector store based on ECFP4 molecular fingerprint embeddings

# COMMAND ----------

from databricks_langchain import VectorSearchRetrieverTool
from databricks_langchain import DatabricksEmbeddings
from langchain.tools import tool

# VectorSearchRetrieverTool requires embedding and text_column be specified but they are not used as the similarity_search_by_vector method is used
embedding_model = DatabricksEmbeddings(
    endpoint="databricks-bge-large-en",
)
zinc_description = "Search for chemicals in ZINC using molecular fingerprints"

retriever_tool = VectorSearchRetrieverTool(
    index_name=cfg.get("retriever")["vs_index"],
    num_results=cfg.get("retriever")["k"],
    columns=[
        "zinc_id",
        "smiles",
        "mwt",
        "logp",
        "purchasable"
    ],
    text_column = "smiles",
    tool_name=cfg.get("retriever")["tool_name"],
    tool_description=zinc_description,
    embedding = embedding_model
)
@tool
def tool_vectorinput(bitstring: str):
    """
    Search for similar molecules based on their ECFP4 molecular fingerprints embedding vector (list of int). Required input (bitstring) is a 1024-char bitstring (e.g. 1011..00) which is the concatenated string form of a list of 1024 integers (e.g. [1,0,1,1,...,0,0]).
    """
    # Use a bitstring so that each list element is not counted as a token
    query_vector = [int(i) for i in list(bitstring)]
    docs = retriever_tool._vector_store.similarity_search_by_vector(
        query_vector, k=cfg.get("retriever")["k"]
    )
    return [doc.metadata | {"smiles": doc.page_content} for doc in docs]
retriever_prompt = "Search for drug-like chemicals in the ZINC database based on ECFP molecular fingerprint embeddings"
zinc_agent = create_agent(
    llm, tools=[tool_vectorinput], system_prompt=retriever_prompt, name="zinc"
)

# COMMAND ----------

# tools.append(("ZINC", zinc_description))
# tools

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the external MCP agents

# COMMAND ----------

from databricks_langchain import DatabricksMultiServerMCPClient, DatabricksMCPServer, MCPServer

mcp_client = DatabricksMultiServerMCPClient(
    [
        DatabricksMCPServer(
            name="pubchem",
            url=f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("pubchem")}',
            workspace_client=ws_client,
            timeout=60,
            terminate_on_close=False
        ),
        DatabricksMCPServer(
            name="pubmed",
            url=f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("pubmed")}',
            workspace_client=ws_client,
            terminate_on_close=False
        ),
        DatabricksMCPServer(
            name="opentargets",
            url=f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("opentargets")}',
            workspace_client=ws_client
        ),
    ]
)

# COMMAND ----------

import asyncio
import nest_asyncio
nest_asyncio.apply()

def get_tools(mcp_client: DatabricksMultiServerMCPClient):
    async def aget_tools():
        await mcp_client.get_tools()
    return asyncio.run(aget_tools())
mcp_tools = get_tools(mcp_client)
mcp_prompt = """You are a multi-MCP server agent connected to:
1. PubChem MCP server that provides everything about chemical compounds
2. PubMed MCP server that searches biomedical literature and retrieves free full text if any. 
3. OpenTargets MCP server that provides everything about drug targets and their associations with diseases and drugs.
Most PubChem tools (e.g. get_compound_info) except for search_compounds expect a CID."""
mcp_agent = create_agent(
    llm, tools=mcp_tools, system_prompt=mcp_prompt, name="mcp"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write tools.txt for the App

# COMMAND ----------

# import pandas as pd

# mcp_tools_list = await mcp_client.get_tools()
# names = ["PubChem"] * 29 + ["PubMed"] * 12 + ["OpenTargets"] * 5
# tools.extend([(i, j.name, j.description.split("\n")[0]) for i,j in zip(names, mcp_tools_list)])
# pd.DataFrame(tools, columns=["Agent", "Tool", "Description"]).to_csv("../apps/app/tools.txt", sep="\t", index=False)

# COMMAND ----------

# # 42 sec when using MultiServerMCPClient vs 1.88 min databricks-mcp
# input_example = {
#     "messages": [
#         {
#             "role": "user",
#             "content": "What is the cid of aspirin?"
#         }
#     ]
# }
# await mcp_agent.ainvoke(input_example)

# COMMAND ----------

# DBTITLE 1,Cell 25
from langgraph_supervisor import create_supervisor

supervisor_prompt = """You are a supervisor managing 4 agents. Route according to the agent required to fulfill the request.
1. Drugbank agent: generates text-to-SQL queries to Drugbank of FDA-approved drugs and their properties
2. ZINC agent: searches for drug-like molecules and their properties from the ZINC database based on ECFP4 molecular fingerprint embeddings represented as a 1024-char bitstring.
3. Chem utilities agent: display molecule image PNG files from PubChem website by CID in markdown or compute ECFP4 molecular fingerprint embeddings in a 1024-char bitstring for a given SMILES structure. If missing SMILES input, query it from a chemical name using the PubChem MCP agent's search_compound tool.
4. MCP agent: connects to the PubChem, PubMed and OpenTargets MCP servers

Because you are an autonomous multi-agent system, do not ask for more follow up information. Instead, use chain-of-thought to reason and break down the request into
achievable steps based on the agentic tools that you have access to. 
"""

workflow = create_supervisor(
    [drugbank_agent, zinc_agent, util_agent, mcp_agent],
    model=llm,
    prompt=supervisor_prompt,
    output_mode="last_message",
    add_handoff_messages=False,
    forward_messages=True,
    parallel_tool_calls=True
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test inferencing unwrapped agent (langchain)
# MAGIC Only async works

# COMMAND ----------

#qstring = "Show the aspirin molecule. First get its CID, then get the PubChem image URL based on the CID."
#workflow.compile().invoke({"messages": [{"role": "user", "content": qstring}]})

# COMMAND ----------

# await workflow.compile().ainvoke({"messages": [{"role": "user", "content": qstring}]})

# COMMAND ----------

# async for chunk in workflow.compile().astream({"messages": [{"role": "user", "content": qstring}]}):
#     print(chunk, flush=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Add memory using Lakebase Postgres backend
# MAGIC Use `databricks_langchain.CheckpointSaver` wrapped around `langchain.PostgresSaver` for easy authentication and connection pools.<br>
# MAGIC Remember to make your SP used in the WorkspaceClient a superuser with CreateDB permissions

# COMMAND ----------

from src.responses_agent import WrappedAgent

agent = WrappedAgent(workflow=workflow, workspace_client=ws_client, lakebase_instance=cfg.get("lakebase_agent").get("instance_name"))
mlflow.models.set_model(agent)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test inferencing wrapped agent (`ResponsesAgent`)

# COMMAND ----------

# from uuid import uuid4
# import nest_asyncio
# nest_asyncio.apply()

# thread_id = str(uuid4())
# inputs = {
#     "input": [{"role": "user", "content": "What is the ENSEMBL ID of GLP-1"}], 
#     "custom_inputs": {"thread_id": thread_id}
# }
# response1 = agent.predict(inputs)
# response1

# COMMAND ----------

# thread_id = str(uuid4())
# inputs = {
#     "input": [{"role": "user", "content": "What is the CID of aspirin?"}], 
#     "custom_inputs": {"thread_id": thread_id}
# }
# response1 = agent.predict(inputs)

# COMMAND ----------

# inputs = {
#     "input": [{"role": "user", "content": "Show me its molecular structure?"}], 
#     "custom_inputs": {"thread_id": thread_id}
# }
# response2 = agent.predict(inputs)

# COMMAND ----------


