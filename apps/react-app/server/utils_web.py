"""
Utility helpers for the AiChemy web server.

Extracted from web_server.py to keep the main module focused on
FastAPI route definitions and the ProjectDB class.
"""

import os
import re
import json
import yaml
import requests
import time
import asyncio
from pathlib import Path
from typing import Optional, Union

from agent.utils import get_secret, load_config

_app_root = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def resolve_databricks_host() -> Optional[str]:
    """Resolve Databricks host from env var or config.yml (None lets SDK use default auth)."""
    host = os.getenv("DATABRICKS_HOST")
    if host:
        return host
    return load_config().get("host")


# ---------------------------------------------------------------------------
# User identity resolution
# ---------------------------------------------------------------------------

_cached_sdk_user_info: Optional[dict] = None


def resolve_user_from_request(request, get_workspace_client) -> dict:
    """Resolve user identity from HTTP headers, then SDK auth, then env vars.

    Databricks Apps sets ``X-Forwarded-Email``, ``X-Forwarded-Preferred-Username``,
    and ``X-Forwarded-User`` on every proxied request.  These are checked first so
    multi-user deployments resolve the *calling* user, not the service principal.
    """
    if request is not None:
        email = request.headers.get("X-Forwarded-Email")
        preferred = request.headers.get("X-Forwarded-Preferred-Username")
        user = request.headers.get("X-Forwarded-User")
        if email or preferred or user:
            return {
                "user_name": preferred or email or user or "Unknown",
                "user_email": email or preferred or "",
                "user_id": email or preferred or user or "",
            }

    return _resolve_sdk_user(get_workspace_client)


def _resolve_sdk_user(get_workspace_client) -> dict:
    """Fallback: resolve from WorkspaceClient / env vars (cached for the process)."""
    global _cached_sdk_user_info
    if _cached_sdk_user_info is not None:
        return _cached_sdk_user_info

    try:
        w = get_workspace_client()
        me = w.current_user.me()
        _cached_sdk_user_info = {
            "user_name": me.display_name or me.user_name or "Unknown",
            "user_email": me.user_name or "",
            "user_id": me.user_name or str(me.id),
        }
        return _cached_sdk_user_info
    except Exception:
        pass

    _cached_sdk_user_info = {
        "user_name": os.getenv("DEFAULT_USER_NAME"),
        "user_email": os.getenv("DEFAULT_USER_EMAIL"),
        "user_id": os.getenv("DEFAULT_USER_ID"),
    }
    return _cached_sdk_user_info


# ---------------------------------------------------------------------------
# Trace serialization & text extraction
# ---------------------------------------------------------------------------


def safe_json(obj):
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


def serialize_trace(trace) -> dict:
    """Convert an MLflow Trace object to a JSON-serializable dict."""
    info = trace.info
    spans = []
    for s in trace.data.spans if trace.data else []:
        attrs = {}
        try:
            for k, v in (s.attributes or {}).items():
                attrs[str(k)] = safe_json(v)
        except Exception:
            pass
        spans.append(
            {
                "name": getattr(s, "name", None),
                "span_id": getattr(s, "span_id", None),
                "parent_id": getattr(s, "parent_id", None),
                "status": str(getattr(s, "status", "")),
                "start_time_ns": getattr(s, "start_time_ns", None),
                "end_time_ns": getattr(s, "end_time_ns", None),
                "inputs": safe_json(getattr(s, "inputs", None)),
                "outputs": safe_json(getattr(s, "outputs", None)),
                "attributes": attrs,
            }
        )
    return {
        "trace_id": getattr(info, "trace_id", None),
        "status": str(getattr(info, "state", "")),
        "execution_time_ms": getattr(info, "execution_duration", None),
        "request_time": getattr(info, "request_time", None),
        "tags": dict(info.tags) if getattr(info, "tags", None) else {},
        "spans": spans,
    }


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def strip_tool_call_tags(text_content: str) -> str:
    """Strip <function_calls>, <thinking>, and <results> tags from text."""
    text_content = re.sub(
        r"<function_calls>.*?</function_calls>", "", text_content, flags=re.DOTALL
    )
    text_content = re.sub(
        r"<thinking>.*?</thinking>", "", text_content, flags=re.DOTALL
    )
    text_content = re.sub(r"<results>.*?</results>", "", text_content, flags=re.DOTALL)
    text_content = re.sub(r"<results>.*", "", text_content, flags=re.DOTALL)
    text_content = re.sub(r"\n\s*\n\s*\n+", "\n\n", text_content)
    return text_content.strip()


