"""
Memory tools for LangGraph agents backed by AsyncDatabricksStore.

Provides get/save/delete tools that store per-user memories in a Lakebase-backed
LangGraph Store, enabling long-term memory across conversations.

Adapted from:
  https://github.com/databricks/app-templates/tree/main/agent-langgraph-long-term-memory
"""

import json
import logging
import os
from typing import Optional

from databricks.sdk import WorkspaceClient
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.store.base import BaseStore
from mlflow.types.responses import ResponsesAgentRequest

logger = logging.getLogger(__name__)


def get_user_id(request: ResponsesAgentRequest) -> Optional[str]:
    """Extract user_id from request custom_inputs or context."""
    custom_inputs = dict(request.custom_inputs or {})
    if "user_id" in custom_inputs:
        return custom_inputs["user_id"]
    if request.context and getattr(request.context, "user_id", None):
        return request.context.user_id
    return None


def _is_lakebase_hostname(value: str) -> bool:
    return ".database." in value and value.endswith(".com")


def resolve_lakebase_instance_name(
    instance_name: str, workspace_client: Optional[WorkspaceClient] = None
) -> str:
    """Resolve a Lakebase hostname to an instance name if needed."""
    if not _is_lakebase_hostname(instance_name):
        return instance_name

    client = workspace_client or WorkspaceClient()
    hostname = instance_name

    try:
        instances = list(client.database.list_database_instances())
    except Exception as exc:
        raise ValueError(
            f"Unable to list database instances to resolve hostname '{hostname}'."
        ) from exc

    for instance in instances:
        rw_dns = getattr(instance, "read_write_dns", None)
        ro_dns = getattr(instance, "read_only_dns", None)
        if hostname in (rw_dns, ro_dns):
            resolved_name = getattr(instance, "name", None)
            if not resolved_name:
                raise ValueError(
                    f"Found matching instance for hostname '{hostname}' "
                    "but instance name is not available."
                )
            logger.info("Resolved Lakebase hostname '%s' to '%s'", hostname, resolved_name)
            return resolved_name

    raise ValueError(f"No database instance matches hostname '{hostname}'.")


def get_lakebase_access_error_message(lakebase_desc: str) -> str:
    if os.getenv("DATABRICKS_APP_NAME"):
        app_name = os.getenv("DATABRICKS_APP_NAME")
        return (
            f"Failed to connect to Lakebase '{lakebase_desc}'. "
            f"The App Service Principal for '{app_name}' may not have access.\n"
            "Add your Lakebase instance as an app resource and grant permissions."
        )
    return (
        f"Failed to connect to Lakebase '{lakebase_desc}'. "
        "Verify the instance name, permissions, and Databricks auth."
    )


async def fetch_user_memories(
    store: BaseStore, user_id: str, query: str = "", limit: int = 5
) -> str:
    """Retrieve relevant memories for a user and return formatted context.

    Called automatically before the supervisor runs so that memory never
    competes with tool routing.  Returns an empty string when there is
    nothing useful to inject.
    """
    if not user_id or not store:
        return ""
    namespace = ("user_memories", user_id.replace(".", "-"))
    try:
        results = await store.asearch(namespace, query=query, limit=limit)
    except Exception as exc:
        logger.warning("Memory retrieval failed (non-fatal): %s", exc)
        return ""
    if not results:
        return ""
    items = [f"- [{item.key}]: {json.dumps(item.value)}" for item in results]
    return (
        "## User memories (retrieved automatically)\n"
        + "\n".join(items)
    )


def memory_write_tools():
    """Save/delete tools for the memory agent (no retrieval — that's automatic)."""

    @tool
    async def save_user_memory(
        memory_key: str, memory_data_json: str, config: RunnableConfig
    ) -> str:
        """Save information about the user to long-term memory.

        memory_key: a short descriptive identifier (e.g. 'preferred_targets')
        memory_data_json: a JSON object string with the data to store
        """
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return "Cannot save memory - no user_id provided."

        store: Optional[BaseStore] = config.get("configurable", {}).get("store")
        if not store:
            return "Cannot save memory - store not configured."

        namespace = ("user_memories", user_id.replace(".", "-"))
        try:
            memory_data = json.loads(memory_data_json)
            if not isinstance(memory_data, dict):
                return f"Failed: memory_data must be a JSON object, not {type(memory_data).__name__}"
            await store.aput(namespace, memory_key, memory_data)
            return f"Successfully saved memory '{memory_key}' for user."
        except json.JSONDecodeError as e:
            return f"Failed to save memory: Invalid JSON - {e}"

    @tool
    async def delete_user_memory(memory_key: str, config: RunnableConfig) -> str:
        """Delete a specific memory from the user's long-term memory."""
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return "Cannot delete memory - no user_id provided."

        store: Optional[BaseStore] = config.get("configurable", {}).get("store")
        if not store:
            return "Cannot delete memory - store not configured."

        namespace = ("user_memories", user_id.replace(".", "-"))
        await store.adelete(namespace, memory_key)
        return f"Successfully deleted memory '{memory_key}' for user."

    return [save_user_memory, delete_user_memory]
