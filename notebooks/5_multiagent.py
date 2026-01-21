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
# MAGIC %pip install rdkit
# MAGIC # %pip install -U databricks-connect # ensure 17+
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# MAGIC %pip freeze > requirements_agent.txt

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
client_id, client_secret = get_SP_credentials(
    scope='aichemy',
    client_id_key='client_id', #if retrieving secrets (but doesn't work with mlflow logging)
    client_secret_key='client_secret', #if retrieving secrets (but doesn't work with mlflow logging)
    # must provide hardcoded values as mlflow log_model cannot retrieve secrets
    client_id_value = "dbb08096-2fd5-4668-bf95-aba8b7609d93", # Hardcode client_id if any
    client_secret_value = "dosefb6c52dc36508a93f088740fcf4c8f49" # Hardcode client_secret if any
)
ws_client = WorkspaceClient(
    host=cfg.get("host"),
    client_id=client_id,
    client_secret=client_secret
)

# COMMAND ----------

from databricks_langchain import ChatDatabricks

llm = ChatDatabricks(endpoint=cfg.get("llm_endpoint"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create `get_embedding` function
# MAGIC To compute molecular fingerprint embeddings for searching ZINC vector store

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION aichemy2_catalog.aichemy.get_embedding(smiles STRING)
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the ECFP molecular fingerprint from SMILES'
# MAGIC LANGUAGE PYTHON
# MAGIC ENVIRONMENT (
# MAGIC   dependencies = '["rdkit"]',
# MAGIC   environment_version = 'None'
# MAGIC )
# MAGIC AS $$
# MAGIC from rdkit.Chem import MolFromSmiles
# MAGIC from rdkit.Chem.AllChem import GetMorganGenerator
# MAGIC fpgen = GetMorganGenerator(radius=2, fpSize=1024)
# MAGIC mol = MolFromSmiles(smiles)
# MAGIC vector = fpgen.GetFingerprintAsNumPy(mol)
# MAGIC bitstring = "".join([str(i) for i in vector])
# MAGIC return bitstring
# MAGIC $$;

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION aichemy2_catalog.aichemy.molecule_png_url(CID INTEGER)
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the molecule image url of a CID from PubChem'
# MAGIC LANGUAGE PYTHON
# MAGIC AS $$
# MAGIC url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{str(cid)}/png"
# MAGIC return url
# MAGIC $$;

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
# MAGIC ## Create text-to-SQL Genie agent to chat with Drugbank

# COMMAND ----------

from databricks_langchain.genie import GenieAgent

# Get you Genie space ID from the URL 
# https://workspace_host/genie/rooms/<genie_id>/chats/...
genie_space_id = cfg.get("genie_space_id")
drugbank_agent = GenieAgent(genie_space_id, genie_agent_name="drugbank")

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
    tool_description="Search for chemicals in ZINC using molecular fingerprints",
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

# MAGIC %md
# MAGIC ## Create the external MCP agents

# COMMAND ----------

import asyncio
from src.mcp_utils import create_mcp_tools

server_url = f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("pubchem")}'
pubchem_tools = asyncio.run(
    create_mcp_tools(
        ws=ws_client,
        managed_server_urls=[server_url],
        custom_server_urls=None
    )
)
pubchem_prompt = 'You are a helpful agent connected to an external Pubchem MCP server that provides everything about chemical compounds. Most tools (e.g. get_compound_info) expect a CID. The get_compound_properties tool expects an array argument listing the required properties (e.g. ["XlogP", "MolecularWeight"])'
pubchem_agent = create_agent(
    llm, tools=pubchem_tools, system_prompt=pubchem_prompt, name="pubchem_mcp"
)

# COMMAND ----------

import asyncio
from src.mcp_utils import create_mcp_tools

server_url = f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("pubmed")}'
pubmed_tools = asyncio.run(
    create_mcp_tools(
        ws=ws_client,
        managed_server_urls=[server_url],
        custom_server_urls=None
    )
)
pubmed_prompt = 'You are a helpful agent connected to an external PubMed MCP server with the pubmed_articles tool that can search the biomedical literature (search_pubmed), get their metadata (get_article_metadata method) and download pdfs (get_paper_fulltext).'
pubmed_agent = create_agent(
    llm, tools=pubmed_tools, system_prompt=pubmed_prompt, name="pubmed_mcp"
)

# COMMAND ----------