def stream_new_content(item: Optional[dict], _sse):
    """Yield SSE events for one response item's text in chunks. Skips tool-call tags."""
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
    """Extract Genie query results from poll_query_results spans."""
    results = []
    for span in trace_dict.get("spans", []):
        if span.get("name") != "poll_query_results":
            continue
        outputs = span.get("outputs")
        if isinstance(outputs, dict) and outputs.get("result"):
            results.append(
                {
                    "result": outputs.get("result", ""),
                    "query": outputs.get("query", ""),
                    "description": outputs.get("description", ""),
                }
            )
    return results


def extract_text_content(response_json: dict) -> list[str]:
    """Extract the final (supervisor) text from the agent response."""
    last_text = None
    for item in response_json.get("output", []):
        if item.get("type") == "message":
            text = item.get("content", [{}])[0].get("text")
            if text:
                last_text = text
    return [last_text] if last_text else []


def extract_all_tool_calls(trace_dict: dict) -> list[dict]:
    """Extract tool calls from a serialized trace (OpenAI Responses-style spans)."""
    all_tool_calls = []
    for span in trace_dict.get("spans", []):
        if span.get("name") == "tools":
            inputs = span.get("inputs", {})
            tool_call = inputs.get("tool_call")
            if isinstance(tool_call, dict):
                tc_name = tool_call.get("name")
                try:
                    results = span.get("outputs").get("messages")[0].get("content")
                except Exception:
                    results = None
                if tool_call.get("args", {}) == {} and results is None:
                    continue
                all_tool_calls.append(
                    {
                        "function_name": tc_name,
                        "parameters": tool_call.get("args"),
                        "results": results,
                    }
                )
    return all_tool_calls


def parse_trace_for_ui(trace_dict: dict) -> dict:
    """Parse a serialized trace for tool_calls and genie_results."""
    return {
        "tool_calls": extract_all_tool_calls(trace_dict),
        "genie_results": parse_genie_results(trace_dict),
    }


def extract_text_from_trace(trace_dict: dict) -> Optional[str]:
    """Extract the final assistant text from a serialized trace.

    Searches spans for text in LangGraph, Responses API, ChatCompletion,
    and plain-string output formats.
    """
    spans = trace_dict.get("spans", [])
    if not spans:
        return None

    root = next((s for s in spans if not s.get("parent_id")), None)
    ordered = ([root] + [s for s in spans if s is not root]) if root else spans

    for span in ordered:
        outputs = span.get("outputs")
        if outputs is None:
            continue

        if isinstance(outputs, dict):
            # LangGraph messages
            messages = outputs.get("messages", [])
            if messages:
                for msg in reversed(messages):
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") in ("ai", "ai_message") or msg.get("role") == "assistant":
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return strip_tool_call_tags(content)

            # Responses API output
            for item in outputs.get("output", []):
                if isinstance(item, dict) and item.get("type") == "message":
                    for block in item.get("content") or []:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "output_text"
                            and block.get("text")
                        ):
                            text = strip_tool_call_tags(block["text"])
                            if text:
                                return text

            # ChatCompletion choices
            for choice in outputs.get("choices", []):
                if isinstance(choice, dict):
                    msg = choice.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        return strip_tool_call_tags(content)

        if isinstance(outputs, str) and outputs.strip():
            return strip_tool_call_tags(outputs)

    return None


# ---------------------------------------------------------------------------
# Skills — discover, load, and build prompts
# ---------------------------------------------------------------------------

SKILLS_DIR = _app_root / "skills"

SKILL_FOLDER_BY_WORKFLOW_IDX = {
    0: "target-identification",
    1: "hit-identification",
    2: "ADME-assessment",
    3: "safety-assessment",
}


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
    skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
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
            label = _smart_title(name.replace("-", " "))

            caption = description.split(". ")[0] if description else ""
            if len(caption) > 70:
                caption = caption[:67] + "..."

            skills[name] = {
                "description": description,
                "path": str(folder),
                "label": label,
                "caption": caption,
            }
        except Exception:
            continue
    return skills


def load_skill_content(
    skill_name: str, skills_dir: Optional[Union[str, Path]] = None
) -> Optional[dict]:
    """Load full SKILL.md + reference files for a given skill."""
    skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
    skill_path = skills_dir / skill_name
    skill_file = skill_path / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        full_content = skill_file.read_text(encoding="utf-8")
        fm = _parse_skill_frontmatter(full_content)
        match = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", full_content, re.DOTALL)
        body = match.group(1).strip() if match else full_content

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

        return {
            "frontmatter": fm,
            "content": body,
            "references": references,
            "full_prompt": full_prompt,
        }
    except Exception:
        return None


