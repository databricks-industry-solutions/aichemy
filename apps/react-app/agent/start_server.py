"""
MLflow AgentServer entry point.
Serves the agent at POST /invocations, GET /health; proxies UI to Streamlit.
"""
from pathlib import Path
import sys
from mlflow.genai.agent_server import AgentServer
import mlflow
import os
from starlette.responses import JSONResponse
from starlette.routing import Route
from opentelemetry import trace


_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))

from agent.utils import init_mlflow, load_env_from_app_yaml, SanitizeNullAttributesProcessor

load_env_from_app_yaml()
init_mlflow()

# Register with the global Otel TracerProvider before mlflow logging
provider = trace.get_tracer_provider()
if hasattr(provider, "add_span_processor"):
    provider.add_span_processor(SanitizeNullAttributesProcessor())
mlflow.langchain.autolog()

# Import agent to register @invoke / @stream with the server
try:
    import agent.agent as _agent_mod
except Exception as _import_err:
    import logging as _logging
    _logging.getLogger(__name__).error("Failed to import agent.agent: %s", _import_err, exc_info=True)

agent_server = AgentServer("ResponsesAgent", enable_chat_proxy=True)
app = agent_server.app

# ---------------------------------------------------------------------------
# Custom endpoints: agent readiness + warmup
# ---------------------------------------------------------------------------
async def agent_status_endpoint(request):
    ready = _agent_mod._agent_ready.is_set()
    has_agent = _agent_mod._agent is not None
    return JSONResponse({
        "ready": ready and has_agent,
        "building": not ready,
        "error": _agent_mod._agent_build_error if ready and not has_agent else None,
    })


async def agent_warmup_endpoint(request):
    if not _agent_mod._agent_ready.is_set():
        return JSONResponse({"ok": False, "detail": "Agent is still building"}, status_code=503)
    if _agent_mod._agent is None:
        err = _agent_mod._agent_build_error or "Agent failed to build"
        return JSONResponse({"ok": False, "detail": err}, status_code=503)
    import threading
    threading.Thread(target=_agent_mod._warmup, args=(_agent_mod._agent,), daemon=True).start()
    return JSONResponse({"ok": True, "detail": "Warmup started"})


async def agent_tools_endpoint(request):
    """Return tool metadata grouped by sub-agent, collected during agent build."""
    if not _agent_mod._agent_ready.is_set():
        return JSONResponse({"error": "Agent not ready"}, status_code=503)
    return JSONResponse(_agent_mod._agent_tools)


app.routes.insert(0, Route("/agent-status", agent_status_endpoint, methods=["GET"]))
app.routes.insert(0, Route("/agent-warmup", agent_warmup_endpoint, methods=["POST"]))
app.routes.insert(0, Route("/agent-tools", agent_tools_endpoint, methods=["GET"]))

def main():
    # Required when run on Databricks Apps (or as subprocess): nest_asyncio + uvloop
    # would raise "no current event loop". Use default policy and ensure a loop.
    import asyncio
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    agent_server.run(app_import_string="start_server:app")


if __name__ == "__main__":
    main()
