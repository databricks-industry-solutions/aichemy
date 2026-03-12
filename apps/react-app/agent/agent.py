"""
LangGraph agent definition for the AgentServer.

Builds the multi-agent supervisor workflow and registers it with mlflow.genai.agent_server's
@invoke and @stream decorators so AgentServer can serve it at /invocations.

The agent is built in a background thread at import time to avoid blocking the server startup.
Requests wait on a threading.Event until the agent is ready.
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import AsyncGenerator, Optional
from uuid import uuid4
import yaml
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)
from langgraph.graph.state import StateGraph

logger = logging.getLogger(__name__)

_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))

from agent.responses_agent import WrappedAgent
from agent.utils import init_workspace_client, get_secret
# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

with open(_app_root / "config.yml") as _f:
    _cfg = yaml.safe_load(_f)

ws_client = init_workspace_client(_cfg)

# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

_workflow: Optional[StateGraph] = None
_agent = None
_agent_ready = threading.Event()
_agent_build_error: Optional[str] = None

# ---------------------------------------------------------------------------
# Persistent MCP event loop — keeps MCP sessions alive across queries
# ---------------------------------------------------------------------------
_mcp_loop = asyncio.new_event_loop()
mcp_client = None


def _run_mcp_loop():
    asyncio.set_event_loop(_mcp_loop)
    _mcp_loop.run_forever()


threading.Thread(target=_run_mcp_loop, daemon=True, name="mcp-loop").start()


def _mcp_run(coro, timeout=300):
    """Schedule a coroutine on the persistent MCP loop and block for the result."""
    return asyncio.run_coroutine_threadsafe(coro, _mcp_loop).result(timeout=timeout)


def _log_exception_group(exc: BaseException) -> None:
    """Recursively log all sub-exceptions from an ExceptionGroup."""
    if isinstance(exc, BaseExceptionGroup):
        for i, sub in enumerate(exc.exceptions, 1):
            logger.error("  MCP sub-exception %d/%d: %s: %s", i, len(exc.exceptions),
                         type(sub).__name__, sub)
            _log_exception_group(sub)
    else:
        logger.error("  MCP root cause: %s: %s", type(exc).__name__, exc)


def _load_mcp_tools_individually(servers, max_retries: int = 3) -> list:
    """Try loading tools from each MCP server with retries; skip persistent failures."""
    from databricks_langchain import DatabricksMultiServerMCPClient
    all_tools = []
    for srv in servers:
        loaded = False
        for attempt in range(1, max_retries + 1):
            single_client = DatabricksMultiServerMCPClient([srv])
            try:
                tools = _mcp_run(single_client.get_tools(), timeout=300)
                logger.info("  ✓ %s: %d tools loaded (attempt %d)", srv.name, len(tools), attempt)
                all_tools.extend(tools)
                loaded = True
                break
            except BaseException as e:
                _log_exception_group(e)
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.info("  ⟳ %s: retry %d/%d in %ds…", srv.name, attempt, max_retries, wait)
                    time.sleep(wait)
                else:
                    logger.warning("  ✗ %s: failed after %d attempts", srv.name, max_retries)
    logger.info("MCP fallback complete: %d total tools loaded", len(all_tools))
    return all_tools


def _build_agent() -> StateGraph:
    """Instantiate the full multi-agent supervisor workflow (uncompiled StateGraph)."""
    # import nest_asyncio
    # nest_asyncio.apply()

    from databricks.sdk import WorkspaceClient
    from databricks_langchain import ChatDatabricks, DatabricksEmbeddings
    from databricks_langchain import DatabricksMultiServerMCPClient, DatabricksMCPServer, MCPServer
    from databricks_langchain import VectorSearchRetrieverTool
    from databricks_langchain.genie import GenieAgent
    from databricks_langchain.uc_ai import UCFunctionToolkit
    from langchain.agents import create_agent
    from langchain.tools import tool
    from langgraph_supervisor import create_supervisor

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
        # DatabricksMCPServer(
        #     name="pubchem",
        #     url=f'{_cfg["host"]}api/2.0/mcp/external/{_cfg["uc_connections"]["pubchem"]}',
        #     workspace_client=ws_client,
        #     timeout=60,
        #     terminate_on_close=False
        # ),
        MCPServer(
            name="pubchem",
            url="https://glama.ai/endpoints/xb306rnopq/mcp",
            timeout=60,
            terminate_on_close=False,
            headers={"Authorization": f"Bearer {get_secret(scope='aichemy', key='pubchem_glama_api')}"}
        ),
        MCPServer(
            name="pubmed",
            url="https://glama.ai/endpoints/mp1ke6xrpi/mcp",
            timeout=60,
            terminate_on_close=False,
            headers={"Authorization": f"Bearer {get_secret(scope='aichemy', key='pubmed_glama_api')}"}
        ),
        MCPServer(
            name="opentargets",
            url="https://mcp.platform.opentargets.org/mcp"
        )
    ]

    global mcp_client
    mcp_client = DatabricksMultiServerMCPClient(servers)
    try:
        mcp_tools = _mcp_run(mcp_client.get_tools())
        logger.info("MCP tools loaded: %d tools", len(mcp_tools))
    except BaseException as exc:
        _log_exception_group(exc)
        logger.warning("Batch MCP loading failed — trying servers individually…")
        mcp_tools = _load_mcp_tools_individually(servers)
    mcp_prompt = """You are a multi-MCP server agent connected to:
    1. PubChem MCP server that provides everything about chemical compounds
    2. PubMed MCP server that searches biomedical literature and retrieves free full text if any. 
    3. OpenTargets MCP server that provides everything about drug targets and their associations with diseases and drugs.
    Most PubChem tools (e.g. get_compound_info) except for search_compounds expect a CID."""
    mcp_agent = create_agent(
        llm, tools=mcp_tools, system_prompt=mcp_prompt, name="mcp"
    )

    # --- Supervisor ---
    supervisor_prompt = (
        "You are a supervisor managing 4 agents. Route to the agent required to fulfill the request.\n"
        "1. Drugbank agent: generates text-to-SQL queries to Drugbank of FDA-approved drugs and their properties\n"
        "2. ZINC agent: searches for drug-like molecules and their properties from the ZINC database "
        "based on ECFP4 molecular fingerprint embeddings represented as a 1024-char bitstring.\n"
        "3. Chem utilities agent: display molecule image PNG files from PubChem website by CID in "
        "markdown or compute ECFP4 molecular fingerprint embeddings in a 1024-char bitstring for a "
        "given SMILES structure. If missing SMILES input, query it from a chemical name using the "
        "PubChem MCP agent's search_compound tool.\n"
        "4. MCP agent: connects to the PubChem, PubMed and OpenTargets MCP servers\n\n"
        "Because you are an autonomous multi-agent system, do not ask for more follow up information. "
        "Instead, use chain-of-thought to reason and break down the request into achievable steps "
        "based on the agentic tools that you have access to.\n\n"
        "CRITICAL RULES — FOLLOW EXACTLY:\n"
        "1. PASS THROUGH RESULTS: When a sub-agent returns data (tables, query results, search results), "
        "that IS the final answer. Tables and structured data do NOT need summarisation. "
        "NEVER fabricate, extend, or add rows/data that were not in the sub-agent's output.\n"
        "2. ONE CALL PER AGENT PER STEP: NEVER route to the same agent twice for the same sub-task. "
        "Once an agent returns a result, that result is COMPLETE. Do NOT re-route to the same agent "
        "to rephrase, summarise, or improve the answer unless another tool is required.\n"
        "3. TERMINATE IMMEDIATELY: After a sub-agent returns data for a single-step request, "
        "FINISH your turn. Do NOT hand off to any agent again.\n"
        "4. For MULTI-STEP requests (e.g. 'find similar molecules to semaglutide'), route to "
        "DIFFERENT agents in sequence — never the same agent twice."
    )
    workflow = create_supervisor(
        [drugbank_agent, zinc_agent, util_agent, mcp_agent],
        model=llm,
        prompt=supervisor_prompt,
        output_mode="last_message",
        add_handoff_messages=False,
        parallel_tool_calls=True,
    )
    return workflow


def build_responses_agent(workflow: Optional[StateGraph] = None) -> WrappedAgent:
    """Wrap a LangGraph workflow in a WrappedAgent (ResponsesAgent).

    If *workflow* is None, calls _build_agent() to create one.
    """
    if workflow is None:
        workflow = _build_agent()
    return WrappedAgent(
        workflow=workflow,
        workspace_client=ws_client,
        lakebase_instance=_cfg["lakebase_agent"]["instance_name"],
    )


_KEEPALIVE_IDLE_SECS = int(os.environ.get("AGENT_KEEPALIVE_SECS", 600))  # 10 min
_last_activity = time.monotonic()
_last_activity_lock = threading.Lock()


def _touch_activity() -> None:
    """Record that a real request was just served."""
    global _last_activity
    with _last_activity_lock:
        _last_activity = time.monotonic()


def _warmup(agent: "WrappedAgent") -> None:
    """Send a trivial query to pre-warm LLM endpoint, Lakebase checkpointer, etc."""
    try:
        logger.info("Sending warmup query…")
        warmup_req = ResponsesAgentRequest(
            input=[{"role": "user", "content": "hello"}],
            custom_inputs={"thread_id": f"_warmup_{uuid4().hex[:8]}"},
        )
        for _ in agent.predict_stream(warmup_req):
            pass
        logger.info("Warmup complete.")
    except Exception as exc:
        logger.warning("Warmup query failed (non-fatal): %s", exc)


def _ping_mcp() -> None:
    """Send tools/list to each MCP server to keep the sessions on _mcp_loop alive."""
    if mcp_client is None:
        return
    try:
        logger.info("Pinging MCP servers…")
        _mcp_run(mcp_client.get_tools(), timeout=120)
        logger.info("MCP ping OK.")
    except Exception as exc:
        logger.warning("MCP ping failed (non-fatal): %s", exc)


def _keepalive_loop() -> None:
    """Background loop: keep agent and MCP sessions warm during idle periods."""
    while True:
        time.sleep(60)
        if _agent is None:
            continue
        with _last_activity_lock:
            idle = time.monotonic() - _last_activity
        if idle >= _KEEPALIVE_IDLE_SECS:
            _ping_mcp()
            #_warmup(_agent)
            _touch_activity()


def _load_agent_background():
    global _agent, _workflow, _agent_build_error
    try:
        logger.info("Building agent…")
        _workflow = _build_agent()
        _agent = build_responses_agent(_workflow)
        logger.info("Agent ready.")
        #_warmup(_agent)
    except Exception as exc:
        _agent_build_error = f"{type(exc).__name__}: {exc}"
        logger.exception("Failed to build agent")
    finally:
        _agent_ready.set()


# Start agent construction in background so the server can accept /health checks immediately
threading.Thread(target=_load_agent_background, daemon=True).start()
threading.Thread(target=_keepalive_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# @invoke endpoint
# ---------------------------------------------------------------------------


async def _wait_for_agent() -> None:
    """Block until the background agent build completes (or times out)."""
    if not _agent_ready.is_set():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _agent_ready.wait, 300)
    if _agent is None:
        msg = "Agent failed to initialize. Check logs for details."
        if _agent_build_error:
            msg += f" Cause: {_agent_build_error}"
        raise RuntimeError(msg)


@invoke()
async def predict(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    """Handle agent inference requests via AgentServer /invocations."""
    await _wait_for_agent()
    _touch_activity()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _agent.predict, request)


@stream()
async def predict_stream(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Stream via WrappedAgent (Lakebase checkpointer + ResponsesAgent helpers)."""
    await _wait_for_agent()
    _touch_activity()
    try:
        async for event in _agent._predict_stream_async(request):
            yield event
    except Exception as e:
        logger.exception("Error in predict_stream")
        from langchain_core.messages import AIMessage
        error_msg = AIMessage(content=f"**Agent error:** `{type(e).__name__}`: {e}")
        for item in output_to_responses_items_stream([error_msg]):
            yield item


# ---------------------------------------------------------------------------
# Alternative: raw LangGraph astream for debugging (no WrappedAgent / Lakebase)
# ---------------------------------------------------------------------------
# To use this instead, swap the @stream() decorator:
#   1. Remove @stream() from predict_stream above
#   2. Uncomment @stream() on predict_stream_raw below


# @stream()
async def predict_stream_raw(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Simple debug stream directly from the LangGraph workflow using astream.

    Compiles the workflow without a checkpointer (no Lakebase memory) and
    prints each chunk to stdout for inspection.
    """
    await _wait_for_agent()

    cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
    ci = dict(request.custom_inputs or {})
    thread_id = ci.get("thread_id", str(uuid4()))
    inputs = {"messages": cc_msgs}
    config = {"configurable": {"thread_id": thread_id}}

    async for chunk in _workflow.compile().astream(inputs, config=config):
        print(chunk, flush=True)
    yield ResponsesAgentStreamEvent(type="response.output_text.done")
