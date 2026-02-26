import os
import json
import asyncio
from uuid import uuid4
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    convert_to_openai_messages,
)
from databricks.sdk import WorkspaceClient
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import to_chat_completions_input
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input
)
from databricks_langchain import AsyncCheckpointSaver
from typing import Any, Generator, Optional
from langgraph.graph.state import StateGraph
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

class WrappedAgent(ResponsesAgent):
    def __init__(self, 
                 workflow: StateGraph,
                 workspace_client: WorkspaceClient,
                 lakebase_instance: str):
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
        1. Use thread_id from custom_inputs if present
        2. Use conversation_id from chat context if available
        3. Generate a new UUID

        Returns:
            thread_id: The thread identifier to use for this conversation
        """
        ci = dict(request.custom_inputs or {})

        if "thread_id" in ci:
            return ci["thread_id"]

        # using conversation id from chat context as thread id
        # https://mlflow.org/docs/latest/api_reference/python_api/mlflow.types.html#mlflow.types.agent.ChatContext
        if request.context and getattr(request.context, "conversation_id", None):
            return request.context.conversation_id

        # Generate new thread_id
        return str(uuid4())

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        thread_id = self._get_or_create_thread_id(request)
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        config = {"configurable": {"thread_id": thread_id}}
        async def apredict(cc_msgs, config):
            events = []
            async for event in self.agent.astream(
                {
                    "messages": cc_msgs, 
                    "recursion_limit": request.custom_inputs.get("recursion_limit", 25)
                }, 
               config = config,
               stream_mode=["updates", "messages"]
            ):
                events.append(event)
            return events

        async def apredict_mem(cc_msgs, config):
            async with AsyncCheckpointSaver(
                instance_name=self.lakebase_instance, 
                workspace_client=self.workspace_client
                ) as checkpointer:
                # if first time
                # await checkpointer.setup()
                self.agent = self._add_memory(checkpointer)
                return await apredict(cc_msgs, config)
            
        events = asyncio.run(apredict_mem(cc_msgs, config))

        outputs = []
        for event in events:
            # if event.type == "response.output_item.done":
            #     outputs.append(event.item)
            if event[0] == "updates":
                for node_data in event[1].values():
                    if len(node_data.get("messages", [])) > 0:
                        #yield from output_to_responses_items_stream(node_data["messages"])
                        items = list(output_to_responses_items_stream(node_data["messages"]))
                        outputs.extend([item.item for item in items if item.type == "response.output_item.done"])
            elif event[0] == "messages":
                try:
                    chunk = event[1][0]
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        # yield ResponsesAgentStreamEvent(
                        #     **self.create_text_delta(delta=chunk.content, item_id=chunk.id),
                        # )
                        text_item = self.create_text_output_item(text=chunk.content, id=chunk.id)
                        outputs.append(text_item)
                except Exception as exc:
                    logger.error("Error streaming chunk: %s", exc)
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)
