from databricks.sdk import WorkspaceClient
from base64 import b64decode

def get_secret(scope: str, key: str) -> str:
    w0 = WorkspaceClient()
    secret_base64 = w0.secrets.get_secret(scope, key).value
    return b64decode(secret_base64).decode("utf-8")
