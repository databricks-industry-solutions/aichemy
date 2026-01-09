from databricks_ai_bridge.genie import Genie, GenieResponse
from utils import get_databricks_client
import os
import requests


class GenieWrapper(Genie):
    def __init__(self, space_id: str):
        self.client = get_databricks_client()
        super().__init__(space_id)

    # patch ask_question to return conversation_id and message_id
    def ask_first_question(self, question: str) -> dict:
        try:
            resp = self.start_conversation(question)
            return resp
        except requests.exceptions.ConnectionError as e:
            raise requests.exceptions.ConnectionError(
                f"❌ Connection error - check your network and workspace URL: {e}"
            )
        except requests.exceptions.Timeout as e:
            raise requests.exceptions.Timeout(f"❌ Request timed out: {e}")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(f"❌ Request failed: {e}")
        except ValueError as e:
            raise ValueError(f"❌ Invalid JSON response: {e}")
        except Exception as e:
            raise Exception(f"Error in ask_first_question: {e}")

    def get_conversation_id(self, resp: dict) -> str:
        try:
            return resp.get("conversation_id")
        except Exception as e:
            raise Exception(f"❌ Invalid JSON response: {e} {resp}")

    def poll_result(self, resp: dict) -> GenieResponse:
        try:
            return self.poll_for_result(resp["conversation_id"], resp["message_id"])
        except Exception as e:
            raise Exception(f"""❌ Invalid JSON response: {resp.text}""")

    def ask_followup_question(self, question, conversation_id) -> dict:
        try:
            # https://docs.databricks.com/api/workspace/genie/createmessage
            resp = self.create_message(conversation_id, question)
            return resp
        except requests.exceptions.ConnectionError as e:
            raise requests.exceptions.ConnectionError(
                f"❌ Connection error - check your network and workspace URL: {e}"
            )
        except requests.exceptions.Timeout as e:
            raise requests.exceptions.Timeout(f"❌ Request timed out: {e}")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(f"❌ Request failed: {e}")
        except ValueError as e:
            raise ValueError(f"❌ Invalid JSON response: {e}")
        except Exception as e:
            raise Exception(f"Error creating message: {e}")
