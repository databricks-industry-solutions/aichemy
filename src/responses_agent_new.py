import asyncio
import json
import logging
from uuid import uuid4
from typing import Annotated, Any, AsyncGenerator, Generator, Optional, Sequence

from databricks.sdk import WorkspaceClient
from databricks_langchain import AsyncCheckpointSaver
from langchain_core.messages.tool import ToolMessage
from langchain.messages import AIMessage, AIMessageChunk, AnyMessage
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)
from langgraph.graph.state import StateGraph

logger = logging.getLogger(__name__)


class WrappedAgent(ResponsesAgent):
    """ResponsesAgent wrapper with optional Lakebase memory via AsyncCheckpointSaver."""

    def __init__(
        self,
        workflow: StateGraph,
        workspace_client: Optional[WorkspaceClient] = None,
        lakebase_instance: Optional[str] = None,
    ):
        self.workflow = workflow
        self.workspace_client = workspace_client or WorkspaceClient()
        self.lakebase_instance = lakebase_instance

    def _add_memory(self, checkpointer: AsyncCheckpointSaver):
        if self.workflow is not None and checkpointer is not None:
            return self.workflow.compile(checkpointer=checkpointer)
        elif self.workflow is not None and checkpointer is None:
            # No memory
            print("No checkpointer found so compiling workflow without memory")
            return self.workflow.compile()

    def _get_or_create_thread_id(self, request: ResponsesAgentRequest) -> str:
        """Get thread_id from request or create a new one.

        Priority:
        1. thread_id from custom_inputs
        2. conversation_id from chat context
        3. New UUID
        """
        ci = dict(request.custom_inputs or {})
        if "thread_id" in ci:
            return ci["thread_id"]
        if request.context and getattr(request.context, "conversation_id", None):
            return request.context.conversation_id
        return str(uuid4())

    # Make a prediction (single-step) for the agent
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done" or event.type == "error"
        ]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    
    async def _predict_stream_async(
        self,
        request: ResponsesAgentRequest,
    ) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
        async with AsyncCheckpointSaver(
            instance_name=self.lakebase_instance,
            workspace_client=self.workspace_client,
        ) as checkpointer:
            self.agent = self._add_memory(checkpointer)
            cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
            recursion_limit = (request.custom_inputs or {}).get("recursion_limit", 25)
            inputs = {"messages": cc_msgs, "recursion_limit": recursion_limit}
            thread_id = self._get_or_create_thread_id(request)
            config = {"configurable": {"thread_id": thread_id}}

            # Stream events from the agent graph
            async for event in self.agent.astream(
                inputs, config=config, stream_mode=["updates", "messages"]
            ):
                if event[0] == "updates":
                    # Stream updated messages from the workflow nodes
                    for node_data in event[1].values():
                        if len(node_data.get("messages", [])) > 0:
                            all_messages = []
                            for msg in node_data["messages"]:
                                if isinstance(msg, ToolMessage) and not isinstance(msg.content, str):
                                    msg.content = json.dumps(msg.content)
                                all_messages.append(msg)
                            for item in output_to_responses_items_stream(all_messages):
                                yield item
                elif event[0] == "messages":
                    # Stream generated text message chunks
                    try:
                        chunk = event[1][0]
                        if isinstance(chunk, AIMessageChunk) and (content := chunk.content):
                            yield ResponsesAgentStreamEvent(
                                **self.create_text_delta(delta=content, item_id=chunk.id),
                            )
                    except:
                        pass

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