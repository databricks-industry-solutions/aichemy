"""
Backend proxy server for AiChemy React app.
Handles Databricks authentication, proxies requests to the agent endpoint,
and provides project persistence via SQLite (local dev) or Lakebase Postgres (production).

The agent endpoint (POST /invocations) is served by agent/start_server.py (MLflow AgentServer).
Port is set via AGENT_PORT (default 8080). Run separately: python agent/start_server.py --port <AGENT_PORT>
"""
import os
import re
import json
import yaml
import sqlite3
import requests
from uuid import uuid4
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union
from databricks.sdk import WorkspaceClient
import sys
import mlflow

_app_root = Path(__file__).resolve().parent.parent
_project_root = _app_root.parent.parent
sys.path.insert(0, str(_app_root))

from agent.utils import get_secret, init_mlflow

init_mlflow()


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
# Database layer – auto-connects to Lakebase if Databricks auth is available,
# otherwise falls back to local SQLite. No manual config needed.
# ---------------------------------------------------------------------------

class ProjectDB:
    """Project storage with automatic Lakebase Autoscaling connection.

    On startup, tries to connect to Lakebase Autoscaling using Databricks SDK auth.
    If that fails for any reason, silently falls back to local SQLite.

    Lakebase Autoscaling uses the w.postgres API with hierarchical resource names:
      projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}
    """

    def __init__(self, sqlite_path: str = "projects.db"):
        self._sqlite_path = sqlite_path
        self._use_pg = False
        self._last_lakebase_error: Optional[str] = None
        self._lakebase_project_id: Optional[str] = None
        self._lakebase_branch_id: Optional[str] = None
        self._lakebase_endpoint_id: Optional[str] = None
        self._lakebase_endpoint_name: Optional[str] = None  # full resource path
        self._lakebase_database: Optional[str] = None
        self._lakebase_host: Optional[str] = None
        self._lakebase_token: Optional[str] = None
        self._lakebase_user: Optional[str] = None
        self._sp_client: Optional[WorkspaceClient] = None
        self._host: Optional[str] = None

    def init(self):
        """Initialize DB — call after WorkspaceClient is available."""
        if self._try_lakebase():
            print("[ProjectDB] Using Lakebase Autoscaling Postgres")
        else:
            print("[ProjectDB] Using local SQLite")
            self._init_sqlite()

    # -- Lakebase Autoscaling auto-detection --------------------------------

    def _try_lakebase(self) -> bool:
        """Try to auto-connect to Lakebase Autoscaling using service principal credentials.

        Flow:
          1. Read config.yml for lakebase project_id / branch_id / endpoint_id / database
          2. Get SP credentials: env vars (Databricks Apps) > secrets API (local dev)
          3. Create an SP-authenticated WorkspaceClient
          4. Resolve endpoint host via w.postgres.get_endpoint()
          5. Generate an ephemeral OAuth token via w.postgres.generate_database_credential()
          6. Test the connection (with retry for scale-to-zero wake-up)

        Falls back to SQLite if any step fails.
        """
        try:
            # 1. Read config.yml
            cfg = _load_config()
            if not cfg:
                print("[ProjectDB] config.yml not found, skipping Lakebase")
                return False

            lakebase_cfg = cfg.get("lakebase")
            if not lakebase_cfg or not lakebase_cfg.get("project_id"):
                return False

            self._lakebase_project_id = lakebase_cfg["project_id"]
            self._lakebase_branch_id = lakebase_cfg.get("branch_id", "main")
            self._lakebase_endpoint_id = lakebase_cfg.get("endpoint_id", "primary")
            self._lakebase_database = lakebase_cfg.get("database", "databricks_postgres")
            self._lakebase_endpoint_name = (
                f"projects/{self._lakebase_project_id}"
                f"/branches/{self._lakebase_branch_id}"
                f"/endpoints/{self._lakebase_endpoint_id}"
            )
            self._host = cfg.get("host")

            # 2. Get SP credentials: env vars (Databricks Apps) > secrets API (local dev)
            sp_client_id = get_secret(scope='aichemy', key='client_id')
            sp_client_secret = get_secret(scope='aichemy', key='client_secret')

            if not (sp_client_id and sp_client_secret):
                print("[ProjectDB] SP credentials missing from Databricks secrets. Skipping Lakebase.")
                return False

            # 3. Create SP-authenticated client
            sp_client = WorkspaceClient(
                host=self._host,
                client_id=sp_client_id,
                client_secret=sp_client_secret,
            )
            print(f"[ProjectDB] SP client: {sp_client}")

            # Cache the SP client for token refresh
            self._sp_client = sp_client

            # 4. Resolve endpoint host via Lakebase Autoscaling API
            endpoint = sp_client.postgres.get_endpoint(name=self._lakebase_endpoint_name)
            self._lakebase_host = endpoint.status.hosts.host
            self._lakebase_user = sp_client_id  # SP client_id IS the Postgres role

            # 5. Generate ephemeral OAuth token (1h expiry)
            cred = sp_client.postgres.generate_database_credential(
                endpoint=self._lakebase_endpoint_name,
            )
            # self._lakebase_token = cred.token
            self._lakebase_token = get_secret(scope='aichemy', key='lakebase_as')

            # 6. Test the connection (retry for scale-to-zero wake-up)
            import psycopg
            conninfo = self._build_conninfo()
            self._connect_with_retry(conninfo)

            print(f"[ProjectDB] Lakebase Autoscaling connected: {self._lakebase_host} / {self._lakebase_database}")
            self._use_pg = True
            self._create_pg_tables()
            return True

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._last_lakebase_error = tb
            print(f"[ProjectDB] Lakebase auto-connect failed:\n{tb}")
            self._use_pg = False
            return False

    def _connect_with_retry(self, conninfo: str, max_retries: int = 5, base_delay: float = 1.0):
        """Connect with retry logic for Lakebase Autoscaling scale-to-zero wake-up.

        When compute is scaled to zero, the first connection attempt may fail while
        the compute wakes up (typically a few hundred milliseconds). We retry with
        exponential backoff to handle this gracefully.
        """
        import psycopg
        import time

        last_error = None
        for attempt in range(max_retries):
            try:
                with psycopg.connect(conninfo, connect_timeout=10) as conn:
                    conn.execute("SELECT 1")
                return  # success
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # 1s, 2s, 4s, 8s, 16s
                    print(f"[ProjectDB] Connection attempt {attempt + 1} failed, retrying in {delay}s... ({e})")
                    time.sleep(delay)
        raise last_error

    def _build_conninfo(self) -> str:
        return (
            f"dbname={self._lakebase_database} "
            f"user={self._lakebase_user} "
            f"password={self._lakebase_token} "
            f"host={self._lakebase_host} "
            f"sslmode=require"
        )

    def _refresh_token(self):
        """Refresh the Lakebase OAuth token using the cached SP client."""
        try:
            cred = self._sp_client.postgres.generate_database_credential(
                endpoint=self._lakebase_endpoint_name,
            )
            self._lakebase_token = cred.token
            print("[ProjectDB] Token refreshed successfully")
        except Exception as e:
            print(f"[ProjectDB] Token refresh failed: {e}")

    # -- Initialization -----------------------------------------------------

    def _init_sqlite(self):
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]',
                    agent_steps TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
            conn.commit()

    def _create_pg_tables(self):
        """Create the projects table in Lakebase if it doesn't exist.

        Uses a plain psycopg connection (not the _conn context manager) because
        this runs during init before _use_pg is set. Skips CREATE TABLE if the
        table already exists to avoid ownership conflicts.
        """
        import psycopg
        conninfo = self._build_conninfo()
        with psycopg.connect(conninfo, connect_timeout=10) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'projects'
                )
            """)
            if cur.fetchone()[0]:
                print("[ProjectDB] projects table already exists, skipping CREATE")
                return
            cur.execute("""
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]',
                    agent_steps TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)
            """)
            conn.commit()

    # -- Connection helpers -------------------------------------------------

    @contextmanager
    def _conn(self):
        if self._use_pg:
            import psycopg
            try:
                with psycopg.connect(self._build_conninfo(), connect_timeout=10) as conn:
                    yield conn
            except Exception as e:
                # Token may have expired or compute may have scaled to zero
                print(f"[ProjectDB] Connection failed ({e}), refreshing token and retrying...")
                self._refresh_token()
                try:
                    self._connect_with_retry(self._build_conninfo(), max_retries=3, base_delay=0.5)
                    with psycopg.connect(self._build_conninfo(), connect_timeout=10) as conn:
                        yield conn
                except Exception as retry_err:
                    print(f"[ProjectDB] Retry also failed: {retry_err}")
                    raise
        else:
            conn = sqlite3.connect(self._sqlite_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _cursor(self, conn):
        """Return a cursor. For Postgres, use dict_row factory."""
        if self._use_pg:
            import psycopg.rows
            return conn.cursor(row_factory=psycopg.rows.dict_row)
        return conn.cursor()

    def _placeholder(self) -> str:
        """Return the parameterized query placeholder for the current backend."""
        return "%s" if self._use_pg else "?"

    # -- CRUD ---------------------------------------------------------------

    def list_projects(self, user_id: str) -> list[dict]:
        p = self._placeholder()
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT id, name, created_at, updated_at FROM projects "
                f"WHERE user_id = {p} ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def create_project(self, user_id: str, name: str) -> dict:
        p = self._placeholder()
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"INSERT INTO projects (id, user_id, name, messages, agent_steps, created_at, updated_at) "
                f"VALUES ({p}, {p}, {p}, '[]', '[]', {p}, {p})",
                (project_id, user_id, name, now, now),
            )
            conn.commit()
        return {"id": project_id, "name": name, "messages": [], "agent_steps": [], "created_at": now, "updated_at": now}

    def get_project(self, project_id: str) -> Optional[dict]:
        p = self._placeholder()
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(f"SELECT * FROM projects WHERE id = {p}", (project_id,))
            row = cur.fetchone()
            if row is None:
                return None
            d = dict(row)
            d["messages"] = json.loads(d["messages"])
            d["agent_steps"] = json.loads(d["agent_steps"])
            return d

    def update_project(self, project_id: str, name: Optional[str] = None,
                       messages: Optional[list] = None,
                       agent_steps: Optional[list] = None) -> Optional[dict]:
        p = self._placeholder()
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(f"SELECT id FROM projects WHERE id = {p}", (project_id,))
            if cur.fetchone() is None:
                return None
            now = datetime.now(timezone.utc).isoformat()
            updates: list[str] = [f"updated_at = {p}"]
            params: list = [now]
            if name is not None:
                updates.append(f"name = {p}")
                params.append(name)
            if messages is not None:
                updates.append(f"messages = {p}")
                params.append(json.dumps(messages))
            if agent_steps is not None:
                updates.append(f"agent_steps = {p}")
                params.append(json.dumps(agent_steps))
            params.append(project_id)
            cur.execute(
                f"UPDATE projects SET {', '.join(updates)} WHERE id = {p}", params
            )
            conn.commit()
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        p = self._placeholder()
        with self._conn() as conn:
            cur = self._cursor(conn)
            cur.execute(f"DELETE FROM projects WHERE id = {p}", (project_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="AiChemy API Proxy")

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Databricks client (lazily initialized — only needed for the agent proxy endpoint)
# Host is resolved from: DATABRICKS_HOST env var > config.yml > WorkspaceClient default auth
_workspace_client = None

def _load_config() -> dict:
    """Load config.yml — checks app root first (deployed), then notebooks/ (local dev)."""
    candidates = [
        Path(__file__).resolve().parent.parent / "config.yml",
        Path(__file__).resolve().parent.parent.parent.parent / "notebooks" / "config.yml",
    ]
    for cfg_path in candidates:
        if cfg_path.exists():
            with open(cfg_path) as f:
                return yaml.safe_load(f) or {}
    return {}

def _resolve_databricks_host() -> Optional[str]:
    """Resolve Databricks host from env var or config.yml (None lets SDK use default auth)."""
    host = os.getenv("DATABRICKS_HOST")
    if host:
        return host
    return _load_config().get("host")

DATABRICKS_HOST = _resolve_databricks_host()

def _get_workspace_client() -> WorkspaceClient:
    global _workspace_client
    try:
        _workspace_client = db._sp_client
    except Exception as e:
        kwargs = {}
        if DATABRICKS_HOST:
            kwargs["host"] = DATABRICKS_HOST
        _workspace_client = WorkspaceClient(**kwargs)
    return _workspace_client

# Initialize project database — runs at import time (before the async event loop
# starts) to avoid generator/async conflicts with the synchronous SDK + psycopg calls.
db = ProjectDB(sqlite_path=os.getenv("PROJECTS_DB_PATH", "projects.db"))
db.init()

# ---------------------------------------------------------------------------
# User identity — cached after first resolution
# Priority: Databricks forwarded headers > Databricks CLI auth > env vars > defaults
# ---------------------------------------------------------------------------

_cached_user_info: Optional[dict] = None


def _resolve_local_user() -> dict:
    """Try to get the current user from Databricks CLI auth, with fallbacks."""
    global _cached_user_info
    if _cached_user_info is not None:
        return _cached_user_info

    # Try Databricks SDK (uses CLI auth / env config)
    try:
        w = _get_workspace_client()
        me = w.current_user.me()
        _cached_user_info = {
            "user_name": me.display_name or me.user_name or "Unknown",
            "user_email": me.user_name or "",  # user_name is typically the email
            "user_id": me.user_name or str(me.id),
        }
        return _cached_user_info
    except Exception:
        pass

    # Fall back to env vars (no built-in defaults — requires Databricks auth)
    _cached_user_info = {
        "user_name": os.getenv("DEFAULT_USER_NAME"),
        "user_email": os.getenv("DEFAULT_USER_EMAIL"),
        "user_id": os.getenv("DEFAULT_USER_ID"),
    }
    return _cached_user_info


@app.get("/api/user")
async def get_user(request: Request):
    """Return the current user identity.

    In Databricks Apps, the platform injects X-Forwarded-* headers.
    Locally, resolves from Databricks CLI auth (cached after first call).
    """
    # Production: Databricks Apps forwards headers
    forwarded_user = request.headers.get("X-Forwarded-User")
    if forwarded_user:
        return {
            "user_name": request.headers.get("X-Forwarded-Preferred-Username") or forwarded_user,
            "user_email": request.headers.get("X-Forwarded-Email") or forwarded_user,
            "user_id": forwarded_user,
        }

    # Local dev: resolve from Databricks CLI auth
    return _resolve_local_user()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str
    content: str

class CustomInputs(BaseModel):
    thread_id: str

class AgentRequest(BaseModel):
    input: List[Message]
    custom_inputs: CustomInputs
    skill_name: Optional[str] = None  # When set, wraps the prompt with skill instructions
    new_thread: Optional[bool] = None  # True = first message in thread; only then stream every item

class CreateProjectRequest(BaseModel):
    name: str
    user_id: Optional[str] = None

class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    messages: Optional[list] = None
    agent_steps: Union[list, dict, None] = None  # frontend sends {toolCallGroups, genieGroups}

# ---------------------------------------------------------------------------
# Agent proxy endpoint
# Set MOCK_AGENT=1 to return a canned response (for local dev without Databricks auth)
# ---------------------------------------------------------------------------
# Agent server: agent/start_server.py (MLflow AgentServer) listens on 8080 /invocations.
# This backend proxies /api/agent and /api/agent/stream to that endpoint.
# ---------------------------------------------------------------------------
# Entry point for the MLflow agent (run with: python agent/start_server.py --port <AGENT_PORT>)
AGENT_PORT = os.getenv("AGENT_PORT", "8080")
AGENT_URL = f"http://0.0.0.0:{AGENT_PORT}/invocations"
# Timeout for web server -> agent requests (seconds). Prevents indefinite hang and generic "network error".
# Split into (connect, read): short connect timeout, longer read timeout for slow MCP/Genie queries.
AGENT_CONNECT_TIMEOUT = int(os.getenv("AGENT_CONNECT_TIMEOUT", "30"))
AGENT_READ_TIMEOUT = int(os.getenv("AGENT_READ_TIMEOUT", "600"))
AGENT_REQUEST_TIMEOUT = AGENT_CONNECT_TIMEOUT + AGENT_READ_TIMEOUT


@app.post("/api/agent/stream")
async def call_agent_stream(request: AgentRequest):
    """Stream agent response as Server-Sent Events (SSE).
    
    Each SSE event is a JSON object with a `type` field:
      - {"type": "text", "content": "..."} — a text chunk to append
      - {"type": "trace_id", "trace_id": "tr-..."} — trace id
    # Not in streamed response
    #   - {"type": "tool_calls", "data": [...]}  — parsed tool calls
    #   - {"type": "genie", "data": [...]}       — parsed genie SQL results
      - {"type": "done"}                       — stream complete
    # Not in streamed response
    #  - {"type": "error", "content": "..."}    — error occurred
    """

    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def stream_generator():
        try:
            # If skills are enabled, wrap the user prompt with skill instructions
            messages = [{"role": msg.role, "content": msg.content} for msg in request.input]
            if request.skill_name and messages:
                last_msg = messages[-1]
                enhanced = build_prompt_with_skill(last_msg["content"], request.skill_name)
                messages[-1] = {"role": last_msg["role"], "content": enhanced}

            input_dict = {
                "input": messages,
                "custom_inputs": {"thread_id": request.custom_inputs.thread_id},
                "databricks_options": {"return_trace": True},
                "stream": True,
            }

            print(f"Input_dict: {input_dict}")
            w = _get_workspace_client()
            url = AGENT_URL
            headers = w.config.authenticate()
            headers["Content-Type"] = "application/json"
            headers["x-mlflow-return-trace-id"] = "true"

            yield _sse({"type": "status", "content": "Waiting for agent..."})

            try:
                resp = requests.post(
                    url=url, headers=headers, json=input_dict, timeout=AGENT_REQUEST_TIMEOUT, stream=True
                )
            except requests.exceptions.Timeout:
                yield _sse({
                    "type": "error",
                    "content": f"Agent request timed out after {AGENT_READ_TIMEOUT}s. Try again or increase AGENT_READ_TIMEOUT.",
                })
                return

            if resp.status_code != 200:
                body = resp.text if not resp.raw.closed else ""
                yield _sse({"type": "error", "content": f"{resp.status_code}: {body[:500]}"})
                return

            yield _sse({"type": "status", "content": "Streaming response..."})

            # Agent returns SSE: data: {"type": "response.output_item.done", "item": {...}},
            # data: {"trace_id": "tr-..."}, then data: [DONE]
            # With the same thread_id the agent may resend all prior turns; only stream the last item (current turn).
            # For a new thread (new_thread=True) we stream every item as it arrives (no prior turns to skip).
            is_new_thread = request.new_thread is True
            accumulated_output = []
            trace_id = None

            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if not payload:
                    continue
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                ev_type = event.get("type")
                if ev_type == "response.output_item.done":
                    item = event.get("item")
                    if item:
                        accumulated_output.append(item)
                        if is_new_thread:
                            yield from stream_new_content(item, _sse)
                elif ev_type == "error":
                    yield _sse({"type": "error", "content": event.get("message", str(event))})
                    return
                elif "trace_id" in event:
                    trace_id = event["trace_id"]

            # Response fully consumed — use trace_id from stream if present
            if trace_id:
                print(f"trace_id: {trace_id}")

            # Existing thread: stream only the last message item to avoid repeating previous responses
            if not is_new_thread and accumulated_output:
                last_msg = next(
                    (it for it in reversed(accumulated_output)
                     if it.get("type") == "message"
                     and any(b.get("type") == "output_text" for b in it.get("content") or [])),
                    accumulated_output[-1],
                )
                yield from stream_new_content(last_msg, _sse)

            # Parse the trace for tool_calls and genie results
            if trace_id:
                trace = get_trace(trace_id, retries=3, delay=1.0)
                if trace:
                    parsed = parse_trace_for_ui(_serialize_trace(trace))
                    print(f"parsed: {parsed}")
                    if parsed["tool_calls"]:
                        yield _sse({"type": "tool_calls", "data": parsed["tool_calls"]})
                    if parsed["genie_results"]:
                        yield _sse({"type": "genie", "data": parsed["genie_results"]})
                yield _sse({"type": "trace_id", "trace_id": trace_id})

        except Exception as e:
            yield _sse({"type": "error", "content": str(e)})

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# MLflow Trace endpoint
# ---------------------------------------------------------------------------

def _safe_json(obj):
    """Convert an object to a JSON-safe value. Falls back to str() for unpicklable objects."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError, OverflowError):
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


