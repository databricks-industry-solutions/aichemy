"""
LangGraph agent definition for the AgentServer.

Builds the multi-agent supervisor workflow and registers it with mlflow.genai.agent_server's
@invoke and @stream decorators so AgentServer can serve it at /invocations.

The agent is built in a background thread at import time to avoid blocking the server startup.
Requests wait on a threading.Event until the agent is ready.
"""

import asyncio
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
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))

from agent.responses_agent import WrappedAgent
from agent.utils import (
    get_secret,
    init_workspace_client,
    build_mcp_list,
    _collect_tool_metadata,
    _load_mcp_tools_individually,
    _keepalive_loop,
    _touch_activity,
    _warmup,
    _log_exception_group,
    _run_mcp_loop,
    _mcp_run,
    wrap_mcp_tools_with_resilience,
)
from agent.utils_memory import memory_write_tools

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
with open(_app_root / "config.yml") as _f:
    _cfg = yaml.safe_load(_f)

_KEEPALIVE_IDLE_SECS = int(os.environ.get("AGENT_KEEPALIVE_SECS", 600))

# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

_workflow: Optional[StateGraph] = None
_agent = None
_agent_tools: dict[str, list[dict]] = {}
mcp_client = None
_agent_ready = threading.Event()
_agent_build_error: Optional[str] = None

# ---------------------------------------------------------------------------
# Persistent MCP event loop — keeps MCP sessions alive across queries
# ---------------------------------------------------------------------------


threading.Thread(target=_run_mcp_loop, daemon=True, name="mcp-loop").start()
_last_activity = time.monotonic()
_last_activity_lock = threading.Lock()


def _build_agent(cfg: dict) -> StateGraph:
    """Instantiate the full multi-agent supervisor workflow (uncompiled StateGraph)."""
    # import nest_asyncio
    # nest_asyncio.apply()

    from databricks.sdk import WorkspaceClient
    from databricks_langchain import ChatDatabricks, DatabricksEmbeddings
    from databricks_langchain import (
        DatabricksMultiServerMCPClient,
        DatabricksMCPServer,
        MCPServer,
    )
    from databricks_langchain import VectorSearchRetrieverTool
    from databricks_langchain.genie import GenieAgent
    from databricks_langchain.uc_ai import UCFunctionToolkit
    from langchain.agents import create_agent
    from langchain.tools import tool
    from langgraph_supervisor import create_supervisor

    ws_client = init_workspace_client(cfg)

    llm = ChatDatabricks(endpoint=cfg["llm_endpoint"])

    # --- Utility functions agent ---
    function_agents = []
    for agent_name, functions in cfg["uc_functions"].items():
        tools = UCFunctionToolkit(function_names=functions).tools
        function_agent = create_agent(
            llm,
            tools=tools,
            system_prompt=cfg["prompts"][agent_name],
            name=agent_name,
        )
        function_agents.append(function_agent)

    # --- DrugBank Genie agent ---
    genie_agents = []
    for agent_name, genie_config in cfg["genie"].items():
        genie_agent = GenieAgent(genie_config["space_id"], genie_agent_name=agent_name)
        genie_agents.append(genie_agent)

    # --- ZINC vector search agent ---
    retriever_agents = []
    for agent_name, retriever_config in cfg["retriever"].items():
        retriever_tool = VectorSearchRetrieverTool(
            index_name=retriever_config["vs_index"],
            num_results=retriever_config["k"],
            columns=retriever_config["columns"],
            text_column=retriever_config["text_column"],
            tool_name=agent_name,
            tool_description=retriever_config["tool_description"],
            embedding=DatabricksEmbeddings(endpoint=retriever_config["embedding"]),
            workspace_client=init_workspace_client(cfg, SP=True),
        )

        if retriever_config["search_type"] == "vector":
            # only needed if non-text embeddings
            @tool
            def tool_vectorinput(bitstring: str):
                """
                Search for similar molecules based on their ECFP4 molecular fingerprints embedding
                vector (list of int). Required input (bitstring) is a 1024-char bitstring
                (e.g. 1011..00) which is the concatenated string form of a list of 1024 integers.
                """
                query_vector = [int(c) for c in bitstring]
                docs = retriever_tool._vector_store.similarity_search_by_vector(
                    query_vector, k=retriever_config["k"]
                )
                return [doc.metadata | {retriever_config["text_column"]: doc.page_content} for doc in docs]
                
            tool = [tool_vectorinput]
        else:
            tool = [retriever_tool]

        retreiver_agent = create_agent(
            llm,
            tools=[tool_vectorinput],
            system_prompt=cfg["prompts"][agent_name],
            name=agent_name,
        )
        retriever_agents.append(retreiver_agent)

    # --- MCP agents (PubChem / PubMed / OpenTargets) ---
    servers = build_mcp_list(cfg, ws_client=ws_client)

    global mcp_client
    mcp_client = DatabricksMultiServerMCPClient(servers)
    try:
        mcp_tools = _mcp_run(mcp_client.get_tools())
        logger.info("MCP tools loaded: %d tools", len(mcp_tools))
    except BaseException as exc:
        server_names = ", ".join(s.name for s in servers)
        _log_exception_group(exc, server_names=server_names)
        logger.warning("Batch MCP loading failed for [%s] — trying servers individually…", server_names)
        mcp_tools = _load_mcp_tools_individually(servers)
    
    # exclude get_safety_data that is overly verbose (lists full tox classification)
    _EXCLUDED_MCP_TOOLS = {"get_safety_data"}
    mcp_tools = [t for t in mcp_tools if t.name not in _EXCLUDED_MCP_TOOLS]
    
    mcp_tools = wrap_mcp_tools_with_resilience(mcp_tools)
    mcp_agent = create_agent(
        llm, tools=mcp_tools, system_prompt=cfg["prompts"]["mcp"], name="mcp"
    )

    # --- Memory agent (save/delete only — retrieval is auto-injected) ---
    mem_agent = create_agent(
        llm,
        tools=memory_write_tools(),
        system_prompt=cfg["prompts"]["memory"],
        name="memory",
    )

    global _agent_tools
    _agent_tools = _collect_tool_metadata(mcp_tools, cfg)

    # --- Supervisor ---
    workflow = create_supervisor(
        [mcp_agent, mem_agent] + function_agents + genie_agents + retriever_agents,
        model=llm,
        prompt=cfg["prompts"]["supervisor"],
        output_mode="last_message",
        add_handoff_messages=False,
        parallel_tool_calls=True,
    )
    return workflow


