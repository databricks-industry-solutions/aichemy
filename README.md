# Engram — Config-Driven Supervisor Agents with Persistent Memory on Databricks Apps

[![Databricks](https://img.shields.io/badge/Databricks-Apps-FF3621?style=for-the-badge&logo=databricks)](https://databricks.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Supervisor-1C3C3C?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Lakebase](https://img.shields.io/badge/Lakebase-Postgres-336791?style=for-the-badge&logo=postgresql)](https://docs.databricks.com/en/database/lakebase.html)

> *In neuroscience, an **engram** is the physical trace of a memory stored in the brain.*

Engram is a framework for building **memory-powered multi-agent supervisors** on Databricks. Define your subagents, tools, and prompts in a single [`config.yml`](apps/react-app/config.yml) — Engram automatically wires up the LangGraph supervisor, connects to Lakebase Autoscaling Postgres for persistent memory, and serves everything as a Databricks App with a React frontend.

## What It Does

- **One config, many agents** — A single [`config.yml`](apps/react-app/config.yml) declares your entire agent system: subagents, tools, data sources, and routing prompts. No code changes needed.
- **Short-term memory** — Full conversation state is checkpointed to Lakebase via `AsyncCheckpointSaver`, so multi-turn conversations survive server restarts without resending chat history.
- **Long-term memory** — Per-user facts, preferences, and notes are stored in Lakebase via `AsyncDatabricksStore` with semantic search. Memories are retrieved automatically before each turn and injected into context.
- **React web app** — A modern chat interface with project management, guided workflow tasks, an agent tools panel, and streaming responses.
- **MLflow tracing** — Every agent invocation is traced end-to-end for observability, debugging, and evaluation.

## Supported Subagent Types

Each top-level key in [`config.yml`](apps/react-app/config.yml) maps to a subagent type that is auto-built at startup:

| Config Key | Subagent Type | What It Does |
|---|---|---|
| `genie` | **Genie Agent** | Natural-language SQL over Unity Catalog tables via [AI/BI Genie](https://docs.databricks.com/en/genie/index.html). Each entry creates a `GenieAgent` bound to a Genie Space. |
| `retriever` | **Vector Search Retriever** | Similarity search over Databricks Vector Search indexes. Supports both text embeddings and raw vector queries (e.g., molecular fingerprints). |
| `uc_functions` | **UC Function Agent** | Calls Python UDFs registered in Unity Catalog as tools. Group related functions under a named agent. |
| `external_mcp` | **MCP Agent** | Connects to external [Model Context Protocol](https://modelcontextprotocol.io/) servers. Each server exposes its own set of tools that the agent can call. |
| `lakebase` | **Memory Agent** | Save and delete long-term user memories. Retrieval is automatic — memories are injected into context before the supervisor runs. |

All subagents are assembled into a single LangGraph supervisor at startup. The `prompts.supervisor` section in [`config.yml`](apps/react-app/config.yml) teaches the LLM how to route across them.

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
│                     └──────────────────────┼─────────┘  │
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

## Quick Start

### 1. Edit [`apps/react-app/config.yml`](apps/react-app/config.yml)

This is the **only file you need to change**. It defines everything: which LLM to use, which subagents to create, how they connect to data, and what the supervisor prompt says.

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

# --- External MCP servers ---
external_mcp:
  my_api: https://example.com/mcp

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

The framework reads this file at startup and automatically:
- Creates a `GenieAgent` for each entry under `genie`
- Creates a UC function agent for each group under `uc_functions`
- Loads MCP tools from each server under `external_mcp`
- Creates a `VectorSearchRetrieverTool` agent for each entry under `retriever`
- Creates a memory agent connected to Lakebase
- Wires them all into a `langgraph-supervisor` using the `prompts.supervisor` instruction

### 2. Deploy

The project uses Databricks Asset Bundles. [`databricks.yml`](databricks.yml) is generated from [`config.yml`](apps/react-app/config.yml) by [`gen_databricksyaml.py`](gen_databricksyaml.py). Deploy with:

```bash
./deploy.sh
```

Or use the Asset Bundle Editor in the Databricks UI — clone the repo as a Git Folder, open the bundle editor, and click **Deploy**.

### 3. Run Setup Jobs

After deploying, run the data setup job from the Deployments tab. This loads source data, creates Vector Search indexes, and sets up Genie Spaces.

## Project Structure

```
├── databricks.yml                  # Asset Bundle definition
├── apps/react-app/
│   ├── config.yml                  # ⬅ THE FILE YOU EDIT
│   ├── app.yaml                    # Databricks App runtime config
│   ├── agent/
│   │   ├── agent.py                # Supervisor builder (reads config.yml)
│   │   ├── responses_agent.py      # ResponsesAgent with Lakebase memory
│   │   ├── utils.py                # MCP, auth, tool metadata helpers
│   │   └── utils_memory.py         # Long-term memory save/delete tools
│   ├── server/
│   │   └── web_server.py           # FastAPI proxy + Lakebase project DB
│   └── src/                        # React frontend
│       ├── App.jsx
│       └── components/
│           ├── ChatPanel.jsx
│           ├── AgentPanel.jsx
│           └── Sidebar.jsx
└── notebooks/                      # Data loading & setup notebooks
```

## Key Dependencies

| Package | Purpose |
|---|---|
| `langgraph-supervisor` | Multi-agent supervisor orchestration |
| `databricks-langchain` | Genie, Vector Search, MCP, UC Functions, Lakebase memory |
| `mlflow` | Agent serving (`AgentServer`) and tracing |
| `fastapi` | Backend proxy server |
| `psycopg` | Lakebase Postgres connectivity |
| `react` + `vite` | Frontend chat UI |

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this project is provided subject to the [Databricks License](https://databricks.com/db-license-source). Third-party libraries are subject to their respective licenses.
