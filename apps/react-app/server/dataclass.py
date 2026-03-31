"""Pydantic request/response models for the AiChemy web server."""

from pydantic import BaseModel
from typing import List, Optional, Union


class Message(BaseModel):
    role: str
    content: str


class CustomInputs(BaseModel):
    thread_id: str
    user_id: Optional[str] = None


class AgentRequest(BaseModel):
    input: List[Message]
    custom_inputs: CustomInputs
    skill_name: Optional[str] = None
    new_thread: Optional[bool] = None


class CreateProjectRequest(BaseModel):
    name: str
    user_id: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    messages: Optional[list] = None
    agent_steps: Union[list, dict, None] = None
