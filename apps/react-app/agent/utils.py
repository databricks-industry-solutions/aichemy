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
from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan

logger = logging.getLogger(__name__)


def load_config(file=None):
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
    print(f"Setting MLflow experiment to {experiment_id}")

    if experiment_id is None:
        cfg = load_config()
        experiment_id = (cfg or {}).get("experiment_id")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(registry_uri)
    mlflow.set_experiment(experiment_id=str(experiment_id).strip())


def get_secret(scope: str, key: str) -> str:
    w0 = WorkspaceClient()
    secret_base64 = w0.secrets.get_secret(scope, key).value
    return b64decode(secret_base64).decode("utf-8")


def get_secret_from_cfg(cfg) -> tuple[str | None, str | None]:
    """Extract SP client_id and client_secret from a config dict via Databricks secrets."""
    sp_creds = cfg.get("service_principal", {})
    print(f"Service Principal credentials: {sp_creds}")
    if not sp_creds:
        return None, None
    scope_name = next(iter(sp_creds))
    scope_cfg = sp_creds[scope_name]
    client_id = get_secret(scope=scope_name, key=scope_cfg["client_id"])
    client_secret = get_secret(scope=scope_name, key=scope_cfg["client_secret"])
    print(f"Service Principal credentials found for {scope_name}: {client_id}")
    return client_id, client_secret


def init_workspace_client(cfg):
    # SP login takes precedence over PAT/profile login (for Lakebase writes)
    client_id, client_secret = get_secret_from_cfg(cfg)
    if client_id and client_secret:
        try:
            ws_client = WorkspaceClient(
                host=cfg["host"], client_id=client_id, client_secret=client_secret
            )
            print(f"Workspace client initialized with SP: {client_id}")
        except Exception as e:
            print(
                f"Error initializing workspace client with SP. Using WorkspaceClient() instead: {e}"
            )
            ws_client = WorkspaceClient()
    else:
        logger.warning("Service Principal credentials not in config.yml. Defaulting to WorkspaceClient()")
        ws_client = WorkspaceClient()
    return ws_client


def get_trace(trace_id: str, retries: int = 5, delay: float = 2.0):
    """Get a trace by its ID with retries (agent writes are async).

    Waits until the trace exists AND is complete (all spans flushed).
    A trace is considered complete when its state is a terminal value
    (OK / ERROR) and it contains at least one span.
    Returns the Trace object or None after all retries fail.
    """
    import time

    _TERMINAL = {"OK", "ERROR", "TraceStatus.OK", "TraceStatus.ERROR"}

    for attempt in range(retries):
        try:
            trace = mlflow.get_trace(trace_id=trace_id)
            if trace is not None:
                state = str(getattr(trace.info, "state", ""))
                spans = trace.data.spans if trace.data else []
                if state in _TERMINAL and len(spans) > 0:
                    print(
                        f"[get_trace] Attempt {attempt+1}/{retries}: trace ready "
                        f"(state={state}, spans={len(spans)})"
                    )
                    return trace
                print(
                    f"[get_trace] Attempt {attempt+1}/{retries}: trace exists but not terminal "
                    f"(state={state}, spans={len(spans)}), retrying..."
                )
            else:
                print(
                    f"[get_trace] Attempt {attempt+1}/{retries}: trace not found yet, retrying..."
                )
        except Exception as e:
            print(
                f"[get_trace] Attempt {attempt+1}/{retries}: exception {type(e).__name__}: {e}, retrying..."
            )
        if attempt < retries - 1:
            time.sleep(delay)
    # Last-ditch: return whatever we have (may be incomplete)
    try:
        return mlflow.get_trace(trace_id=trace_id)
    except Exception:
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


