# Databricks notebook source
# MAGIC %pip install -U databricks-mcp databricks-sdk databricks-langchain mlflow
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %pip freeze

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

from databricks.sdk import WorkspaceClient
import mlflow
from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")

mlflow.langchain.autolog()

ws_client = WorkspaceClient()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test connection to external MCP via CURL

# COMMAND ----------

# MAGIC %sh
# MAGIC curl -i POST \
# MAGIC   -H "Authorization: Bearer mcp_k1.IflPmhPDseCWsR0NiXVI0DZjLkp9_ImLoMtfZorRfKc.1uhC9PQuDSH6" \
# MAGIC   -H "Content-Type: application/json" \
# MAGIC   -H "Accept: application/json, text/event-stream" \
# MAGIC   "https://glama.ai/endpoints/w0rcnqusm3/mcp" \
# MAGIC   -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "curl-client", "version": "1.0"}}, "id": 1}' \
# MAGIC   --max-time 60

# COMMAND ----------

# MAGIC %md
# MAGIC ## Connect to External MCP server via UC Connection
# MAGIC Doing it programmatically in SQL does not create a Is MCP Connection flag. You'll need to edit in UC UI later

# COMMAND ----------

# MAGIC %sql
# MAGIC DROP CONNECTION IF EXISTS conn_aichemy_opentargets;
# MAGIC CREATE CONNECTION conn_aichemy_opentargets
# MAGIC TYPE HTTP
# MAGIC OPTIONS (
# MAGIC   host 'https://glama.ai',
# MAGIC   base_path '/endpoints/w0rcnqusm3/mcp/',
# MAGIC   bearer_token 'mcp_k1.IflPmhPDseCWsR0NiXVI0DZjLkp9_ImLoMtfZorRfKc.1uhC9PQuDSH6'
# MAGIC )
# MAGIC COMMENT 'Create connection with external Open Targets MCP server by Augmented Nature on glama.ai'
# MAGIC ;

# COMMAND ----------

# MAGIC %md
# MAGIC ## Enable MCP in the UC explorer
# MAGIC Unity Catalog > External Data > Connections > <the_connection_you_created> > Edit
# MAGIC Keep clicking Next until you find the page to check the `Is MCP connection` box and save it
# MAGIC ![](../img/is_mcp.png)
# MAGIC
# MAGIC ### Grant permissions
# MAGIC On the UC page with your connection, click on the Permissions tab, grant:
# MAGIC 1. All users `USE CONNECTION`
# MAGIC 2. owner/yourself `ALL PRIVILEGES` and `MANAGE`

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option 1 for calling external MCP server: SQL
# MAGIC Not Recommended for stateful MCP servers<br>
# MAGIC Can't specify `curl` flags like `-i` to retrieve session id<br>
# MAGIC If `Mcp-Session-Id` is required, get it from the `curl` call above

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT http_request(
# MAGIC   conn => 'conn_aichemy_opentargets',
# MAGIC   method => 'POST',
# MAGIC   path => '',
# MAGIC   json => '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "search_targets", "arguments": {"query": "glp-1"}}, "id": 2}',
# MAGIC   headers => map(
# MAGIC     'Content-Type', 'application/json',
# MAGIC     'Accept', 'application/json, text/event-stream',
# MAGIC     'Mcp-Session-Id', '462ffd58-708d-4140-a41e-8705778a5d8b'
# MAGIC   )
# MAGIC );

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option 2: Databricks Python SDK

# COMMAND ----------

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from pprint import pprint

response = ws_client.serving_endpoints.http_request(
  conn=cfg.get("uc_connections").get("opentargets"),
  method=ExternalFunctionRequestHttpMethod.POST,
  path="",
  json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2},
  headers={"Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Mcp-Session-Id": "462ffd58-708d-4140-a41e-8705778a5d8b"}\
)
pprint(response.__dict__)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option 3: `DatabricksMCPClient`
# MAGIC Needs to be patched to disable zstd decoding and allow kwargs into `streamablehttp_client`

# COMMAND ----------

# Use the patched DatabricksMCPClient to disable zstd decoding
# from databricks_mcp import DatabricksMCPClient
from src.databricks_mcp_client import DatabricksMCPClient
import nest_asyncio

nest_asyncio.apply()

server_url = f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("opentargets")}'
mcp_client = DatabricksMCPClient(server_url=server_url, workspace_client=ws_client)
mcp_client.list_tools(timeout=60, terminate_on_close=False)

# COMMAND ----------

mcp_client.call_tool("search_targets", {"query": "glp-1"}, terminate_on_close=False, timeout=120)
