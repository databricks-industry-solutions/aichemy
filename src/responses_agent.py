import json
from uuid import uuid4
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    convert_to_openai_messages,
)
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent
)
from typing import Any, Generator, Optional, Union
from langgraph.graph.state import CompiledStateGraph, StateGraph
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
#import inspect

#print(inspect.getsource(uuid4))

class WrappedAgent(ResponsesAgent):
    def __init__(self, 
                 agent: Union[CompiledStateGraph, StateGraph], 
                 conninfo: str = None):
        # if without memory
        if isinstance(agent, CompiledStateGraph):
            self.agent = agent
            self.workflow = None
            self.conninfo = conninfo
            self.pool = None
            self.checkpointer = None
        # if with memory
        elif isinstance(agent, StateGraph):
            self.agent = None
            self.workflow = agent
            self.conninfo = conninfo
            self.pool = ConnectionPool(
                conninfo=self.conninfo,
                kwargs={'autocommit': True},
                min_size=1,
                max_size=10,
                open=True)
            self.checkpointer = PostgresSaver(self.pool)
        else:
            raise Exception("agent must be either a langgraph CompiledStateGraph or a StateGraph")

    def _add_memory(self):
        if self.workflow is not None and self.checkpointer is not None:
            self.agent = self.workflow.compile(checkpointer=self.checkpointer)
        elif self.workflow is not None and self.checkpointer is None:
            # No memory
            self.agent = self.workflow.compile()
            print("No checkpointer found so compiling workflow without memory")

    def _langchain_to_responses(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        "Convert from ChatCompletion dict to Responses output item dictionaries"
        for message in messages:
            message = message.model_dump()
            role = message["type"]
            if role == "ai":
                if tool_calls := message.get("tool_calls"):
                    return [
                        self.create_function_call_item(
                            id=message.get("id") or str(uuid4()),
                            call_id=tool_call["id"],
                            name=tool_call["name"],
                            arguments=json.dumps(tool_call["args"]),
                        )
                        for tool_call in tool_calls
                    ]
                else:
                    return [
                        self.create_text_output_item(
                            text=message["content"],
                            id=message.get("id") or str(uuid4()),
                        )
                    ]
            elif role == "tool":
                return [
                    self.create_function_call_output_item(
                        call_id=message["tool_call_id"],
                        output=message["content"],
                    )
                ]
            elif role == "user":
                return [message]

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = []
        for event in self.predict_stream(request):
            if event.type == "response.output_item.done":
                outputs.append(event.item)
                # overwrite with latest as thread_id is constant through the stream
                custom_outputs = event.custom_outputs
        return ResponsesAgentResponse(output=outputs, custom_outputs=custom_outputs)

    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        try:
            config = {"configurable": {"thread_id": request.custom_inputs.get("thread_id", str(uuid4()))}}
        except Exception as e:
            config = {"configurable": {"thread_id": str(uuid4())}}

        cc_msgs = []
        for msg in request.input:
            cc_msgs.extend(self._responses_to_cc(msg.model_dump()))

        if self.checkpointer:
            self._add_memory()
        for event in self.agent.stream(
            {
                "messages": cc_msgs, 
                "recursion_limit": request.custom_inputs.get("recursion_limit", 25)
            }, 
            config=config, 
            stream_mode=["updates", "messages"]
        ):
            if event[0] == "updates":
                for node_data in event[1].values():
                    if node_data:
                        for item in self._langchain_to_responses(node_data.get("messages")):
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.done", 
                                item=item,
                                custom_outputs={"thread_id": config["configurable"]["thread_id"]})
            # filter the streamed messages to just the generated text messages
            elif event[0] == "messages":
                try:
                    chunk = event[1][0]
                    if isinstance(chunk, AIMessageChunk) and (content := chunk.content):
                        yield ResponsesAgentStreamEvent(
                            **self.create_text_delta(delta=content, item_id=chunk.id),
                            custom_outputs={"thread_id": config["configurable"]["thread_id"]}
                        )
                except Exception as e:
                    print(e)