def _log_exception_group(exc: BaseException, server_names: str = "") -> None:
    """Recursively log all sub-exceptions from an ExceptionGroup."""
    prefix = f"[{server_names}] " if server_names else ""
    if isinstance(exc, BaseExceptionGroup):
        for i, sub in enumerate(exc.exceptions, 1):
            logger.error(
                "  %sMCP sub-exception %d/%d: %s: %s",
                prefix,
                i,
                len(exc.exceptions),
                type(sub).__name__,
                sub,
            )
            _log_exception_group(sub, server_names=server_names)
    else:
        logger.error("  %sMCP root cause: %s: %s", prefix, type(exc).__name__, exc)


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
            logger.warning(
                "ws_client is None, using WorkspaceClient() instead for %s", name
            )
            ws_client = WorkspaceClient()

        servers.append(
            DatabricksMCPServer(
                name=name,
                url=f"{host}api/2.0/mcp/external/{conn_name}",
                workspace_client=ws_client,
                timeout=60,
                terminate_on_close=False,
            )
        )

    for name, mcp_cfg in cfg.get("external_mcp", {}).items():
        url = mcp_cfg["url"]
        kwargs = dict(name=name, url=url, timeout=60, terminate_on_close=False)
        if "secret" in mcp_cfg:
            kwargs["headers"] = {
                "Authorization": f"Bearer {get_secret(scope=mcp_cfg.get('scope'), key=mcp_cfg.get('secret'))}"
            }
            print(f"Getting bearer token from scope {mcp_cfg.get('scope')} and secret {mcp_cfg.get('secret')}")
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
                logger.info(
                    "  ✓ %s: %d tools loaded (attempt %d)",
                    srv.name,
                    len(tools),
                    attempt,
                )
                all_tools.extend(tools)
                loaded = True
                break
            except BaseException as e:
                _log_exception_group(e, server_names=srv.name)
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.info(
                        "  ⟳ %s: retry %d/%d in %ds…",
                        srv.name,
                        attempt,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning(
                        "  ✗ %s: failed after %d attempts", srv.name, max_retries
                    )
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
                # _warmup(agent)
                _touch_activity()


def _collect_tool_metadata(mcp_tools: list, cfg: dict) -> dict[str, list[dict]]:
    """Build a {agent_name: [{name, description}, ...]} dict from live tools and config."""
    from databricks_langchain.uc_ai import UCFunctionToolkit
    from agent.utils_memory import memory_write_tools

    def _meta(t):
        return {
            "name": getattr(t, "name", str(t)),
            "description": getattr(t, "description", "") or "",
        }

    result: dict[str, list[dict]] = {}
    result["mcp"] = [_meta(t) for t in mcp_tools]
    result["memory"] = [_meta(t) for t in memory_write_tools()]
    for agent_name, functions in cfg.get("uc_functions", {}).items():
        result[agent_name] = [
            _meta(t) for t in UCFunctionToolkit(function_names=functions).tools
        ]
    for agent_name in cfg.get("genie", {}):
        result[agent_name] = [
            {"name": "genie_query", "description": "Text-to-SQL via Genie Space"}
        ]
    for agent_name, rc in cfg.get("retriever", {}).items():
        result[agent_name] = [
            {"name": agent_name, "description": rc.get("tool_description", "")}
        ]
    return result


def _strip_lc_ids(result):
    """Strip LangChain-injected 'id' fields from MCP tool result content blocks.

    The Databricks model serving API rejects extra fields (e.g. ``id``) in
    tool_result content blocks, causing a 400 BAD_REQUEST error.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return [
            {k: v for k, v in item.items() if k != "id"}
            if isinstance(item, dict) else item
            for item in result
        ]
    if isinstance(result, tuple) and len(result) == 2:
        return (_strip_lc_ids(result[0]), result[1])
    if isinstance(result, dict):
        cleaned = {k: v for k, v in result.items() if k != "id"}
        if "content" in cleaned and isinstance(cleaned["content"], list):
            cleaned["content"] = _strip_lc_ids(cleaned["content"])
        return cleaned
    return result


def wrap_mcp_tools_with_resilience(tools, max_concurrent=2, call_delay=1.0):
    """Wrap MCP tools with concurrency limiting and graceful error handling.

    Prevents 429 rate-limit errors from external MCP servers by throttling
    concurrent calls via a semaphore and inserting a delay after each call.
    Errors are returned as strings so the LLM can adapt rather than crashing
    the entire agent stream.
    """
    sem = asyncio.Semaphore(max_concurrent)

    for tool in tools:
        orig = tool.coroutine
        name = tool.name
        expects_tuple = getattr(tool, "response_format", None) == "content_and_artifact"

        async def _wrapped(
            *args, _orig=orig, _name=name, _tuple=expects_tuple, **kwargs
        ):
            async with sem:
                try:
                    result = await _orig(*args, **kwargs)
                    await asyncio.sleep(call_delay)
                    #return result
                    return _strip_lc_ids(result)
                except Exception as e:
                    logger.error(
                        "MCP tool '%s' error: %s: %s", _name, type(e).__name__, e
                    )
                    err_msg = (
                        f"Error calling tool '{_name}': {type(e).__name__}: {e}. "
                        f"The external service may be temporarily unavailable or "
                        f"rate-limiting. Try a different approach or tool."
                    )
                    return (err_msg, None) if _tuple else err_msg

        tool.coroutine = _wrapped
    return tools
    

class SanitizeNullAttributesProcessor(SpanProcessor):
    """Remove None-valued attributes that would fail OTLP encoding."""

    def on_end(self, span: ReadableSpan) -> None:
        if not hasattr(span, "_attributes") or span._attributes is None:
            return
        keys_to_remove = [
            k for k, v in span._attributes.items() if v is None
        ]
        for k in keys_to_remove:
            del span._attributes[k]