server_url = f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("opentargets")}'
opentargets_tools = asyncio.run(
    create_mcp_tools(
        ws=ws_client,
        managed_server_urls=[server_url],
        custom_server_urls=None
    )
)
opentargets_prompt = 'You are a helpful agent connected to an external OpenTargets MCP server that provides everything about drug targets and their associations with diseases and drugs.'
opentargets_agent = create_agent(
    llm, tools=opentargets_tools, system_prompt=opentargets_prompt, name="opentargets_mcp"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Add memory using Lakebase Postgres backend

# COMMAND ----------

from langgraph_supervisor import create_supervisor

supervisor_prompt = """You are a supervisor managing several agents:
1. Drugbank agent: generates text-to-SQL queries to Drugbank of FDA-approved drugs and their properties
2. ZINC agent: searches for drug-like molecules and their properties from the ZINC database based on ECFP4 molecular fingerprint embeddings represented as a 1024-char bitstring.
3. Chem utilities agent: display molecule image PNG files from PubChem website by CID in markdown or compute ECFP4 molecular fingerprint embeddings in a 1024-char bitstring for a given SMILES structure. If missing SMILES input, query it from a chemical name using the PubChem MCP agent's search_compound tool.
4. PubChem MCP: looks up chemical compounds and their properties including CID, SMILES structures, descriptors and ADMET from the PubChem MCP server. Do not use Pubchem MCP to compute fingerprints or embeddings or use calculate_descriptors tool.
5. PubMed MCP: looks up or download biomedical articles on PubMed by keywords, metadata or PMID.
6. OpenTargets MCP: looks up drug-target-disease associations in the OpenTargets MCP server to assist in drug discovery research.

Because you are an autonomous multi-agent system, do not ask for more follow up information. Instead, use chain-of-thought to reason and break down the request into
achievable steps based on the agentic tools that you have access to. For example, a common workflow is to get the CID from a compound name (search_compound), then use the CID to look up chemical properties (get_compound_info or get_compound_properties). A similar workflow exists for drug targets based on looking up the target name for its target ID (search_targets) and then using the target ID for target information (get_target_details) or disease- or drug- associations. Another common workflow is to look up SMILES from a compound name using Pubchem's search_compounds tool, then use the SMILES to compute ECFP embeddings (get_embedding). In such a case, do not use PubChem to directly compute ECFP or other fingerprint embeddings.
"""

workflow = create_supervisor(
    [drugbank_agent, zinc_agent, util_agent, pubchem_agent, pubmed_agent, opentargets_agent],
    model=llm,
    prompt=supervisor_prompt,
    output_mode="last_message",
)

# COMMAND ----------

from langgraph.checkpoint.postgres import PostgresSaver
from src.lakebase import LakebaseConnect

dbClient = LakebaseConnect(
    user = client_id,
    password = None, # leave None to generate ephemeral token (1h)
    instance_name = cfg.get("lakebase").get("instance_name"), 
    database = cfg.get("lakebase").get("database"),
    wsClient = ws_client
)

# COMMAND ----------

dbClient.test_query() # connects and closes pool too

# COMMAND ----------

dbClient._connect()
checkpointer = PostgresSaver(dbClient.connection_pool)
# checkpointer.setup() # if setting up for the first time (ensure that your SP has create table permissions)
full_agent = workflow.compile(checkpointer=checkpointer)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test inferencing unwrapped agent (langchain)

# COMMAND ----------

# Keep commented for fast mlflow logging in driver
# Test invoking unwrapped langgraph
# from uuid import uuid4

# input_example = {
#     "messages": [
#         {
#             "role": "user",
#             "content": "What is the mw of danuglipron?"
#         }
#     ]
# }
# thread_id = str(uuid4())
# config = {"configurable": {"thread_id": thread_id}}
# response = full_agent.invoke(input_example, config=config)

# COMMAND ----------

# input_example = {
#     "messages": [
#         {
#             "role": "user",
#             "content": "What is the latest review article on danuglipron?"
#         }
#     ]
# }
# thread_id = str(uuid4())
# config = {"configurable": {"thread_id": thread_id}}
# response = full_agent.invoke(input_example, config=config)

# COMMAND ----------

# Keep commented for fast mlflow logging in driver
# import pandas as pd

# dbClient._connect()
# data = dbClient.query("SELECT * FROM checkpoints")
# dbClient.close()
# display(pd.DataFrame(data).tail())

# COMMAND ----------

from src.responses_agent import WrappedAgent

dbClient._connect()
conninfo = dbClient.conninfo
agent = WrappedAgent(workflow, conninfo)

# COMMAND ----------

mlflow.models.set_model(agent)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test inferencing wrapped agent (`ResponsesAgent`)

# COMMAND ----------

# from uuid import uuid4

# thread_id = str(uuid4())
# response1 = agent.predict({
#     "input": [{"role": "user", "content": "Show the aspirin molecule. First get its CID from PubChem then get the molecule_png_url then display in markdown"}], 
#     "custom_inputs": {"thread_id": thread_id, "recursion_limit": 20}
#     })

# COMMAND ----------

# response1 = agent.predict({
#     "input": [{"role": "user", "content": "Summarize the latest articles on the use of aspirin in the treatment of covid"}], 
#     "custom_inputs": {"thread_id": thread_id}
#     })
