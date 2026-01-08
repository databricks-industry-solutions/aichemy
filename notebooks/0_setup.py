# Databricks notebook source
# MAGIC %pip install -U mlflow databricks-sdk psycopg psycopg_pool
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# Provide SP credentials here for connecting to LakeBase
# Method 1: Get from secrets
client_id = dbutils.secrets.get(scope="aichemy", key="client_id")
client_secret = dbutils.secrets.get(scope="aichemy", key="client_secret")

# COMMAND ----------

# Method 2: Enter into widgets
dbutils.widgets.text(name="client_id", defaultValue=client_id,  label="Service Principal Client ID")
dbutils.widgets.text(name="client_secret", defaultValue=client_secret, label="Service Principal Client Secret")
client_id = dbutils.widgets.get("client_id")
client_secret = dbutils.widgets.get("client_secret")

# COMMAND ----------

from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")
cfg.to_dict()

# COMMAND ----------

ws_info = ws_client.current_user.me()
display(ws_info)

# COMMAND ----------

from databricks.sdk import WorkspaceClient

instance_name = cfg.get("lakebase").get("instance_name")
ws_client = WorkspaceClient(
    host=cfg.get("host"),
    client_id=client_id,
    client_secret=client_secret
)

# COMMAND ----------

from databricks.sdk.service.database import DatabaseInstance

# Check if database instance exist
if any(db.name == instance_name for db in ws_client.database.list_database_instances()):
    print(f"Database instance {instance_name} already exists")
else:  # database instance does not exist
    instance = ws_client.database.create_database_instance(
        DatabaseInstance(name=instance_name, capacity="CU_1")
    )

# COMMAND ----------

# MAGIC %md
# MAGIC Ensure that you have:
# MAGIC 1. Granted the necessary permissions (SP can CreateDB) to the Lakebase instance
# MAGIC 2. `CREATE DATABASE <database_name>;`
# MAGIC 3. `GRANT ALL PRIVILEGES ON SCHEMA public TO "<CLIENT_ID>";`

# COMMAND ----------

from src.lakebase import LakebaseConnect
from databricks.sdk import WorkspaceClient

dbClient = LakebaseConnect(
    user = client_id,
    password = None, # leave None to generate ephemeral token (1h)
    instance_name = cfg.get("lakebase").get("instance_name"), 
    database = cfg.get("lakebase").get("database"),
    wsClient = ws_client
)
dbClient.test_query()
