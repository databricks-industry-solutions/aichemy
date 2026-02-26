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
# MAGIC   -H "Content-Type: application/json" \
# MAGIC   -H "Accept: application/json, text/event-stream" \
# MAGIC   "https://mcp.platform.opentargets.org/mcp" \
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
# MAGIC   host 'https://mcp.platform.opentargets.org',
# MAGIC   base_path '/mcp',
# MAGIC   bearer_token 'anything'
# MAGIC )
# MAGIC COMMENT 'Create connection with external Open Targets MCP server'
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
# MAGIC   json => '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "curl-client", "version": "1.0"}}, "id": 1}',
# MAGIC   headers => map(
# MAGIC     'Content-Type', 'application/json',
# MAGIC     'Accept', 'application/json, text/event-stream'
# MAGIC   )
# MAGIC );

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT http_request(
# MAGIC   conn => 'conn_aichemy_opentargets',
# MAGIC   method => 'POST',
# MAGIC   path => '',
# MAGIC   json => '{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "search_entities", "arguments": {"query_strings": ["glp-1"]}}, "id": 2}',
# MAGIC   headers => map(
# MAGIC     'Content-Type', 'application/json',
# MAGIC     'Accept', 'application/json, text/event-stream',
# MAGIC     'Mcp-Session-Id', 'a623134b01f341c2ab532cc9ba48ff1f'
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
    "Mcp-Session-Id": "a623134b01f341c2ab532cc9ba48ff1f"}\
)
pprint(response.__dict__)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option 3: `DatabricksMultiServerMCPClient` from `databricks-langchain`

# COMMAND ----------

from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient
import asyncio

mcp_client = DatabricksMultiServerMCPClient([
    DatabricksMCPServer(
        name="opentargets",
        url=f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("opentargets")}',
    )
])
await mcp_client.get_tools()

# COMMAND ----------

server_name = None
server_names = [server_name] if server_name is not None else list(mcp_client.connections.keys())
print(server_names)
load_tool_tasks = [
    asyncio.create_task(
        super(DatabricksMultiServerMCPClient, mcp_client).get_tools(server_name=name)
    )
    for name in server_names
]
tools_list = await asyncio.gather(*load_tool_tasks,  return_exceptions=True)
tools_list

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option 4: `DatabricksMCPClient` from `databricks-mcp`
# MAGIC Needs to be patched to disable zstd decoding and allow kwargs into `streamablehttp_client`

# COMMAND ----------

# Use the patched DatabricksMCPClient to disable zstd decoding
from databricks_mcp import DatabricksMCPClient
#from src.databricks_mcp_client import DatabricksMCPClient
import nest_asyncio

nest_asyncio.apply()

server_url = f'{cfg.get("host")}api/2.0/mcp/external/{cfg.get("uc_connections").get("opentargets")}'
mcp_client = DatabricksMCPClient(server_url=server_url, workspace_client=ws_client)
mcp_client.list_tools()

# COMMAND ----------

mcp_client.call_tool("search_entities", {"query": "glp-1"})
