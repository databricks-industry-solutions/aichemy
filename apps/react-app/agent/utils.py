from pathlib import Path
import os

from databricks.sdk import WorkspaceClient
from base64 import b64decode


def _load_config():
    """Load config.yml from app root (parent of agent/)."""
    try:
        import yaml
        app_root = Path(__file__).resolve().parent.parent
        with open(app_root / "config.yml") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def init_mlflow():
    """Set MLflow tracking URI and experiment. Single place for agent and web server."""
    import mlflow
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "databricks")
    registry_uri = os.environ.get("MLFLOW_REGISTRY_URI", "databricks-uc")
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID")

    if experiment_id is None:
        cfg = _load_config()
        experiment_id = (cfg or {}).get("experiment_id", "1001868044455114")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(registry_uri)
    mlflow.set_experiment(experiment_id=str(experiment_id).strip())


def get_secret(scope: str, key: str) -> str:
    w0 = WorkspaceClient()
    secret_base64 = w0.secrets.get_secret(scope, key).value
    return b64decode(secret_base64).decode("utf-8")


def init_workspace_client(cfg):
    client_id = get_secret(scope='aichemy', key='client_id')
    client_secret = get_secret(scope='aichemy', key='client_secret')
    ws_client = WorkspaceClient(
        host=cfg["host"],
        client_id=client_id,
        client_secret=client_secret
    )
    return ws_client