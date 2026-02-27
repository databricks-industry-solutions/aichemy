from databricks.sdk import WorkspaceClient
import mlflow


def get_SP_credentials(
    scope: str,
    client_id_key: str,
    client_secret_key: str,
    client_id_value: str = None,
    client_secret_value: str = None,
):
    # Do not use dbutils.secrets.get(scope="yen", key="client_secret") which is unsupported in mlflow logging in Driver
    from base64 import b64decode

    w0 = WorkspaceClient()
    if not client_id_value:
        id_base64 = w0.secrets.get_secret(scope, client_id_key).value
        client_id_value = b64decode(id_base64).decode("utf-8")
    if not client_secret_value:
        secret_base64 = w0.secrets.get_secret(scope, client_secret_key).value
        client_secret_value = b64decode(secret_base64).decode("utf-8")
    return client_id_value, client_secret_value


def get_latest_model_version(model_name):
    from mlflow.tracking import MlflowClient

    mlflow_client = MlflowClient(registry_uri="databricks-uc")
    latest_version = 1
    for mv in mlflow_client.search_model_versions(f"name='{model_name}'"):
        version_int = int(mv.version)
        if version_int > latest_version:
            latest_version = version_int
    return latest_version