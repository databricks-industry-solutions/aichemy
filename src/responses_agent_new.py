import asyncio
from typing import Annotated, Any, AsyncGenerator, Generator, Optional, Sequence
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)
from langchain_core.messages.tool import ToolMessage
from langchain.messages import AIMessage, AIMessageChunk, AnyMessage
import json

class WrappedAgent(ResponsesAgent):
    def __init__(self, agent):
        self.agent = agent

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
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        # Stream events from the agent graph
        async for event in self.agent.astream(
            {"messages": cc_msgs}, stream_mode=["updates", "messages"]
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