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

            # Stream node-level updates only (not individual LLM tokens via "messages"
            # mode, which would leak the supervisor's intermediate reasoning/hallucinations).
            seen_msg_ids: set[str] = set()
            seen_item_ids: set[str] = set()

            try:
                async for event in self.agent.astream(
                    inputs, config=config, stream_mode="updates"
                ):
                    for node_name, node_data in event.items():
                        if node_data is None or not isinstance(node_data, dict):
                            continue
                        # Skip the supervisor's own messages — they may contain
                        # hallucinated summaries. The graph's output_mode="last_message"
                        # ensures the sub-agent's final answer is the authoritative output;
                        # honour that by only surfacing sub-agent messages.
                        if node_name == "supervisor":
                            continue
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
                            for item in output_to_responses_items_stream(unique_messages):
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