"""
Backend proxy server for AiChemy React app.
Handles Databricks authentication, proxies requests to the agent endpoint,
and persists project metadata to Lakebase Autoscaling Postgres.

Long-term user memory (facts, preferences) is handled separately by the agent
backend via AsyncDatabricksStore (LangGraph postgres store).

The agent endpoint (POST /invocations) is served by agent/start_server.py (MLflow AgentServer).
Port is set via AGENT_PORT (default 8080). Run separately: python agent/start_server.py --port <AGENT_PORT>
"""

import os
import json
import requests
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from databricks.sdk import WorkspaceClient
import sys

_app_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_app_root))

from agent.utils import load_env_from_app_yaml, init_mlflow, get_secret_from_cfg, get_trace, load_config
from server.utils_web import (
    resolve_databricks_host,
    resolve_user_from_request,
    serialize_trace,
    stream_new_content,
    parse_trace_for_ui,
    extract_text_from_trace,
    build_prompt_with_skill,
    discover_skills,
    check_all_mcp_servers,
)
from server.utils_lakebase import ProjectDB
from server.dataclass import (
    AgentRequest,
    CreateProjectRequest,
    UpdateProjectRequest,
)

load_env_from_app_yaml()
init_mlflow()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="AiChemy API Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080", "http://localhost:3000", "http://localhost:5173",
        "http://127.0.0.1:3000", "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_workspace_client = None
DATABRICKS_HOST = resolve_databricks_host()


def _get_workspace_client() -> WorkspaceClient:
    global _workspace_client
    if _workspace_client is not None:
        return _workspace_client
    try:
        _workspace_client = WorkspaceClient()
    except Exception:
        if db._sp_client is not None:
            _workspace_client = db._sp_client
        else:
            raise
    return _workspace_client


db = ProjectDB()

# Agent server settings
AGENT_PORT = os.getenv("AGENT_PORT", "8080")
AGENT_URL = f"http://0.0.0.0:{AGENT_PORT}/invocations"
AGENT_CONNECT_TIMEOUT = int(os.getenv("AGENT_CONNECT_TIMEOUT", "30"))
AGENT_READ_TIMEOUT = int(os.getenv("AGENT_READ_TIMEOUT", "600"))
AGENT_REQUEST_TIMEOUT = AGENT_CONNECT_TIMEOUT + AGENT_READ_TIMEOUT


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/user")
async def get_user(request: Request):
    """Return the current user identity (from proxy headers or SDK auth)."""
    return resolve_user_from_request(request, _get_workspace_client)


@app.post("/api/agent/stream")
async def call_agent_stream(request: AgentRequest):
    """Stream agent response as Server-Sent Events (SSE)."""

    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def stream_generator():
        try:
            messages = [{"role": msg.role, "content": msg.content} for msg in request.input]
            if request.skill_name and messages:
                last_msg = messages[-1]
                enhanced = build_prompt_with_skill(last_msg["content"], request.skill_name)
                messages[-1] = {"role": last_msg["role"], "content": enhanced}

            custom_inputs = {"thread_id": request.custom_inputs.thread_id}
            if request.custom_inputs.user_id:
                custom_inputs["user_id"] = request.custom_inputs.user_id

            input_dict = {"input": messages, "custom_inputs": custom_inputs, "stream": True}

            print(f"Input_dict: {input_dict}")
            w = _get_workspace_client()
            headers = w.config.authenticate()
            headers["Content-Type"] = "application/json"
            headers["x-mlflow-return-trace-id"] = "true"

            yield _sse({"type": "status", "content": "Waiting for agent..."})

            try:
                resp = requests.post(
                    url=AGENT_URL, headers=headers, json=input_dict,
                    timeout=AGENT_REQUEST_TIMEOUT, stream=True,
                )
            except requests.exceptions.Timeout:
                yield _sse({"type": "error", "content": f"Agent request timed out after {AGENT_READ_TIMEOUT}s. Try again or increase AGENT_READ_TIMEOUT."})
                return

            if resp.status_code != 200:
                body = resp.text if not resp.raw.closed else ""
                yield _sse({"type": "error", "content": f"{resp.status_code}: {body[:500]}"})
                return

            yield _sse({"type": "status", "content": "Streaming response..."})

            is_new_thread = request.new_thread is True
            accumulated_output = []
            trace_id = None

            seen_event_types = []
            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        break
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                ev_type = event.get("type")
                seen_event_types.append(ev_type)
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

            print(f"[stream] SSE event types received: {seen_event_types}")
            print(f"[stream] accumulated_output items: {len(accumulated_output)}, trace_id: {trace_id}")

            if not is_new_thread and accumulated_output:
                last_msg = next(
                    (it for it in reversed(accumulated_output)
                     if it.get("type") == "message"
                     and any(b.get("type") == "output_text" for b in it.get("content") or [])),
                    accumulated_output[-1],
                )
                yield from stream_new_content(last_msg, _sse)

            if trace_id:
                print(f"trace_id: {trace_id}")
                yield _sse({"type": "trace_id", "trace_id": trace_id})

            if not accumulated_output and trace_id:
                yield from _fallback_from_trace(trace_id, _sse)
            elif not accumulated_output:
                yield _sse({"type": "error", "content": "Agent stream ended without producing output. Check agent logs for details."})
            elif trace_id:
                yield from _enrich_from_trace(trace_id, _sse)

        except requests.exceptions.ConnectionError as e:
            yield _sse({"type": "error", "content": f"Lost connection to agent server: {e}"})
        except Exception as e:
            yield _sse({"type": "error", "content": f"{type(e).__name__}: {e}"})

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


