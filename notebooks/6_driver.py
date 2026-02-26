# Databricks notebook source
# MAGIC %pip install -r ../requirements.txt
# MAGIC %pip install -U -qq databricks-agents uv
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# Test that databricks-langchain[memory] was installed
from databricks_ai_bridge.lakebase import AsyncLakebasePool

# COMMAND ----------

# MAGIC %pip freeze > requirements_driver.txt

# COMMAND ----------

import os

os.environ["MLFLOW_LOCK_MODEL_DEPENDENCIES"] = "true"

# COMMAND ----------

import mlflow
from mlflow.models import ModelConfig
from src.utils import get_SP_credentials

mlflow.set_registry_uri('databricks-uc')

cfg = ModelConfig(development_config="config.yml")

client_id, client_secret = get_SP_credentials(
    scope='aichemy',
    client_id_key='client_id', #if retrieving secrets (but doesn't work within mlflow logging)
    client_secret_key='client_secret', #if retrieving secrets (but doesn't work within mlflow logging)
)

# COMMAND ----------

catalog_name = cfg.get("catalog")
schema_name = cfg.get("schema")
model_name = "aichemy"

registered_name = f"{catalog_name}.{schema_name}.{model_name}"
artifact_path = "agent"

# COMMAND ----------

from uuid import uuid4

query = "What is the CID of aspirin?"
input_message = {
    "messages": [
        {
            "role": "user",
            "content": query
        }
    ]
}
input = {
    "input": input_message["messages"],
    "custom_inputs": {"thread_id": str(uuid4())}
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log the `agent` as an MLflow model

# COMMAND ----------

# Log the model to MLflow
import os
from mlflow.models.resources import (
    DatabricksVectorSearchIndex, 
    DatabricksServingEndpoint,
    DatabricksFunction,
    DatabricksUCConnection,
    DatabricksGenieSpace,
    DatabricksTable,
    DatabricksSQLWarehouse,
    DatabricksLakebase
)

with mlflow.start_run():
    logged_agent_info = mlflow.pyfunc.log_model(
        python_model=os.path.join(os.getcwd(), '5_multiagent'),
        name=artifact_path,
        registered_model_name=registered_name,
        model_config="config.yml",
        pip_requirements="../requirements.txt",
        code_paths = ["../src"],
        input_example=input,
        # specify resources for deployed server to have explicit access
        resources=[
            DatabricksServingEndpoint(endpoint_name=cfg.get("llm_endpoint")),
            DatabricksVectorSearchIndex(index_name=cfg.get('retriever')['vs_index']),
            DatabricksFunction(function_name=cfg.get("uc_functions")[0]),
            DatabricksFunction(function_name=cfg.get("uc_functions")[1]),
            DatabricksUCConnection(connection_name=cfg.get("uc_connections")["pubchem"]),
            DatabricksUCConnection(connection_name=cfg.get("uc_connections")["pubmed"]),
            DatabricksUCConnection(connection_name=cfg.get("uc_connections")["opentargets"]),
            DatabricksGenieSpace(genie_space_id=cfg.get("genie_space_id")),
            DatabricksTable(table_name=cfg.get("genie_table")),
            DatabricksSQLWarehouse(warehouse_id="75fd8278393d07eb"),
            DatabricksLakebase(database_instance_name=cfg.get("lakebase_agent")["instance_name"]),
        ]
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test inferencing

# COMMAND ----------

DBTITLE 1,Cell 12
model_uri = f"runs:/{logged_agent_info.run_id}/{artifact_path}"
# model_uri = 'runs:/f6fd223bea3c42bd9df54edc30bd5d52/agent' #v3
model_uri

# COMMAND ----------

loaded_model = mlflow.pyfunc.load_model(model_uri)
response = loaded_model.predict(input)
response

# COMMAND ----------

thread_id = str(uuid4())
input_message = {
    "messages": [
        {
            "role": "user",
            "content": "Get the ECFP4 fingerprint embedding of asprin as a bitstring using the get_embedding(smiles) tool in the chem_utils agent"
        }
    ]
}
input = {
    "input": input_message["messages"],
    "custom_inputs": {"thread_id": thread_id, "recursion_limit": 50}
}
loaded_model.predict(input)

# COMMAND ----------

input_message = {
    "messages": [
        {
            "role": "user",
            "content": "What molecule in ZINC is most structurally similar to aspirin based on ECFP4?"
        }
    ]
}
input = {
    "input": input_message["messages"],
    "custom_inputs": {"thread_id": thread_id}
}
loaded_model.predict(input)

# COMMAND ----------

input_message = {
    "messages": [
        {
            "role": "user",
            "content": "How does the 2 most similar molecules in ZINC look like?"
        }
    ]
}
input = {
    "input": input_message["messages"],
    "custom_inputs": {"thread_id": thread_id}
}
loaded_model.predict(input)

# COMMAND ----------

input_message = {
    "messages": [
        {
            "role": "user",
            "content": "Search for Pubmed articles related to ZINC001362825912 use in humans"
        }
    ]
}
input = {
    "input": input_message["messages"],
    "custom_inputs": {"thread_id": thread_id}
}
loaded_model.predict(input)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy model

# COMMAND ----------

from src.utils import get_latest_model_version

latest_version = get_latest_model_version(registered_name)
latest_version

# COMMAND ----------

from databricks import agents

# Deploy the model to the review app and a model serving endpoint
agents.deploy(model_name=registered_name,
              model_version=latest_version,
              endpoint_name="aichemy",
              scale_to_zero=False,
              environment_vars={
                "MAX_MODEL_LOADING_TIMEOUT": "600",
                "DATABRICKS_CLIENT_ID": client_id,
                "DATABRICKS_CLIENT_SECRET": client_secret
                }
              )

# COMMAND ----------


