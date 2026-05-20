import asyncio
import json
import logging
import time as time_mod
from typing import Any, AsyncGenerator, AsyncIterator, Generator, Optional
from uuid import uuid4

from databricks.sdk import WorkspaceClient
from databricks_langchain import AsyncCheckpointSaver, AsyncDatabricksStore
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.tool import ToolMessage
from langgraph.graph.state import StateGraph
from langgraph.store.base import BaseStore
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    create_function_call_item,
    create_function_call_output_item,
    create_text_output_item,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

try:
    import uuid_utils
    def _new_id() -> str:
        return str(uuid_utils.uuid7())
except ImportError:
    def _new_id() -> str:
        return str(uuid4())

from agent.utils_memory import get_user_id, fetch_user_memories
from agent.utils import _FAKE_ID_PREFIX, _disabled_mcps_ctx, _tool_server_map

logger = logging.getLogger(__name__)

async def process_agent_astream_events(
    async_stream: AsyncIterator[Any],
    seen_msg_ids: set[str] | None = None,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Convert raw LangGraph astream events into ResponsesAgentStreamEvents.

    Adapted from the official agent-langgraph-advanced template. Handles:
    - Per-token text deltas (messages mode)
    - Inline tool call start / argument deltas / done (messages mode)
    - Tool results and completed text (updates mode)

    seen_msg_ids: message IDs already present in the checkpointer before this
    turn started. When LangGraph replays prior-turn messages through the
    "updates" stream on follow-up turns, we skip any message whose id is in
    this set so the client doesn't see the previous response re-emitted.
    """
    seen_msg_ids = set(seen_msg_ids or ())
    response_id = f"{_FAKE_ID_PREFIX}{uuid4().hex[:16]}"
    in_turn = False
    turn_output_items: list[dict] = []
    output_index = 0
    active_text_item_id: str | None = None
    active_text_content = ""
    active_tool_calls: dict[int, dict] = {}

    def _response_obj(output: list[dict] | None = None) -> dict:
        return {
            "id": response_id,
            "created_at": time_mod.time(),
            "object": "response",
            "output": output or [],
            "status": None,
        }

    def _start_turn():
        nonlocal in_turn, turn_output_items
        in_turn = True
        turn_output_items = []

    def _end_turn():
        nonlocal in_turn, active_text_item_id, active_text_content
        in_turn = False
        active_text_item_id = None
        active_text_content = ""

    async for raw_event in async_stream:
        # When astream is called with subgraphs=True, events are
        # (namespace_tuple, mode, data) so sub-agent activity surfaces here.
        # Without subgraphs they are (mode, data). Normalize to (mode, data).
        if len(raw_event) == 3:
            event = raw_event[1:]
        else:
            event = raw_event

        if event[0] == "messages":
            try:
                chunk = event[1][0]
                if not isinstance(chunk, AIMessageChunk):
                    continue

                if not in_turn:
                    _start_turn()
                    yield ResponsesAgentStreamEvent(
                        type="response.created",
                        response=_response_obj(),
                    )

                if chunk.tool_call_chunks:
                    for tc_chunk in chunk.tool_call_chunks:
                        idx = tc_chunk.get("index", 0)
                        name = tc_chunk.get("name") or ""
                        tc_id = tc_chunk.get("id") or ""
                        args = tc_chunk.get("args") or ""

                        if idx not in active_tool_calls:
                            item_id = _new_id()
                            active_tool_calls[idx] = {
                                "item_id": item_id,
                                "name": name,
                                "args": "",
                                "call_id": tc_id,
                                "output_index": output_index,
                            }
                            output_index += 1
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.added",
                                item={
                                    "type": "function_call",
                                    "id": item_id,
                                    "call_id": tc_id,
                                    "name": name,
                                    "arguments": "",
                                },
                                output_index=active_tool_calls[idx]["output_index"],
                            )
                        else:
                            tc_info = active_tool_calls[idx]
                            if name and not tc_info["name"]:
                                tc_info["name"] = name
                            if tc_id and not tc_info["call_id"]:
                                tc_info["call_id"] = tc_id

                        if args:
                            active_tool_calls[idx]["args"] += args
                            yield ResponsesAgentStreamEvent(
                                type="response.function_call_arguments.delta",
                                delta=args,
                                item_id=active_tool_calls[idx]["item_id"],
                                output_index=active_tool_calls[idx]["output_index"],
                            )

                elif chunk.content:
                    content = chunk.content
                    if not active_text_item_id:
                        active_text_item_id = _new_id()
                        active_text_content = ""
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.added",
                            item={
                                "type": "message",
                                "id": active_text_item_id,
                                "role": "assistant",
                                "status": "in_progress",
                                "content": [],
                            },
                            output_index=output_index,
                        )
                        yield ResponsesAgentStreamEvent(
                            type="response.content_part.added",
                            item_id=active_text_item_id,
                            output_index=output_index,
                            content_index=0,
                            part={"type": "output_text", "text": "", "annotations": []},
                        )

                    active_text_content += content
                    yield ResponsesAgentStreamEvent(
                        type="response.output_text.delta",
                        delta=content,
                        item_id=active_text_item_id,
                        content_index=0,
                        output_index=output_index,
                    )

            except Exception as e:
                logger.exception("Error processing agent stream event: %s", e)

        elif event[0] == "updates":
            for node_data in event[1].values():
                messages = node_data.get("messages", [])
                if not messages:
                    continue

                fresh_messages = []
                for msg in messages:
                    msg_id = getattr(msg, "id", None)
                    if msg_id and msg_id in seen_msg_ids:
                        continue
                    if msg_id:
                        seen_msg_ids.add(msg_id)
                    fresh_messages.append(msg)
                if not fresh_messages:
                    continue

                has_ai_message = False

                for msg in fresh_messages:
                    if isinstance(msg, ToolMessage):
                        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                        item = create_function_call_output_item(
                            call_id=msg.tool_call_id,
                            output=content,
                        )
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=item,
                        )

                    elif isinstance(msg, AIMessage) and msg.tool_calls:
                        has_ai_message = True
                        if not in_turn:
                            _start_turn()
                            yield ResponsesAgentStreamEvent(
                                type="response.created",
                                response=_response_obj(),
                            )

                        for j, tc in enumerate(msg.tool_calls):
                            call_id = tc.get("id", "")
                            name = tc.get("name", "")
                            args = tc.get("args", {})
                            args_str = json.dumps(args) if isinstance(args, dict) else str(args)

                            tc_info = active_tool_calls.get(j)
                            if tc_info:
                                item_id = tc_info["item_id"]
                                matched_oi = tc_info["output_index"]
                            else:
                                item_id = _new_id()
                                matched_oi = output_index
                                output_index += 1

                            item = create_function_call_item(
                                id=item_id,
                                call_id=call_id,
                                name=name,
                                arguments=args_str,
                            )
                            turn_output_items.append(item)
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.done",
                                item=item,
                                output_index=matched_oi,
                            )

                        active_tool_calls.clear()

                    elif isinstance(msg, AIMessage) and msg.content:
                        has_ai_message = True
                        if not in_turn:
                            _start_turn()
                            yield ResponsesAgentStreamEvent(
                                type="response.created",
                                response=_response_obj(),
                            )

                        text = msg.content
                        item_id = active_text_item_id or _new_id()

                        if not active_text_item_id:
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.added",
                                item={
                                    "type": "message",
                                    "id": item_id,
                                    "role": "assistant",
                                    "status": "in_progress",
                                    "content": [],
                                },
                                output_index=output_index,
                            )
                            yield ResponsesAgentStreamEvent(
                                type="response.content_part.added",
                                item_id=item_id,
                                output_index=output_index,
                                content_index=0,
                                part={"type": "output_text", "text": "", "annotations": []},
                            )

                        yield ResponsesAgentStreamEvent(
                            type="response.content_part.done",
                            item_id=item_id,
                            output_index=output_index,
                            content_index=0,
                            part={"type": "output_text", "text": text, "annotations": []},
                        )

                        item = create_text_output_item(text=text, id=item_id)
                        item["status"] = "completed"
                        turn_output_items.append(item)
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=item,
                            output_index=output_index,
                        )
                        output_index += 1
                        active_text_item_id = None
                        active_text_content = ""

                if has_ai_message and in_turn:
                    yield ResponsesAgentStreamEvent(
                        type="response.completed",
                        response=_response_obj(turn_output_items),
                    )
                    _end_turn()


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

            existing_state = await self.agent.aget_state(config)
            seen_msg_ids: set[str] = {
                getattr(msg, "id", None)
                for msg in (existing_state.values or {}).get("messages", [])
                if getattr(msg, "id", None)
            }

            try:
                async for event in process_agent_astream_events(
                    self.agent.astream(
                        inputs,
                        config=config,
                        stream_mode=["updates", "messages"],
                        subgraphs=True,
                    ),
                    seen_msg_ids=seen_msg_ids,
                ):
                    yield event
            except Exception as e:
                logger.exception("Error during agent streaming")
                error_msg = AIMessage(content=f"**Agent error:** `{type(e).__name__}`: {e}")
                for item in output_to_responses_items_stream([error_msg]):
                    yield item
            finally:
                _disabled_mcps_ctx.reset(_ctx_token)

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