def _fallback_from_trace(trace_id: str, _sse):
    """When SSE produced no output, extract response text from the trace."""
    print(f"[stream] No output from SSE events, falling back to trace extraction...")
    try:
        trace = get_trace(trace_id, retries=5, delay=2.0)
        if trace:
            trace_dict = serialize_trace(trace)
            parsed = parse_trace_for_ui(trace_dict)
            if parsed["tool_calls"]:
                yield _sse({"type": "tool_calls", "data": parsed["tool_calls"]})
            if parsed["genie_results"]:
                yield _sse({"type": "genie", "data": parsed["genie_results"]})
            fallback_text = extract_text_from_trace(trace_dict)
            if fallback_text:
                yield _sse({"type": "text", "content": fallback_text})
            else:
                yield _sse({"type": "error", "content": "Agent produced a trace but no readable output was found."})
        else:
            yield _sse({"type": "error", "content": "Agent stream ended without producing output. Check agent logs for details."})
    except Exception as e:
        print(f"[stream] Failed to parse trace {trace_id}: {e}")
        yield _sse({"type": "error", "content": f"Failed to extract output from trace: {e}"})


def _enrich_from_trace(trace_id: str, _sse):
    """Normal path: SSE worked, parse trace for tool_calls/genie metadata."""
    try:
        trace = get_trace(trace_id, retries=3, delay=1.0)
        if trace:
            parsed = parse_trace_for_ui(serialize_trace(trace))
            print(f"parsed: {parsed}")
            if parsed["tool_calls"]:
                yield _sse({"type": "tool_calls", "data": parsed["tool_calls"]})
            if parsed["genie_results"]:
                yield _sse({"type": "genie", "data": parsed["genie_results"]})
    except Exception as e:
        print(f"[stream] Failed to parse trace {trace_id}: {e}")


@app.get("/api/trace/{trace_id}")
async def api_get_trace(trace_id: str):
    """Fetch an MLflow trace by ID (with retries for async write delay)."""
    import asyncio
    import functools

    loop = asyncio.get_running_loop()
    trace = await loop.run_in_executor(
        None, functools.partial(get_trace, trace_id, retries=5, delay=2)
    )
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found after retries")
    return serialize_trace(trace)


# -- Project CRUD ----------------------------------------------------------


@app.get("/api/projects")
async def list_projects(request: Request, user_id: str = Query(default=None)):
    uid = user_id or resolve_user_from_request(request, _get_workspace_client)["user_id"]
    return db.list_projects(uid)


