import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Generator, Optional

from databricks.sdk import WorkspaceClient
from databricks_langchain import AsyncCheckpointSaver, AsyncDatabricksStore
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolMessage
from langgraph.graph.state import StateGraph
from langgraph.store.base import BaseStore
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

from agent.utils_memory import get_user_id, fetch_user_memories
from agent.utils import _disabled_mcps_ctx, _tool_server_map

logger = logging.getLogger(__name__)


class WrappedAgent(ResponsesAgent):
    """ResponsesAgent wrapper with Lakebase-backed store + checkpointer.

    - **Store** (``AsyncDatabricksStore``): per-user long-term memory (preferences, notes).
    - **Checkpointer** (``AsyncCheckpointSaver``): full conversation state per thread,
      enabling multi-turn continuity without resending the entire history.
    Both share the same Lakebase Autoscale project/branch.
    """

    def __init__(
        self,
        workflow: StateGraph,
        workspace_client: Optional[WorkspaceClient] = None,
        cfg: dict[str, Any] = None,
    ):
        self.workflow = workflow
        self.workspace_client = workspace_client or WorkspaceClient()
        self.config = cfg

        self.lakebase_autoscaling_project = cfg["lakebase"]["project_id"]
        self.lakebase_autoscaling_branch = cfg["lakebase"]["branch_id"]
        self.embedding_endpoint = cfg["lakebase"]["embedding"]
        self.embedding_dim = cfg["lakebase"]["embedding_dim"]

    def _compile(self, store: Optional[BaseStore] = None, checkpointer=None):
        if self.workflow is None:
            raise RuntimeError("Workflow not set")
        kwargs: dict[str, Any] = {}
        if store is not None:
            kwargs["store"] = store
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
        if not kwargs:
            logger.warning("Compiling workflow without store or checkpointer")
        return self.workflow.compile(**kwargs)

    # Make a prediction (single-step) for the agent
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        seen_ids: set[str] = set()
        outputs = []
        for event in self.predict_stream(request):
            if event.type == "response.output_item.done" or event.type == "error":
                item_id = getattr(event.item, "id", None)
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                outputs.append(event.item)
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    
    async def _predict_stream_async(
        self,
        request: ResponsesAgentRequest,
    ) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
        from uuid import uuid4

        lakebase_kwargs = dict(
            project=self.lakebase_autoscaling_project,
            branch=self.lakebase_autoscaling_branch,
            workspace_client=self.workspace_client
        )
        async with (
            AsyncDatabricksStore(
                **lakebase_kwargs,
                embedding_endpoint=self.embedding_endpoint,
                embedding_dims=self.embedding_dim,
            ) as store,
            AsyncCheckpointSaver(**lakebase_kwargs) as checkpointer,
        ):
            await store.setup()
            await checkpointer.setup()
            self.agent = self._compile(store=store, checkpointer=checkpointer)

            cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
            ci = dict(request.custom_inputs or {})
            recursion_limit = ci.get("recursion_limit", 25)
            thread_id = ci.get("thread_id", str(uuid4()))
            user_id = get_user_id(request)

            # Auto-inject relevant user memories as context so the
            # supervisor never needs to route to a memory agent for retrieval.
            if user_id:
                last_user_msg = ""
                for m in reversed(cc_msgs):
                    if getattr(m, "type", None) == "human" or (isinstance(m, dict) and m.get("role") == "user"):
                        last_user_msg = m.content if hasattr(m, "content") else m.get("content", "")
                        break
                memory_ctx = await fetch_user_memories(store, user_id, query=last_user_msg)
                if memory_ctx:
                    from langchain_core.messages import SystemMessage
                    cc_msgs = [SystemMessage(content=memory_ctx)] + list(cc_msgs)

            # Derive the disabled set from the enabled_mcps list sent by the UI.
            # All known servers (from _tool_server_map) minus the enabled ones = disabled.
            enabled_mcps = ci.get("enabled_mcps")
            if enabled_mcps is not None:
                all_servers = set(_tool_server_map.values())
                disabled_mcps = frozenset(all_servers - set(enabled_mcps))
            else:
                disabled_mcps = frozenset()
            _ctx_token = _disabled_mcps_ctx.set(disabled_mcps)
            if disabled_mcps:
                logger.info("Disabled MCP servers for this request: %s", disabled_mcps)

            inputs = {"messages": cc_msgs}
            config: dict[str, Any] = {
                "configurable": {
                    "thread_id": thread_id,
                    "store": store,
                },
                "recursion_limit": recursion_limit,
            }
            if user_id:
                config["configurable"]["user_id"] = user_id

            # Pre-seed seen_msg_ids with any messages already in the checkpoint
            # so that prior-turn messages are never re-emitted on follow-up turns.
            existing_state = await self.agent.aget_state(config)
            seen_msg_ids: set[str] = {
                getattr(msg, "id", None)
                for msg in (existing_state.values or {}).get("messages", [])
                if getattr(msg, "id", None)
            }
            seen_item_ids: set[str] = set()
            seen_non_supervisor_output = False  # tracks whether any sub-agent has responded
            # IDs of messages whose text was already emitted as per-token deltas;
            # the corresponding response.output_item.done should not re-emit the text.
            token_streamed_msg_ids: set[str] = set()

            def _should_skip_supervisor() -> bool:
                return seen_non_supervisor_output

            try:
                async for raw_event in self.agent.astream(
                    inputs, config=config, stream_mode=["updates", "messages"]
                ):
                    # stream_mode list → events are (mode, data) tuples
                    if isinstance(raw_event, tuple):
                        mode, data = raw_event
                    else:
                        mode, data = "updates", raw_event

                    # ── per-token streaming ────────────────────────────────────
                    if mode == "messages":
                        msg_chunk, metadata = data
                        node_name = metadata.get("langgraph_node", "")

                        if node_name == "supervisor" and _should_skip_supervisor():
                            continue

                        # Only stream AI text tokens; skip tool messages (raw JSON)
                        # and tool-call chunks (list content).
                        if isinstance(msg_chunk, ToolMessage):
                            continue
                        content = msg_chunk.content if isinstance(msg_chunk.content, str) else ""
                        if not content:
                            continue

                        msg_id = getattr(msg_chunk, "id", None)
                        if msg_id:
                            token_streamed_msg_ids.add(msg_id)

                        yield ResponsesAgentStreamEvent(
                            type="response.output_text.delta",
                            output_index=0,
                            content_index=0,
                            delta=content,
                            item_id=msg_id or "",
                        )

                    # ── node-complete events ───────────────────────────────────
                    elif mode == "updates":
                        for node_name, node_data in data.items():
                            if node_data is None or not isinstance(node_data, dict):
                                continue
                            if node_name == "supervisor" and _should_skip_supervisor():
                                continue
                            if node_name != "supervisor" and node_data.get("messages"):
                                seen_non_supervisor_output = True
                            if len(node_data.get("messages", [])) > 0:
                                unique_messages = []
                                for msg in node_data["messages"]:
                                    msg_id = getattr(msg, "id", None)
                                    if msg_id and msg_id in seen_msg_ids:
                                        continue
                                    if msg_id:
                                        seen_msg_ids.add(msg_id)
                                    if isinstance(msg, ToolMessage) and not isinstance(msg.content, str):
                                        msg.content = json.dumps(msg.content)
                                    unique_messages.append(msg)
                                # Emit events per message so we can suppress delta
                                # re-emission for messages already streamed per-token.
                                for msg in unique_messages:
                                    msg_id = getattr(msg, "id", None)
                                    already_streamed = bool(msg_id and msg_id in token_streamed_msg_ids)
                                    for item in output_to_responses_items_stream([msg]):
                                        if already_streamed and getattr(item, "type", None) == "response.output_text.delta":
                                            continue
                                        item_id = getattr(item, "item_id", None) or (
                                            getattr(item, "item", None) and getattr(item.item, "id", None)
                                        )
                                        if item_id and item_id in seen_item_ids:
                                            continue
                                        if item_id:
                                            seen_item_ids.add(item_id)
                                        yield item

            except Exception as e:
                logger.exception("Error during agent streaming")
                error_msg = AIMessage(content=f"**Agent error:** `{type(e).__name__}`: {e}")
                for item in output_to_responses_items_stream([error_msg]):
                    yield item
            finally:
                _disabled_mcps_ctx.reset(_ctx_token)

    # Stream predictions for the agent, yielding output as it's generated
    def predict_stream(
        self, request: ResponsesAgentRequest
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        agen = self._predict_stream_async(request)

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        ait = agen.__aiter__()

        while True:
            try:
                item = loop.run_until_complete(ait.__anext__())
            except StopAsyncIteration:
                break
            else:
                yield item