def build_responses_agent(cfg: dict, workflow: Optional[StateGraph] = None) -> WrappedAgent:
    """Wrap a LangGraph workflow in a WrappedAgent (ResponsesAgent).

    If *workflow* is None, calls _build_agent() to create one.
    """
    if workflow is None:
        workflow = _build_agent(cfg)
    return WrappedAgent(
        workflow=workflow,
        workspace_client=init_workspace_client(cfg, SP=True),  #use SP-based ws_client for Lakebase writes
        cfg=cfg
    )


def launch_agent_background():
    global _agent, _workflow, _agent_build_error
    try:
        logger.info("Building agent…")
        _workflow = _build_agent(_cfg)
        _agent = build_responses_agent(_cfg, _workflow)
        logger.info("Agent ready.")
        # _warmup(_agent)
    except Exception as exc:
        _agent_build_error = f"{type(exc).__name__}: {exc}"
        logger.exception("Failed to build agent")
    finally:
        _agent_ready.set()


# Start agent construction in background so the server can accept /health checks immediately
threading.Thread(target=launch_agent_background, daemon=True).start()
threading.Thread(
    target=_keepalive_loop,
    args=(lambda: (_agent, mcp_client), _KEEPALIVE_IDLE_SECS),
    daemon=True,
).start()

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
    user_id = ci.get("user_id")
    inputs = {"messages": cc_msgs}
    config = {"configurable": {"thread_id": thread_id}}
    if user_id:
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
        

    async for chunk in _workflow.compile().astream(inputs, config=config):
        print(chunk, flush=True)
    yield ResponsesAgentStreamEvent(type="response.output_text.done")
