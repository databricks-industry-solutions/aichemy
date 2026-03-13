from pathlib import Path
import os
import time
from databricks.sdk import WorkspaceClient
from base64 import b64decode
import mlflow
import yaml
import threading
from mlflow.types.responses import ResponsesAgentRequest
from uuid import uuid4
import asyncio
import logging

logger = logging.getLogger(__name__)


def _load_config(file=None):
    """Load config.yml from app root (parent of agent/)."""
    if file:
        with open(file) as f:
            return yaml.safe_load(f)
    else:
        app_root = Path(__file__).resolve().parent.parent
        file = app_root / "config.yml"
    with open(file) as f:
        return yaml.safe_load(f)



def load_env_from_app_yaml():
    """Set env vars from app.yaml for local (Mac) development.

    On Databricks Apps the platform injects these automatically.
    Existing env vars are never overwritten.
    """
    app_root = Path(__file__).resolve().parent.parent
    app_yaml = app_root / "app.yaml"
    if not app_yaml.exists():
        return
    with open(app_yaml) as f:
        spec = yaml.safe_load(f)
    for entry in spec.get("env", []):
        name = entry.get("name")
        value = entry.get("value")
        if name and value is not None and name not in os.environ:
            os.environ[name] = str(value)


def init_mlflow():
    """Set MLflow tracking URI and experiment. Single place for agent and web server."""
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "databricks")
    registry_uri = os.environ.get("MLFLOW_REGISTRY_URI", "databricks-uc")
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID")

    if experiment_id is None:
        cfg = _load_config()
        experiment_id = (cfg or {}).get("experiment_id", "1001868044455114")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(registry_uri)
    mlflow.set_experiment(experiment_id=str(experiment_id).strip())


def get_secret(scope: str, key: str) -> str:
    w0 = WorkspaceClient()
    secret_base64 = w0.secrets.get_secret(scope, key).value
    return b64decode(secret_base64).decode("utf-8")


def init_workspace_client(cfg):
    client_id = get_secret(scope='aichemy', key='client_id')
    client_secret = get_secret(scope='aichemy', key='client_secret')
    try:
        ws_client = WorkspaceClient(
            host=cfg["host"],
            client_id=client_id,
            client_secret=client_secret
        )
    except Exception as e:
        print(f"Error initializing workspace client with SP. Using WorkspaceClient() instead: {e}")
        ws_client = WorkspaceClient()
    return ws_client


def get_trace(trace_id: str, retries: int = 5, delay: float = 2.0):
    """Get a trace by its ID with retries (agent writes are async).
    Returns the Trace object or None after all retries fail."""
    import time
    for attempt in range(retries):
        try:
            trace = mlflow.get_trace(trace_id=trace_id)
            if trace is not None:
                return trace
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay)
    return None


# ---------------------------------------------------------------------------
# MCP utils
# ---------------------------------------------------------------------------

_mcp_loop = asyncio.new_event_loop()

def _run_mcp_loop():
    asyncio.set_event_loop(_mcp_loop)
    _mcp_loop.run_forever()


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


def build_mcp_list(cfg, ws_client=None):
    """Build a list of MCP server objects from config.yml sections.

    Reads ``uc_connections`` (-> DatabricksMCPServer via the workspace proxy)
    and ``external_mcp`` (-> MCPServer with direct URLs).  Glama.ai endpoints
    get an Authorization header automatically via ``get_secret``.

    Returns a list suitable for ``DatabricksMultiServerMCPClient(mcp_list)``.
    """
    from databricks_langchain import DatabricksMCPServer, MCPServer

    servers = []
    host = cfg.get("host", "").rstrip("/") + "/"

    for name, conn_name in cfg.get("uc_connections", {}).items():
        if ws_client is None:
            logger.warning("ws_client is None, using WorkspaceClient() instead for %s", name)
            ws_client = WorkspaceClient()

        servers.append(DatabricksMCPServer(
            name=name,
            url=f"{host}api/2.0/mcp/external/{conn_name}",
            workspace_client=ws_client,
            timeout=60,
            terminate_on_close=False,
        ))

    for name, url in cfg.get("external_mcp", {}).items():
        kwargs = dict(name=name, url=url, timeout=60, terminate_on_close=False)
        if "glama.ai" in url:
            kwargs["headers"] = {
                "Authorization": f"Bearer {get_secret(scope='aichemy', key=f'{name}_glama_api')}"
            }
        servers.append(MCPServer(**kwargs))

    return servers


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


# ---------------------------------------------------------------------------
# Agent utils
# ---------------------------------------------------------------------------

_last_activity_lock = threading.Lock()
_last_activity = time.monotonic()


def _touch_activity() -> None:
    """Record that a real request was just served."""
    global _last_activity
    with _last_activity_lock:
        _last_activity = time.monotonic()


def _warmup(agent) -> None:
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


def _ping_mcp(mcp_client=None) -> None:
    """Send tools/list to each MCP server to keep the sessions on _mcp_loop alive."""
    if mcp_client is None:
        return
    try:
        logger.info("Pinging MCP servers…")
        _mcp_run(mcp_client.get_tools(), timeout=120)
        logger.info("MCP ping OK.")
    except Exception as exc:
        logger.warning("MCP ping failed (non-fatal): %s", exc)


def _keepalive_loop(get_state, keepalive_secs=600) -> None:
    """Background loop: keep agent and MCP sessions warm during idle periods.

    Args:
        get_state: callable returning (agent, mcp_client) from the caller's
                   module-level globals so we always see the latest values.
        keepalive_secs: idle threshold before pinging MCP.
    """
    while True:
        time.sleep(60)
        agent, mcp = get_state()
        if agent and mcp:
            with _last_activity_lock:
                idle = time.monotonic() - _last_activity
            if idle >= keepalive_secs:
                _ping_mcp(mcp)
                #_warmup(agent)
                _touch_activity()
