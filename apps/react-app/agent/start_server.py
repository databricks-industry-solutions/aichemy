"""
MLflow AgentServer entry point.

Runs a FastAPI server on port 8080 (Databricks Apps standard port) that:
  - Serves the LangGraph agent at POST /invocations
  - Proxies all other requests (UI) to Streamlit running on CHAT_APP_PORT (default 3000)
  - Exposes GET /health for readiness checks

Usage:
    python start_server.py --port 8080
    python start_server.py --port 8080 --workers 2
"""

from pathlib import Path
import sys

_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))
# Import the module that registers @invoke and @stream (agent/agent.py)
try:
    import agent.agent  # noqa: F401
except ImportError:
    import agent as _agent_pkg  # noqa: F401 — fallback if agent is a single module

from mlflow.genai.agent_server import AgentServer

# MLflow reads MLFLOW_EXPERIMENT_ID automatically — set it in app.yaml
agent_server = AgentServer("ResponsesAgent", enable_chat_proxy=True)

# Expose the ASGI app for uvicorn import-string mode (required for --workers > 1)
app = agent_server.app


def main():
    # Ensure main thread has an event loop before uvicorn runs (required when
    # started as a subprocess on Databricks Apps; otherwise uvloop/nest_asyncio
    # raise "There is no current event loop in thread 'MainThread'").
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    # Passes --port / --workers / --reload through to uvicorn via argparse
    agent_server.run(app_import_string="start_server:app")


if __name__ == "__main__":
    main()