@app.post("/api/projects")
async def create_project(request: Request, req: CreateProjectRequest):
    uid = req.user_id or resolve_user_from_request(request, _get_workspace_client)["user_id"]
    return db.create_project(uid, req.name)


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    project = db.update_project(project_id, name=req.name, messages=req.messages, agent_steps=req.agent_steps)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    if not db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# -- Tools, Skills, Health --------------------------------------------------


@app.get("/api/tools")
async def get_tools():
    try:
        resp = requests.get(f"http://0.0.0.0:{AGENT_PORT}/agent-tools", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


@app.get("/api/skills")
async def get_skills():
    skills = discover_skills()
    sorted_skills = sorted(skills.items(), key=lambda x: x[0].lower())
    return {name: meta for name, meta in sorted_skills}


@app.get("/api/health")
async def health_check():
    result = {
        "status": "healthy",
        "host": DATABRICKS_HOST or "(resolved by SDK auth)",
        "db_backend": "lakebase-autoscaling",
        "db_detail": f"{db._lakebase_endpoint_name} / {db._lakebase_database}",
        "agent_memory": "AsyncDatabricksStore (Lakebase)",
    }
    if db._last_lakebase_error:
        result["lakebase_init_error"] = db._last_lakebase_error

    mcp_results = await check_all_mcp_servers()
    if mcp_results:
        result["mcp_servers"] = mcp_results
        if any(not s["ok"] for s in mcp_results):
            result["status"] = "degraded"
    return result


@app.get("/api/mcp/status")
async def mcp_status():
    return {"servers": await check_all_mcp_servers()}


@app.get("/api/agent/status")
async def agent_status():
    try:
        resp = requests.get(f"http://0.0.0.0:{AGENT_PORT}/agent-status", timeout=5)
        return resp.json()
    except Exception:
        return {"ready": False, "building": True, "error": None}


@app.post("/api/agent/warmup")
async def agent_warmup():
    try:
        resp = requests.post(f"http://0.0.0.0:{AGENT_PORT}/agent-warmup", timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "detail": str(e)}


@app.get("/api/debug/lakebase")
async def debug_lakebase(request: Request):
    """Run each Lakebase connection step individually and report where it fails."""
    import databricks.sdk
    import psycopg

    steps = {
        "0_env": {
            "sdk_version": getattr(databricks.sdk, "__version__", "unknown"),
            "startup_error": db._last_lakebase_error,
        }
    }

    try:
        cfg = load_config()
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

    try:
        sp_client_id, sp_client_secret = get_secret_from_cfg(cfg)
        steps["2_sp_credentials"] = {
            "ok": bool(sp_client_id and sp_client_secret),
            "client_id_prefix": sp_client_id[:8] + "..." if sp_client_id else None,
        }
    except Exception as e:
        steps["2_sp_credentials"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 2"}

    try:
        host = (cfg or {}).get("host")
        sp_client = WorkspaceClient(host=host, client_id=sp_client_id, client_secret=sp_client_secret)
        steps["3_sp_client"] = {"ok": True, "host": host}
    except Exception as e:
        steps["3_sp_client"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 3"}

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

    try:
        cred = sp_client.postgres.generate_database_credential(endpoint=endpoint_name)
        steps["5_token"] = {"ok": True, "token_length": len(cred.token) if cred.token else 0}
    except Exception as e:
        steps["5_token"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 5"}

    try:
        database = lakebase_cfg.get("database", "databricks_postgres")
        conninfo = (
            f"dbname={database} user={sp_client_id} password={cred.token} "
            f"host={pg_host} sslmode=require"
        )
        with psycopg.connect(conninfo, connect_timeout=10) as conn:
            conn.execute("SELECT 1")
        steps["6_pg_connect"] = {"ok": True, "database": database}
    except Exception as e:
        steps["6_pg_connect"] = {"ok": False, "error": str(e)}
        return {"steps": steps, "result": "FAILED at step 6"}

    return {"steps": steps, "result": "ALL STEPS PASSED"}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

_dist_dir = _app_root / "dist"

if _dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=_dist_dir / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = _dist_dir / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_dist_dir / "index.html")
else:
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
