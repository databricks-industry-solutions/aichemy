"""
MLflow AgentServer entry point.
Serves the agent at POST /invocations, GET /health; proxies UI to Streamlit.
"""
from pathlib import Path
import sys

_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))

from mlflow.genai.agent_server import AgentServer

# Import agent to register @invoke / @stream with the server
try:
    import agent.agent  # noqa: F401
except ImportError:
    import agent as _agent_pkg  # noqa: F401

agent_server = AgentServer("ResponsesAgent", enable_chat_proxy=True)
app = agent_server.app


def main():
    # Required when run as subprocess (e.g. Databricks Apps): avoid uvloop
    # "no current event loop" by using default policy and ensuring a loop exists.
    # import asyncio
    # asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    # try:
    #     asyncio.get_event_loop()
    # except RuntimeError:
    #     asyncio.set_event_loop(asyncio.new_event_loop())
    agent_server.run(app_import_string="start_server:app")


if __name__ == "__main__":
    main()