def build_prompt_with_skill(
    user_query: str, skill_name: str, skills_dir: Optional[Union[str, Path]] = None
) -> str:
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


# ---------------------------------------------------------------------------
# External MCP server health checks
# ---------------------------------------------------------------------------

_MCP_SERVERS: Optional[dict[str, dict]] = None


def get_mcp_servers() -> dict[str, dict]:
    """Load all MCP server URLs and auth metadata from config.yml (cached).

    Reads three config sections:
      * ``external_mcp``   – third-party servers with bearer-token auth
      * ``custom_mcp``     – Databricks Apps with OAuth M2M auth
      * ``uc_connections`` – Unity Catalog connection proxy via workspace auth
    """
    global _MCP_SERVERS
    if _MCP_SERVERS is None:
        cfg = load_config()
        flat: dict[str, dict] = {}

        for name, mcp_cfg in cfg.get("external_mcp", {}).items():
            flat[name] = {"url": mcp_cfg["url"], "type": "external"}

        for name, mcp_cfg in cfg.get("custom_mcp", {}).items():
            flat[name] = {"url": mcp_cfg["url"], "type": "custom"}

        host = cfg.get("host", "").rstrip("/") + "/"
        for name, conn_name in cfg.get("uc_connections", {}).items():
            flat[name] = {
                "url": f"{host}api/2.0/mcp/external/{conn_name}",
                "type": "uc_connection",
            }

        _MCP_SERVERS = flat
    return _MCP_SERVERS


def _databricks_auth_headers(cfg: dict, server_type: str, name: str) -> dict[str, str]:
    """Build Authorization headers for Databricks-authenticated MCP servers."""
    from databricks.sdk import WorkspaceClient

    if server_type == "custom":
        mcp_cfg = cfg.get("custom_mcp", {}).get(name, {})
        if "scope" in mcp_cfg:
            client_id = get_secret(scope=mcp_cfg["scope"], key=mcp_cfg["client_id"])
            client_secret = get_secret(scope=mcp_cfg["scope"], key=mcp_cfg["secret"])
            ws = WorkspaceClient(
                host=mcp_cfg.get("host") or cfg.get("host"),
                client_id=client_id,
                client_secret=client_secret,
                auth_type="oauth-m2m",
            )
        else:
            ws = WorkspaceClient()
    else:
        ws = WorkspaceClient()

    # headers: dict[str, str] = {}
    # ws.config.authenticate(headers)
    # return headers
    return ws.config.authenticate()

def check_mcp_server(name: str, server_info: dict, timeout: float = 5.0) -> dict:
    """Ping an MCP server with a JSON-RPC initialize request.

    Handles three auth modes:
      * external  – bearer token from Databricks secrets
      * custom    – Databricks OAuth M2M via WorkspaceClient
      * uc_connection – default workspace OAuth via WorkspaceClient
    """
    cfg = load_config()
    url = server_info["url"]
    server_type = server_info["type"]

    mcp_init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "health-check", "version": "0.1.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    if server_type == "external":
        secret = cfg.get("external_mcp", {}).get(name, {}).get("secret")
        if secret:
            scope = cfg["external_mcp"].get(name, {}).get("scope")
            headers["Authorization"] = f"Bearer {get_secret(scope=scope, key=secret)}"
    elif server_type in ("custom", "uc_connection"):
        try:
            headers.update(_databricks_auth_headers(cfg, server_type, name))
        except Exception as e:
            return {"name": name, "url": url, "ok": False, "error": f"auth_failed: {e}"}

    try:
        resp = requests.post(url, json=mcp_init, headers=headers, timeout=timeout)
        if resp.status_code < 400:
            return {"name": name, "url": url, "ok": True, "status_code": resp.status_code}
        return {
            "name": name, "url": url, "ok": True, "status": "reachable",
            "status_code": resp.status_code, "detail": resp.reason,
        }
    except requests.exceptions.ConnectionError:
        return {"name": name, "url": url, "ok": False, "error": "connection_refused"}
    except requests.exceptions.Timeout:
        return {"name": name, "url": url, "ok": False, "error": "timeout"}
    except Exception as e:
        return {"name": name, "url": url, "ok": False, "error": str(e)}


async def check_all_mcp_servers() -> list[dict]:
    """Check reachability of all configured MCP servers in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    servers = get_mcp_servers()
    if not servers:
        return []

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=len(servers)) as pool:
        futures = [
            loop.run_in_executor(pool, check_mcp_server, name, info)
            for name, info in servers.items()
        ]
        return list(await asyncio.gather(*futures))
