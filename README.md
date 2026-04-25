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
    - my_catalog.my_schema.get_ecfp_embedding
    - my_catalog.my_schema.get_img_url

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
  zinc_molecular_search:
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
  - What diseases are associated with EGFR?
  - List all the drugs in the GLP-1 agonists ATC class in DrugBank.
  - Get the latest review study on the GI toxicity of danuglipron.
  - Show me compounds similar to vemurafenib. Display their structures.

# --- Prompts for each subagent and the supervisor ---
prompts:
  chem_utils: >-
    You are a python function that can generate ECFP molecular fingerprint embeddings
    from SMILES and display molecule PNG images from the PubChem website by CID in markdown.
  zinc_molecular_search: >-
    Search for drug-like chemicals in the ZINC database based on ECFP molecular
    fingerprint embeddings
  mcp: >-
    You are a multi-MCP server agent connected to:
    1. PubChem MCP server that provides everything about chemical compounds
    2. PubMed MCP server that searches biomedical literature and retrieves free full text if any.
    3. OpenTargets MCP server that provides everything about drug targets and their associations with diseases and drugs.
    Most PubChem tools (e.g. get_compound_info) except for search_compounds expect a CID.
  memory: >-
    You save and delete long-term user memories. Save when the user explicitly
    asks to remember something. Proactively save durable preferences, roles,
    ongoing projects, and recurring constraints. Do NOT save trivial or
    short-lived facts. You do NOT need to retrieve memories — that happens
    automatically before the conversation starts.
  supervisor: >-
    You are a supervisor managing 5 agents. Route to the agent required to fulfill the request.

    1. Drugbank agent: generates text-to-SQL queries to Drugbank of FDA-approved drugs and their properties

    2. ZINC agent: searches for drug-like molecules and their properties from the ZINC database
    based on ECFP4 molecular fingerprint embeddings represented as a 1024-char bitstring.

    3. Chem utilities agent: display molecule image PNG files from PubChem website by CID in
    markdown or compute ECFP4 molecular fingerprint embeddings in a 1024-char bitstring for a
    given SMILES structure. If missing SMILES input, query it from a chemical name using the
    PubChem MCP agent's search_compound tool.

    4. MCP agent: connects to the PubChem, PubMed and OpenTargets MCP servers

    5. Memory agent: saves or deletes long-term user memories. ONLY route here when the user
    explicitly asks to "remember", "store", "note that", "from now on", "forget", or "delete memory".
    User memories are already loaded automatically — do NOT route here to retrieve them.

    Because you are an autonomous multi-agent system, do not ask for more follow up information.
    Instead, use chain-of-thought to reason and break down the request into achievable steps
    based on the agentic tools that you have access to.
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
