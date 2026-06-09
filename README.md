# AiChemy Solution Accelerator
[![Databricks](https://img.shields.io/badge/Databricks-Apps-FF3621?style=for-the-badge&logo=databricks)](https://databricks.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Supervisor-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Lakebase](https://img.shields.io/badge/Lakebase-Postgres-336791?style=for-the-badge&logo=postgresql)](https://docs.databricks.com/en/database/lakebase.html)

## Usage
See more in [blog](http://databricks.com/blog/aichemy-next-generation-agent-mcp-skills-and-custom-data-drug-discovery)
#### Use Case 1: Understand disease mechanisms, find druggable targets and lead generation
The Guided Tasks panel provides necessary prompts and agent Skills to perform the key steps in a drug discovery workflow of disease -> target -> drug -> literature validation.<br>
<br>
- First, given a disease, e.g. ER+/HER2- breast cancer, find therapeutic targets (i.e. ESR1).
- Second, given the target e.g, ESR1, find drugs associated with a target.
- Third, given a drug candidate, e.g., camizestrant, check the literature for supporting evidence.
<img width="1675" height="850" alt="esr1_drugs" src="https://github.com/user-attachments/assets/ef85e4bb-fec8-423d-85ad-f67b2ac6507f" />


#### Use Case 2: Lead generation by chemical similarity
Say we want to discover a follow up to Elacestrant, the first oral SERM approved in 2023. We can look up a large chemical library like the ZINC15 database for drug-like molecules structurally similar to Elacestrant and thus are likely to share similar properties according to Quantitative Structure Activity Relationship (QSAR) principles. We can query Databricks Vector Search which stores the 1024-bit Extended-Connectivity Fingerprint (ECFP) molecular embeddings of all 250,000 molecules in ZINC using Elacestrant ECFP embedding as the query string.
<img width="1671" height="853" alt="elacestrant_sim" src="https://github.com/user-attachments/assets/8dc0a67e-babe-47d3-8bc7-8d69763679f2" />

## Setup
### 1. Installation
```
git clone git@github.com:databricks-industry-solutions/aichemy.git
cd aichemy

# Activate your virtual environment
uv venv
source .venv/bin/activate
uv pip install -r apps/react-app/requirements.txt
```

### 2. Customize [`config.yml`](apps/react-app/config.yml) to your assets
The repo reads [`config.yml`](apps/react-app/config.yml) at startup and creates subagents loaded with existing genie, retriever, UC functions, MCP servers and/or Lakebase memory tools and assembles them into a langgraph supervisor with the appropriate subagent and supervisor prompts.

It assumes that the assets defined in [`config.yml`](apps/react-app/config.yml) already exists. See example [notebooks](notebooks) and [blog](http://databricks.com/blog/aichemy-next-generation-agent-mcp-skills-and-custom-data-drug-discovery) on how to set up the various assets.

A. [OPTIONAL] Change [`logo.svg`](apps/react-app/public/logo.svg) to your app logo. <br>
B. [OPTIONAL] Add custom skills to the [`skills`](apps/react-app/skills) folder. <br>
C. Align [`app.yaml`](apps/react-app/app.yaml) with [`config.yml`](apps/react-app/config.yml), particularly `MLFLOW_EXPERIMENT_ID`.<br>
D. Edit [`config.yml`](apps/react-app/config.yml). Define which LLM to use, which subagents to create, how they connect to data, and what the supervisor prompt says.

```yaml
# --- Workspace & model ---
host: https://your-workspace.cloud.databricks.com/
catalog: my_catalog
schema: my_schema
experiment_id: mlflow_experiment_id  # where agent traces will be logged
llm_endpoint: databricks-claude-sonnet-4

# --- Genie subagents (text-to-SQL) ---
genie:
  drugbank: # name your genie here
    space_id: <genie_space_id>
    table: my_catalog.my_schema.drugbank

# --- UC function subagents ---
uc_functions:
  analytics: # name your functions agent here
    - my_catalog.my_schema.get_embedding

# --- UC connections (wraps around external URL) ---
uc_connections:
  pubmed: conn_pubmed_mcp

# --- External MCP servers ---
external_mcp:
  mcp1:
    url: https://example.com/mcp
    scope: secret_scope_for_bearer_token
    secret: secret_for_bearer_token

# --- Vector Search retriever subagents ---
retriever:
  zinc_vector_search:
    vs_endpoint: my_vs_endpoint
    vs_index: my_catalog.my_schema.zinc_vs
    vs_source: my_catalog.my_schema.zinc_table
    embedding: databricks-gte-large-en  # required but ignored
    k: 5
    text_column: content
    columns:
      - id
      - content
      - title
    search_type: vector
    tool_description: Search by embedding similarity

# --- Lakebase (memory + project persistence) ---
lakebase:
  project_id: <lakebase_project_id>
  branch_id: <branch_id>
  endpoint_id: <endpoint_id>
  database: databricks_postgres
  embedding: databricks-gte-large-en
  embedding_dim: 1024

example_questions:
  - Show me the molecule image of orforglipron.
  - What diseases are associated with EGFR?

# --- Prompts for each subagent and the supervisor ---
prompts:
  chem_utils: >-
    You are a python function that can generate 1024-bit ECFP molecular fingerprint embeddings
    from SMILES. Get the SMILES from the PubChem MCP server. Do not fabricate SMILES.
    You also have the ability to display molecule image PNG files from PubChem website by CID in markdown.
    You also have the ability to predict ADMET properties calling an external ChemProp MPNN model. This would require you first look up SMILES as input to the ADMET prediction tool.
  zinc_vector_search: >-
    You search the ZINC database of 250,000 drug-like chemicals for structural similarity.
    Pass a SMILES string directly to your search tool, not the 1024-bit ECFP bitstring.
  mcp: >-
    You are a multi-MCP server agent connected to several knowledge bases via MCP servers such as PubChem, PubMed, OpenTargets, ClinicalTrials, OpenFDA, US Census, CMS Coverage, BioPortal, BioContext, etc.
    Some of these MCP servers may be disabled in the UI so when listing tools, do check if the tool is disabled before listing it.
    If a tool call returns a response containing "not yet implemented", "not implemented", or "coming soon", treat that tool as unavailable for this request.
    Do not retry it. Instead, skip that step, note it as unavailable, and continue with the remaining steps using other available tools.
  memory: >-
    You save and delete long-term user memories. Save when the user explicitly
    asks to remember something. Proactively save durable preferences, roles,
    ongoing projects, and recurring constraints. Do NOT save trivial or
    short-lived facts. You do NOT need to retrieve memories — that happens
    automatically before the conversation starts.
  supervisor: >-
    You are a supervisor agent that handles the routing to the following agents depending on the request: 
```

### 3. Run locally
Do local development for faster iteration of your agent app.

**Prerequisite:** [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install) <br>
Ensure you can [authenticate](https://docs.databricks.com/aws/en/dev-tools/cli/authentication) into your Databricks Workspace.
```
databricks auth login
```

Start the local servers.
```
cd apps/react-app

# Option 1: Starts both agent server and web server in a single script ([start.py](apps/react-app/start.py))
# Go to http://localhost:{DATABRICKS_APPS_PORT}, e.g. 8010, 8000
uv run start.py 

# Option 2: Start agent server then webserver
# Starts only agent server
uv run agent/start_server.py --port 8080

# Starts web server
uv run server/web_server.py

# To invoke the agent server
curl -X POST http://localhost:{AGENT_PORT}/invocations \
-H "Content-Type: application/json" \
-d '{
   "input": [{"role": "user", "content": "What is my favorite color?"}],
   "context": {"user_id": "test@example.com"},
   "stream": true
}'
```
Set the ports using environment variables `AGENT_PORT` and `DATABRICKS_APP_PORT` respectively or in [`app.yaml`](apps/react-app/app.yaml).

NB: [`app.yaml`](apps/react-app/app.yaml) is a way of defining environment variables for Databricks Apps but not in your local environment. Remember to align the environment variables according to your [`config.yml`](apps/react-app/config.yml).

### 3. Run remotely in [Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/deploy#deploy-the-app)
When you are satisfied with the local agent app, deploy it to Databricks Apps.

#### Option 1: Using git
1. Push to remote git repo.
2. On your Databricks workspace, create a git folder based on the remote git repo (only do this once). Subsequently, you only need to push/pull updates to/from the git repo. 
3. Create a custom Databricks App pointing to the folder `app/react-app`

#### Option 2: Using Databricks CLI
```
cd apps/react-app

# Sync from local folder to Databricks workspace
databricks sync --watch . /Workspace/Users/my-email@org.com/my-app

# Deploy app based on the Databricks folder
databricks apps deploy my-app-name \
   --source-code-path /Workspace/Users/my-email@org.com/my-app
```

Remember to grant the app SP the appropriate permissions to your underlying assets (Experiment and secret scope)

### 4. Databricks Assets Bundle

The project uses Databricks Asset Bundles. [`databricks.yml`](databricks.yml) is generated from [`config.yml`](apps/react-app/config.yml) by [`gen_databricksyaml.py`](gen_databricksyaml.py). The generator syncs workspace host, catalog/schema, experiment, LLM endpoint, and the `lakebase` block (`project_id`, `branch_id`, `endpoint_id`, `database`). Deploy with:

```bash
./deploy.sh
```

Or use the Asset Bundle Editor in the Databricks UI — clone the repo as a Git Folder, open the bundle editor, and click **Deploy**.

#### Secret scope

The bundle creates the `aichemy` secret scope and grants the app read access to these keys:

| Secret key | Purpose |
|---|---|
| `client_id` | App service principal client ID (Lakebase, M2M auth) |
| `client_secret` | App service principal client secret |
| `pubchem_glama_api` | Bearer token for PubChem MCP (Glama) |

Secret **values** are not stored in the bundle. Populate them after the first deploy using the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/reference/secrets-commands#databricks-secrets-put-secret).
```
databricks secrets put-secret SCOPE KEY [flags]
```

#### Lakebase project

The bundle creates a Lakebase Autoscaling project (plus branch and endpoint) from the `lakebase` section in [`config.yml`](apps/react-app/config.yml). After editing those values, run `./deploy.sh --sync-only` (or `python3 gen_databricksyaml.py`) before deploy. The app is granted `CAN_CONNECT_AND_CREATE` on the configured database.

> **Note:** `lakebase.project_id` must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens (RFC 1123). If you already created a project manually, set the IDs in `config.yml` to match before syncing.


## Supported Subagent Types

| Config Key | Subagent Type | What It Does |
|---|---|---|
| `genie` | **Genie Agent** | Natural-language SQL over Unity Catalog tables via [AI/BI Genie](https://docs.databricks.com/en/genie/index.html). Each entry creates a `GenieAgent` bound to a Genie Space. |
| `retriever` | **Vector Search Retriever** | Similarity search over Databricks Vector Search indexes. Supports both text embeddings and raw vector queries (e.g., molecular fingerprints). |
| `uc_functions` | **UC Function Agent** | Calls Python UDFs registered in Unity Catalog as tools. Group related functions under a named agent. |
| `external_mcp` | **MCP Agent** | Connects to external [Model Context Protocol](https://modelcontextprotocol.io/) servers. Each server exposes its own set of tools that the agent can call. |
| `lakebase` | **Memory Agent** | Save and delete long-term user memories. Retrieval is automatic — memories are injected into context before the supervisor runs. |

## Load Custom Skills
Add custom skills into the [`skills`](apps/react-app/skills) folder. Each skill name will be inferred from the frontmatter in `SKILL.md`.

## Architecture
<img width="1279" height="719" alt="architecture" src="https://github.com/user-attachments/assets/f6196a8a-e765-4d40-8cd6-b1d30877fc87" />

```
┌─────────────────────────────────────────────────────────┐
│  Databricks App                                         │
│                                                         │
│  ┌─────────────┐    ┌────────────────────────────────┐  │
│  │  React UI   │───▶│  FastAPI Proxy                 │  │
│  │  (Vite)     │    │  (web_server.py)               │  │
│  └─────────────┘    │  • project CRUD                │  │
│                     │  • auth / SSO                  │  │
│                     │  • chat history persistence     │  │
│                     └────────────┬───────────────────┘  │
│                                  │                      │
│                     ┌────────────▼───────────────────┐  │
│                     │  MLflow AgentServer (agent.py)  │  │
│                     │  /invocations + /stream         │  │
│                     └────────────┬───────────────────┘  │
│                                  │                      │
│                     ┌────────────▼───────────────────┐  │
│                     │  LangGraph Supervisor           │  │
│                     │  ┌──────┐ ┌─────────┐ ┌─────┐  │  │
│                     │  │Genie │ │Retriever│ │ MCP │  │  │
│                     │  └──────┘ └─────────┘ └─────┘  │  │
│                     │  ┌──────────┐ ┌──────────────┐  │  │
│                     │  │UC Funcs  │ │   Memory     │  │  │
│                     │  └──────────┘ └──────┬───────┘  │  │
│                     └───────┬──────────────┼─────────┘  │
│                             │              │            │
│                     ┌───────▼────────────────────────┐  │
│                     │  Agent Skills (skills/)         │  │
│                     │  • Domain-specific SKILL.md     │  │
│                     │  • Reference docs & API specs   │  │
│                     │  • Injected as system prompts   │  │
│                     └────────────────────────────────┘  │
│                                            │            │
└────────────────────────────────────────────┼────────────┘
                                             │
                          ┌──────────────────▼──────────────────┐
                          │  Lakebase Autoscaling Postgres      │
                          │  • Checkpointer (conversation state)│
                          │  • Store (long-term user memories)  │
                          │  • Project metadata & chat history  │
                          └─────────────────────────────────────┘
```

## Key Dependencies
See [requirements.txt](apps/react-app/requirements.txt).
| Package | Purpose |
|---|---|
| `langgraph-supervisor` | Multi-agent supervisor orchestration |
| `databricks-langchain` | Genie, Vector Search, MCP, UC Functions, Lakebase memory |
| `mlflow` | Agent serving (`AgentServer`) and tracing |
| `fastapi` | Backend proxy server |
| `psycopg` | Lakebase Postgres connectivity |
| `react` + `vite` | Frontend chat UI |

## [License](LICENSE.md)

&copy; 2025 Databricks, Inc. All rights reserved. The source in this project is provided subject to the [Databricks License](https://databricks.com/db-license-source). Third-party libraries are subject to their respective licenses.
