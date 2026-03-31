# Super Supervisor: Declarative Supervisor Agent with Short-/Long-term Memory and React UI on Databricks Apps
[![Databricks](https://img.shields.io/badge/Databricks-Apps-FF3621?style=for-the-badge&logo=databricks)](https://databricks.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Supervisor-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Lakebase](https://img.shields.io/badge/Lakebase-Postgres-336791?style=for-the-badge&logo=postgresql)](https://docs.databricks.com/en/database/lakebase.html)


*Super Supervisor* is a declarative framework for building **memory-powered multi-agent supervisors** on Databricks. Define your subagents, tools, and prompts in a single [`config.yml`](apps/react-app/config.yml). Super Supervisor automatically assembles the LangGraph supervisor, connects to Lakebase Autoscaling Postgres for short-/long-term memory, and serves everything as a Databricks App with a React UI.

## What It Does

1. **One config, many agents**: A single [`config.yml`](apps/react-app/config.yml) declares your entire agent system: subagents, tools, data sources, and routing prompts. No code changes needed.
2. **Short-term memory**: Full conversation state is checkpointed to Lakebase via `AsyncCheckpointSaver`, so multi-turn conversations survive server restarts without resending chat history.
3. **Long-term memory**: Per-user facts, preferences, and notes are stored in Lakebase via `AsyncDatabricksStore` with semantic search. Memories are retrieved automatically before each turn and injected into context.
4. **Web session memory**
5. **Agent skills**: Add custom skills to the [`skills`](apps/react-app/skills) folder
5. **REST API**: Invoke the MLFlow AgentServer at http://localhost:{AGENT_PORT}/invocations
6. **React web app**: Modern chat interface with session memory, MCP/tool availability, agent tool history, and streaming responses.
7. **MLflow tracing**: Every invocation is traced end-to-end to MLFlow traces for observability, debugging, and evaluation.


## Usage

### 1. Setup
```
git clone git@github.com:yenlow/super_supervisor.git
cd super_supervisor

# Activate your virtual environment
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Make your edits 

A. [OPTIONAL] Change [`logo.svg`](apps/react-app/public/logo.svg) to your app logo. <br>
B. [OPTIONAL] Add custom skills to the [`skills`](apps/react-app/skills) folder. <br>
C. Align [`app.yaml`](apps/react-app/app.yaml) with [`config.yml`](apps/react-app/config.yml), particularly `MLFLOW_EXPERIMENT_ID`.
D. Edit [`config.yml`](apps/react-app/config.yml). Define which LLM to use, which subagents to create, how they connect to data, and what the supervisor prompt says.

```yaml
# --- Workspace & model ---
host: https://your-workspace.cloud.databricks.com/
catalog: my_catalog
schema: my_schema
experiment_id: <mlflow_experiment_id>  # where agent traces will be logged
llm_endpoint: databricks-claude-sonnet-4

# --- Genie subagents (text-to-SQL) ---
genie:
  sales_data: # name your genie here
    space_id: <genie_space_id>
    table: my_catalog.my_schema.sales

# --- UC function subagents ---
uc_functions:
  analytics: # name your functions agent here
    - my_catalog.my_schema.compute_metric
    - my_catalog.my_schema.forecast

# --- External MCP servers (grouped by secret scope) ---
external_mcp:
  mcp1:
    url: https://example.com/mcp
    scope: secret_scope_for_bearer_token
    secret: secret_for_bearer_token

# --- Vector Search retriever subagents ---
retriever:
  doc_search:
    vs_endpoint: my_vs_endpoint
    vs_index: my_catalog.my_schema.docs_index
    vs_source: my_catalog.my_schema.documents
    embedding: databricks-gte-large-en
    k: 5
    text_column: content
    columns:
      - id
      - content
      - title
    search_type: text
    tool_description: Search internal documents by semantic similarity

# --- Lakebase (memory + project persistence) ---
lakebase:
  project_id: <lakebase_project_id>
  branch_id: <branch_id>
  endpoint_id: <endpoint_id>
  database: databricks_postgres
  embedding: databricks-gte-large-en
  embedding_dim: 1024

# --- Prompts for each subagent and the supervisor ---
prompts:
  analytics: >-
    You compute business metrics and forecasts.
  doc_search: >-
    You search internal documents for relevant information.
  mcp: >-
    You connect to external API tools.
  memory: >-
    You save and delete long-term user memories.
  supervisor: >-
    You are a supervisor managing N agents. Route to the right agent...
```

The framework reads this [`config.yml`](apps/react-app/config.yml) file at startup and creates subagents  loaded with either genie, retriever, UC functions, MCP servers or Lakebase memory tools and assembles them into a langgraph supervisor with the appropriate subagent and supervisor prompts.

It assumes that the assets defined in [`config.yml`](apps/react-app/config.yml) already exists. See example notebooks on how to set up the various assets.


### 2. Run locally
Do local development for faster iteration of your agent app.

**Prerequisite:** [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install) <br>
Ensure you can [authenticate](https://docs.databricks.com/aws/en/dev-tools/cli/authentication) into your Databricks Workspace.
```
databricks auth login
```

Start the local servers.
```
cd apps/react-app

# Starts both agent server and web server
uv run start.py 

# Starts only agent server
uv run agent/start_server.py --port 8080

# To invoke the agent server


# Starts only web server
uv run server/web_server.py
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

### 4. Databricks Assets Bundle (TBD)

The project uses Databricks Asset Bundles. [`databricks.yml`](databricks.yml) is generated from [`config.yml`](apps/react-app/config.yml) by [`gen_databricksyaml.py`](gen_databricksyaml.py). Deploy with:

```bash
./deploy.sh
```

Or use the Asset Bundle Editor in the Databricks UI — clone the repo as a Git Folder, open the bundle editor, and click **Deploy**.


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


## Project Structure

```
├── databricks.yml                  # Asset Bundle definition
├── gen_databricksyaml.py           # Generates databricks.yml from config
├── apps/react-app/
│   ├── config.yml                  # ⬅ THE FILE YOU EDIT
│   ├── app.yaml                    # Databricks App env vars config
│   ├── start.py                    # Entrypoint
│   ├── agent/
│   │   ├── agent.py                # Supervisor builder (reads config.yml)
│   │   ├── responses_agent.py      # ResponsesAgent with Lakebase memory
│   │   ├── start_server.py         # Agent server entrypoint
│   │   ├── utils.py                # MCP, auth, tool metadata helpers
│   │   └── utils_memory.py         # Long-term memory save/delete tools
│   ├── skills/                     # Agent skill definitions
│   │   ├── skill-1/
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   │   └── skill-2/
│   │       └── SKILL.md
│   ├── server/
│   │   └── web_server.py           # Web server
│   ├── public/
│   │   └── logo.svg                # Upload your logo image here
│   └── src/                        # React frontend
│       ├── App.jsx
│       └── components/
│           ├── ChatPanel.jsx
│           ├── AgentPanel.jsx
│           └── Sidebar.jsx
└── notebooks/                      # Data loading & setup notebooks
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