def _serialize_trace(trace) -> dict:
    """Convert an MLflow Trace object to a JSON-serializable dict."""
    info = trace.info
    spans = []
    for s in (trace.data.spans if trace.data else []):
        attrs = {}
        try:
            for k, v in (s.attributes or {}).items():
                attrs[str(k)] = _safe_json(v)
        except Exception:
            pass
        spans.append({
            "name": getattr(s, "name", None),
            "span_id": getattr(s, "span_id", None),
            "parent_id": getattr(s, "parent_id", None),
            "status": str(getattr(s, "status", "")),
            "start_time_ns": getattr(s, "start_time_ns", None),
            "end_time_ns": getattr(s, "end_time_ns", None),
            "inputs": _safe_json(getattr(s, "inputs", None)),
            "outputs": _safe_json(getattr(s, "outputs", None)),
            "attributes": attrs,
        })
    return {
        "trace_id": getattr(info, "trace_id", None),
        "status": str(getattr(info, "state", "")),
        "execution_time_ms": getattr(info, "execution_duration", None),
        "request_time": getattr(info, "request_time", None),
        "tags": dict(info.tags) if getattr(info, "tags", None) else {},
        "spans": spans,
    }


@app.get("/api/trace/{trace_id}")
async def api_get_trace(trace_id: str):
    """Fetch an MLflow trace by ID (with retries for async write delay)."""
    import asyncio
    loop = asyncio.get_running_loop()
    trace = await loop.run_in_executor(None, get_trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found after retries")
    return _serialize_trace(trace)


# ---------------------------------------------------------------------------
# Project CRUD endpoints
# ---------------------------------------------------------------------------

@app.get("/api/projects")
async def list_projects(user_id: str = Query(default=None)):
    """List all projects for a user, ordered by most recently updated."""
    uid = user_id or _resolve_local_user()["user_id"]
    return db.list_projects(uid)

@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project. Returns the full project object."""
    uid = req.user_id or _resolve_local_user()["user_id"]
    return db.create_project(uid, req.name)

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Load a project with its full messages and agent steps."""
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    """Update a project's name, messages, and/or agent steps."""
    project = db.update_project(
        project_id,
        name=req.name,
        messages=req.messages,
        agent_steps=req.agent_steps,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project."""
    deleted = db.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}

# ---------------------------------------------------------------------------
# Response parsing helpers (mirrors Streamlit utils.py)
# ---------------------------------------------------------------------------
def strip_tool_call_tags(text_content: str) -> str:
    """Strip <function_calls>, <thinking>, and <results> tags from text."""
    text_content = re.sub(r'<function_calls>.*?</function_calls>', '', text_content, flags=re.DOTALL)
    text_content = re.sub(r'<thinking>.*?</thinking>', '', text_content, flags=re.DOTALL)
    text_content = re.sub(r'<results>.*?</results>', '', text_content, flags=re.DOTALL)
    text_content = re.sub(r'<results>.*', '', text_content, flags=re.DOTALL)
    text_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', text_content)
    return text_content.strip()


def stream_new_content(item: Optional[dict], _sse):
    """Yield SSE events for one response item's text in chunks. Skips tool-call tags."""
    import time
    if not item:
        return
    for block in item.get("content") or []:
        if block.get("type") == "output_text":
            text = block.get("text") or ""
            if text:
                cleaned = strip_tool_call_tags(text)
                if cleaned:
                    words = cleaned.split(" ")
                    for i, word in enumerate(words):
                        chunk = word + (" " if i < len(words) - 1 else "")
                        yield _sse({"type": "text", "content": chunk})
                        time.sleep(0.02)


def parse_genie_results(trace_dict: dict) -> list[dict]:
    """Extract Genie query results from poll_query_results spans in a serialized trace.

    Accepts the dict returned by _serialize_trace() (spans at top level,
    outputs already deserialized).
    """
    results = []
    for span in trace_dict.get("spans", []):
        if span.get("name") != "poll_query_results":
            continue
        outputs = span.get("outputs")
        if isinstance(outputs, dict) and outputs.get("result"):
            results.append({
                "result": outputs.get("result", ""),
                "query": outputs.get("query", ""),
                "description": outputs.get("description", ""),
            })
    return results


def extract_text_content(response_json: dict) -> list[str]:
    """Extract the final (supervisor) text from the agent response.

    In a multi-agent workflow the last message output is the supervisor's
    consolidated summary.  Earlier messages are intermediate sub-agent
    outputs and should not be shown to the user.
    """
    last_text = None
    for item in response_json.get("output", []):
        if item.get("type") == "message":
            text = item.get("content", [{}])[0].get("text")
            if text:
                last_text = text
    return [last_text] if last_text else []


def extract_all_tool_calls(trace_dict: dict) -> list[dict]:
    """Extract tool calls from a serialized trace.

    Checks three sources (in order):
    1. Spans named ``"tools"`` whose ``inputs`` contain a ``tool_call`` dict
       with ``name`` and ``args`` (OpenAI Responses-style traces).
    2. Message text in the root span's outputs for ``<function_calls>`` XML
       blocks (Claude-style traces).
    3. Direct child spans of the root, treated as function invocations
       (fallback for other span layouts).
    """
    all_tool_calls = []
    spans = trace_dict.get("spans", [])

    for span in spans:
        if span.get("name") == "tools":
            inputs = span.get("inputs", {})
            tool_call = inputs.get("tool_call")
            if isinstance(tool_call, dict):
                tc_name = tool_call.get("name")
                try:
                    results = span.get("outputs").get("messages")[0].get("content")
                except Exception:
                    results = None
                if tool_call.get("args", {})=={} and results is None:
                    continue
                else:
                    all_tool_calls.append({
                        "function_name": tc_name,
                        "parameters": tool_call.get("args"),
                        "results": results
                    })
    return all_tool_calls


def parse_trace_for_ui(trace_dict: dict) -> dict:
    """Parse a serialized trace for tool_calls and genie_results.

    ``trace_dict`` is the dict returned by ``_serialize_trace()`` (or the
    ``/api/trace/<id>`` endpoint).  Returns a dict with ``tool_calls`` and
    ``genie_results`` lists ready for SSE emission.
    """
    return {
        "tool_calls": extract_all_tool_calls(trace_dict),
        "genie_results": parse_genie_results(trace_dict),
    }


# ---------------------------------------------------------------------------
# Tools endpoint — serve the tools manifest
# ---------------------------------------------------------------------------

# Locate tools.txt – check react-app root first (deployed), then Streamlit app dir (local dev)
_tools_candidates = [
    Path(__file__).resolve().parent.parent / "tools.txt",           # react-app/tools.txt
    Path(__file__).resolve().parent.parent.parent / "app" / "tools.txt",  # apps/app/tools.txt
]
_TOOLS_PATH = next((p for p in _tools_candidates if p.exists()), _tools_candidates[0])

@app.get("/api/tools")
async def get_tools():
    """Return available tools grouped by agent, loaded from tools.txt."""
    if not _TOOLS_PATH.exists():
        return []
    groups: dict[str, list[dict]] = {}
    with open(_TOOLS_PATH) as f:
        for i, line in enumerate(f):
            if i == 0:
                continue  # skip header
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                agent, tool_name, description = parts[0], parts[1], parts[2]
                groups.setdefault(agent, []).append({"name": tool_name, "description": description})
    return groups

# ---------------------------------------------------------------------------
# Skills – discover, load, and build prompts with skill instructions
# ---------------------------------------------------------------------------

# Skills directory — check app root first (deployed), then Streamlit app location (local dev)
_skills_candidates = [
    Path(__file__).resolve().parent.parent / "skills",
    Path(__file__).resolve().parent.parent.parent / "app" / "skills",
]
_SKILLS_DIR = next((p for p in _skills_candidates if p.exists()), _skills_candidates[0])


def _smart_title(s: str) -> str:
    """Title-case words, but leave fully uppercase words (e.g. ADME) unchanged."""
    return " ".join(w if w.isupper() else w.title() for w in s.split())


def _parse_skill_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter (between --- delimiters) from a SKILL.md file."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if match:
        try:
            return yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            pass
    return {}


def discover_skills(skills_dir: Optional[Union[str, Path]] = None) -> dict:
    """Scan the skills directory and return metadata keyed by skill folder name."""
    skills_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR
    skills: dict[str, dict] = {}
    if not skills_dir.exists():
        return skills

    for folder in skills_dir.iterdir():
        if not folder.is_dir():
            continue
        skill_file = folder / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            content = skill_file.read_text(encoding="utf-8")
            fm = _parse_skill_frontmatter(content)
            name = fm.get("name", folder.name)
            description = fm.get("description", "")

            # Assign emoji + ordering based on skill type
            lower = name.lower()
            if "target" in lower:
                label, order = f"🎯 {_smart_title(name.replace('-', ' '))}", 0
            elif "hit" in lower:
                label, order = f"⌬ {_smart_title(name.replace('-', ' '))}", 1
            elif "adme" in lower:
                label, order = f"🧪 {_smart_title(name.replace('-', ' '))}", 2
            elif "safety" in lower:
                label, order = f"☠️ {_smart_title(name.replace('-', ' '))}", 3
            else:
                label, order = f"📋 {_smart_title(name.replace('-', ' '))}", 4

            caption = description.split(". ")[0] if description else ""
            if len(caption) > 70:
                caption = caption[:67] + "..."

            skills[name] = {
                "description": description,
                "path": str(folder),
                "label": label,
                "caption": caption,
                "order": order,
            }
        except Exception:
            continue
    return skills


def load_skill_content(skill_name: str, skills_dir: Optional[Union[str, Path]] = None) -> Optional[dict]:
    """Load full SKILL.md + reference files for a given skill."""
    skills_dir = Path(skills_dir) if skills_dir else _SKILLS_DIR
    skill_path = skills_dir / skill_name
    skill_file = skill_path / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        full_content = skill_file.read_text(encoding="utf-8")
        fm = _parse_skill_frontmatter(full_content)
        match = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", full_content, re.DOTALL)
        body = match.group(1).strip() if match else full_content

        # Load reference files
        references: dict[str, str] = {}
        refs_dir = skill_path / "references"
        if refs_dir.exists():
            for ref_file in refs_dir.iterdir():
                if ref_file.is_file() and ref_file.suffix == ".md":
                    try:
                        references[ref_file.name] = ref_file.read_text(encoding="utf-8")
                    except Exception:
                        continue

        full_prompt = f"# Skill: {fm.get('name', skill_name)}\n\n{body}"
        if references:
            full_prompt += "\n\n---\n\n## Reference Materials\n\n"
            for ref_name, ref_content in references.items():
                full_prompt += f"### {ref_name}\n\n{ref_content}\n\n"

        return {"frontmatter": fm, "content": body, "references": references, "full_prompt": full_prompt}
    except Exception:
        return None


def build_prompt_with_skill(user_query: str, skill_name: str, skills_dir: Optional[Union[str, Path]] = None) -> str:
    """Wrap a user query with skill instructions if the skill exists."""
    skill_data = load_skill_content(skill_name, skills_dir)
    if not skill_data:
        return user_query
    return (
        "You have been given a specialized skill to help with this task. "
        "Follow the workflow instructions carefully.\n\n"
        f"<skill_instructions>\n{skill_data['full_prompt']}\n</skill_instructions>\n\n"
        f"<user_request>\n{user_query}\n</user_request>\n\n"
        "Execute the skill workflow to address the user's request. "
        "Follow each step methodically and provide the expected output format."
    )


def extract_user_request(prompt: str) -> str:
    """Extract the user query from <user_request> tags, or return the original prompt."""
    match = re.search(r"<user_request>\s*(.*?)\s*</user_request>", prompt, re.DOTALL)
    return match.group(1).strip() if match else prompt


# Skill-name → workflow-index mapping for determining which skill folder to use
_SKILL_FOLDER_BY_WORKFLOW_IDX = {
    0: "target-identification",
    1: "hit-identification",
    2: "ADME-assessment",
    3: "safety-assessment",
}


@app.get("/api/skills")
async def get_skills():
    """Return discovered skills metadata (sorted by order)."""
    skills = discover_skills()
    sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("order", 99))
    return {
        "skills": {name: meta for name, meta in sorted_skills},
        "labels": [meta["label"] for _, meta in sorted_skills],
        "captions": [meta["caption"] for _, meta in sorted_skills],
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    """Health check endpoint — also reports which DB backend is active."""
    if db._use_pg:
        db_backend = "lakebase-autoscaling"
        db_detail = f"{db._lakebase_endpoint_name} / {db._lakebase_database}"
    else:
        db_backend = "sqlite"
        db_detail = db._sqlite_path
    result = {
        "status": "healthy",
        "host": DATABRICKS_HOST or "(resolved by SDK auth)",
        "db_backend": db_backend,
        "db_detail": db_detail,
    }
    if db._last_lakebase_error:
        result["lakebase_init_error"] = db._last_lakebase_error
    return result

# ---------------------------------------------------------------------------
# Agent status + warmup — proxied from the AgentServer
# ---------------------------------------------------------------------------

@app.get("/api/agent/status")
async def agent_status():
    """Proxy agent readiness check to the AgentServer."""
    try:
        resp = requests.get(
            f"http://0.0.0.0:{AGENT_PORT}/agent-status",
            timeout=5,
        )
        return resp.json()
    except Exception:
        return {"ready": False, "building": True, "error": None}


@app.post("/api/agent/warmup")
async def agent_warmup():
    """Trigger a warmup query on the AgentServer."""
    try:
        resp = requests.post(
            f"http://0.0.0.0:{AGENT_PORT}/agent-warmup",
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"ok": False, "detail": str(e)}


# ---------------------------------------------------------------------------
# Lakebase diagnostic endpoint — step-by-step connection test
# ---------------------------------------------------------------------------

@app.get("/api/debug/lakebase")
async def debug_lakebase(request: Request):
    """Run each Lakebase connection step individually and report where it fails."""
    import databricks.sdk
    steps = {"0_env": {
        "sdk_version": getattr(databricks.sdk, "__version__", "unknown"),
        "startup_error": db._last_lakebase_error,
    }}

    # Step 1: config.yml
    try:
        cfg = _load_config()
        lakebase_cfg = cfg.get("lakebase", {}) if cfg else {}
        steps["1_config"] = {
            "ok": bool(lakebase_cfg.get("project_id")),
            "project_id": lakebase_cfg.get("project_id"),
            "branch_id": lakebase_cfg.get("branch_id"),
            "endpoint_id": lakebase_cfg.get("endpoint_id"),
            "database": lakebase_cfg.get("database"),
            "host": cfg.get("host") if cfg else None,
        }
    except Exception as e:
        steps["1_config"] = {"ok": False, "error": str(e)}

    # Step 2: SP credentials
    try:
        sp_client_id = os.getenv("SP_CLIENT_ID")
        sp_client_secret = os.getenv("SP_CLIENT_SECRET")
        source = "env"
        if not (sp_client_id and sp_client_secret):
            from base64 import b64decode
            w = _get_workspace_client()
            sp_id_b64 = w.secrets.get_secret("aichemy", "client_id").value
            sp_secret_b64 = w.secrets.get_secret("aichemy", "client_secret").value
            sp_client_id = b64decode(sp_id_b64).decode("utf-8")
            sp_client_secret = b64decode(sp_secret_b64).decode("utf-8")
            source = "secrets_api"
        steps["2_sp_credentials"] = {
            "ok": True,
            "source": source,
            "client_id_prefix": sp_client_id[:8] + "..." if sp_client_id else None,
        }
    except Exception as e:
        steps["2_sp_credentials"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 2"}

    # Step 3: SP-authenticated WorkspaceClient
    try:
        host = (cfg or {}).get("host")
        sp_client = WorkspaceClient(
            host=host,
            client_id=sp_client_id,
            client_secret=sp_client_secret,
        )
        steps["3_sp_client"] = {"ok": True, "host": host}
    except Exception as e:
        steps["3_sp_client"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 3"}

    # Step 4: Resolve Lakebase endpoint
    try:
        endpoint_name = (
            f"projects/{lakebase_cfg['project_id']}"
            f"/branches/{lakebase_cfg.get('branch_id', 'main')}"
            f"/endpoints/{lakebase_cfg.get('endpoint_id', 'primary')}"
        )
        endpoint = sp_client.postgres.get_endpoint(name=endpoint_name)
        pg_host = endpoint.status.hosts.host
        steps["4_endpoint"] = {"ok": True, "pg_host": pg_host, "endpoint_name": endpoint_name}
    except Exception as e:
        steps["4_endpoint"] = {"ok": False, "error": str(e), "endpoint_name": endpoint_name}
        return {"steps": steps, "result": "FAILED at step 4"}

    # Step 5: Generate OAuth token
    try:
        cred = sp_client.postgres.generate_database_credential(endpoint=endpoint_name)
        steps["5_token"] = {"ok": True, "token_length": len(cred.token) if cred.token else 0}
    except Exception as e:
        steps["5_token"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 5"}

    # Step 6: Postgres connection test
    try:
        import psycopg
        database = lakebase_cfg.get("database", "databricks_postgres")
        conninfo = (
            f"dbname={database} "
            f"user={sp_client_id} "
            f"password={cred.token} "
            f"host={pg_host} "
            f"sslmode=require"
        )
        with psycopg.connect(conninfo, connect_timeout=10) as conn:
            conn.execute("SELECT 1")
        steps["6_pg_connect"] = {"ok": True, "database": database}
    except Exception as e:
        steps["6_pg_connect"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 6"}

    return {"steps": steps, "result": "ALL STEPS PASSED"}

# ---------------------------------------------------------------------------
# Static file serving — serves the built React frontend (dist/)
# Must be mounted LAST so /api routes take priority.
# ---------------------------------------------------------------------------

_dist_dir = _app_root / "dist"

if _dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=_dist_dir / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA — all non-API routes fall through to index.html."""
        file_path = _dist_dir / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_dist_dir / "index.html")
else:
    # No dist/ — e.g. backend-only or frontend not built yet. Avoid 404 on /
    @app.get("/")
    async def root_no_dist():
        return HTMLResponse(
            "<!DOCTYPE html><html><head><title>AiChemy</title></head><body>"
            "<h1>AiChemy backend</h1><p>React frontend not built. "
            "Run <code>npm run build</code> in the app directory, or use the API:</p>"
            "<ul><li><a href='/api/health'>/api/health</a></li>"
            "<li><a href='/api/projects'>/api/projects</a></li></ul></body></html>"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DATABRICKS_APP_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
