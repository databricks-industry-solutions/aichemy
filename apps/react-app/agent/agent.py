"""
LangGraph agent definition for the AgentServer.

Builds the multi-agent supervisor workflow and registers it with mlflow.genai.agent_server's
@invoke and @stream decorators so AgentServer can serve it at /invocations.

The agent is built in a background thread at import time to avoid blocking the server startup.
Requests wait on a threading.Event until the agent is ready.
"""

import asyncio
import logging
import sys
import threading
from pathlib import Path
from typing import AsyncGenerator
import nest_asyncio

import yaml

# Make src/ importable (project structure: apps/app/ → apps/ → project_root/)
_app_root = Path(__file__).resolve().parent.parent
_project_root = _app_root.parent.parent
sys.path.insert(0, str(_project_root))

from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent  # noqa: F401

logger = logging.getLogger(__name__)

nest_asyncio.apply()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

with open(_project_root / "notebooks" / "config.yml") as _f:
    _cfg = yaml.safe_load(_f)

# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

_agent = None
_agent_ready = threading.Event()

def _build_agent():
    """Instantiate the full multi-agent supervisor workflow and return a WrappedAgent."""
    import nest_asyncio

    nest_asyncio.apply()

    from databricks.sdk import WorkspaceClient
    from databricks_langchain import ChatDatabricks, DatabricksEmbeddings
    from databricks_langchain import DatabricksMultiServerMCPClient, DatabricksMCPServer, MCPServer
    from databricks_langchain import VectorSearchRetrieverTool
    from databricks_langchain.genie import GenieAgent
    from databricks_langchain.uc_ai import UCFunctionToolkit
    from langchain.agents import create_agent
    from langchain.tools import tool
    from langgraph_supervisor import create_supervisor

    from src.responses_agent_new import WrappedAgent
    from src.utils import get_SP_credentials

    client_id, client_secret = get_SP_credentials(
        scope='aichemy',
        client_id_key='client_id', #if retrieving secrets (but doesn't work with mlflow logging)
        client_secret_key='client_secret', #if retrieving secrets (but doesn't work with mlflow logging)
    )
    ws_client = WorkspaceClient(
        host=_cfg["host"],
        client_id=client_id,
        client_secret=client_secret
    )

    llm = ChatDatabricks(endpoint=_cfg["llm_endpoint"])

    # --- Chem utilities agent ---
    python_tools = UCFunctionToolkit(function_names=_cfg["uc_functions"]).tools
    util_agent = create_agent(
        llm,
        tools=python_tools,
        system_prompt=(
            "You are a python function that can generate ECFP molecular fingerprint embeddings "
            "from SMILES and display molecule PNG images from the PubChem website by CID in markdown."
        ),
        name="chem_utils",
    )

    # --- DrugBank Genie agent ---
    drugbank_agent = GenieAgent(_cfg["genie_space_id"], genie_agent_name="drugbank")

    # --- ZINC vector search agent ---
    ret = _cfg["retriever"]
    retriever_tool = VectorSearchRetrieverTool(
        index_name=ret["vs_index"],
        num_results=ret["k"],
        columns=["zinc_id", "smiles", "mwt", "logp", "purchasable"],
        text_column="smiles",
        tool_name=ret["tool_name"],
        tool_description="Search for chemicals in ZINC using molecular fingerprints",
        embedding=DatabricksEmbeddings(endpoint="databricks-bge-large-en"),
        workspace_client=ws_client,
    )

    @tool
    def tool_vectorinput(bitstring: str):
        """
        Search for similar molecules based on their ECFP4 molecular fingerprints embedding
        vector (list of int). Required input (bitstring) is a 1024-char bitstring
        (e.g. 1011..00) which is the concatenated string form of a list of 1024 integers.
        """
        query_vector = [int(c) for c in bitstring]
        docs = retriever_tool._vector_store.similarity_search_by_vector(
            query_vector, k=ret["k"]
        )
        return [doc.metadata | {"smiles": doc.page_content} for doc in docs]

    zinc_agent = create_agent(
        llm,
        tools=[tool_vectorinput],
        system_prompt=(
            "Search for drug-like chemicals in the ZINC database based on ECFP molecular "
            "fingerprint embeddings"
        ),
        name="zinc",
    )

    # --- MCP agents (PubChem / PubMed / OpenTargets) ---
    uc = _cfg["uc_connections"]
    host = _cfg["host"]
    servers = [
        DatabricksMCPServer(
            name="pubchem",
            url=f'{_cfg["host"]}api/2.0/mcp/external/{_cfg["uc_connections"]["pubchem"]}',
            workspace_client=ws_client,
            timeout=60,
            terminate_on_close=False
        ),
        DatabricksMCPServer(
            name="pubmed",
            url=f'{_cfg["host"]}api/2.0/mcp/external/{_cfg["uc_connections"]["pubmed"]}',
            workspace_client=ws_client,
            terminate_on_close=False
        ),
        DatabricksMCPServer(
            name="opentargets",
            url=f'{_cfg["host"]}api/2.0/mcp/external/{_cfg["uc_connections"]["opentargets"]}',
            workspace_client=ws_client,
            terminate_on_close=False,
        ),
    ]

    # class _McpClient(DatabricksMultiServerMCPClient):
    #     def load_tools(self):
    #         return asyncio.run(self.get_tools())

    def get_tools(mcp_client: DatabricksMultiServerMCPClient):
        async def aget_tools():
            return await mcp_client.get_tools()
        return asyncio.run(aget_tools())

    mcp_client = DatabricksMultiServerMCPClient(servers)
    try:
        # mcp_tools = _McpClient(servers).load_tools()
        mcp_tools = get_tools(mcp_client)
        logger.info("MCP tools loaded: %d tools", len(mcp_tools))
    except Exception as exc:
        logger.warning("MCP tool loading failed (%s) — building mcp_agent with no tools.", exc)
        mcp_tools = []
    mcp_prompt = """You are a multi-MCP server agent connected to:
    1. PubChem MCP server that provides everything about chemical compounds
    2. PubMed MCP server that searches biomedical literature and retrieves free full text if any. 
    3. OpenTargets MCP server that provides everything about drug targets and their associations with diseases and drugs.
    Most PubChem tools (e.g. get_compound_info) except for search_compounds expect a CID."""
    mcp_agent = create_agent(
        llm, tools=mcp_tools, system_prompt=mcp_prompt, name="mcp"
    )

    # --- Supervisor ---
    workflow = create_supervisor(
        [drugbank_agent, zinc_agent, util_agent, mcp_agent],
        model=llm,
        prompt="""You are a supervisor managing 4 agents. Route according to the agent required to fulfill the request.
1. Drugbank agent: generates text-to-SQL queries to Drugbank of FDA-approved drugs and their properties
2. ZINC agent: searches for drug-like molecules and their properties from the ZINC database based on ECFP4 molecular fingerprint embeddings represented as a 1024-char bitstring.
3. Chem utilities agent: display molecule image PNG files from PubChem website by CID in markdown or compute ECFP4 molecular fingerprint embeddings in a 1024-char bitstring for a given SMILES structure. If missing SMILES input, query it from a chemical name using the PubChem MCP agent's search_compound tool.
4. MCP agent: connects to the PubChem, PubMed and OpenTargets MCP servers

Because you are an autonomous multi-agent system, do not ask for more follow up information. Instead, use chain-of-thought to reason and break down the request into
achievable steps based on the agentic tools that you have access to. 
""",
        output_mode="last_message",
        add_handoff_messages=False,
        forward_messages=True,
        parallel_tool_calls=True,
    )

    # WrappedAgent (responses_agent_new) only needs the workflow; optional lakebase from config
    return WrappedAgent( # fallback when no checkpointer
      workflow=workflow,
      workspace_client=ws_client,
      lakebase_instance=_cfg["lakebase_agent"]["instance_name"],
  )


def _load_agent_background():
    global _agent
    try:
        logger.info("Building agent...")
        _agent = _build_agent()
        logger.info("Agent ready.")
    except Exception:
        logger.exception("Failed to build agent")
    finally:
        _agent_ready.set()


# Start agent construction in background so the server can accept /health checks immediately
threading.Thread(target=_load_agent_background, daemon=True).start()


# ---------------------------------------------------------------------------
# @invoke endpoint
# ---------------------------------------------------------------------------


async def _wait_for_agent() -> None:
    """Block until the background agent build completes (or times out)."""
    if not _agent_ready.is_set():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _agent_ready.wait, 300)
    if _agent is None:
        raise RuntimeError("Agent failed to initialize. Check logs for details.")


@invoke()
async def predict(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    """Handle agent inference requests via AgentServer /invocations."""
    await _wait_for_agent()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _agent.predict, request)


@stream()
async def predict_stream(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Stream agent responses token-by-token via AgentServer /invocations with stream=true."""
    await _wait_for_agent()
    # Use async generator so the server's "async for" works; predict_stream() is sync.
    async for event in _agent._predict_stream_async(request):
        yield event
