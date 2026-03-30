# AiChemy Solution Accelerator

[![Databricks](https://img.shields.io/badge/Databricks-Solution_Accelerator-FF3621?style=for-the-badge&logo=databricks)](https://databricks.com)
[![Unity Catalog](https://img.shields.io/badge/Unity_Catalog-Enabled-00A1C9?style=for-the-badge)](https://docs.databricks.com/en/data-governance/unity-catalog/index.html)
[![Serverless](https://img.shields.io/badge/Serverless-Compute-00C851?style=for-the-badge)](https://docs.databricks.com/en/compute/serverless.html)

## Usage
See more in [blog](https://docs.google.com/document/d/1Lmbl2XMKTj7mMda7rObBxvQFMmIpl1OY4k8rDKNDxSQ/edit?tab=t.0#heading=h.a5gdsuyydapd)
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

-----------------------------------
## Installation
1. Clone this repo into your Databricks workspace as a git folder

<img width="1726" height="677" alt="Screenshot 2025-07-23 at 11 05 25 AM" src="https://github.com/user-attachments/assets/55b1729f-ad07-420e-a271-843266abfb71" />

2. Open the Asset Bundle Editor in the Databricks UI

<img width="1120" height="665" alt="Screenshot 2025-07-23 at 11 06 12 AM" src="https://github.com/user-attachments/assets/d1f91256-eb8f-4456-8d88-c0a37b1bd4c5" />

3. Click on "Deploy"

<img width="1523" height="902" alt="Screenshot 2025-07-23 at 11 09 37 AM" src="https://github.com/user-attachments/assets/9564cbdd-c5c5-4210-bf27-2b19e6efc85b" />

4. Navigate to the Deployments tab in the Asset Bundle UI (🚀 icon) and click "Run" on the job available. This will run the notebooks from this project sequentially.

<img width="1527" height="880" alt="Screenshot 2025-07-23 at 11 10 13 AM" src="https://github.com/user-attachments/assets/0f612882-7123-449b-8349-1835bc59523c" />

NB: Genie spaces need to be [created](https://docs.databricks.com/aws/en/genie/set-up) via the UI


---------------------------------
## Contributing
1. **git clone** this project locally
2. Utilize the Databricks CLI to test your changes against a Databricks workspace of your choice
3. Contribute to repositories with pull requests (PRs), ensuring that you always have a second-party review from a capable teammate

## 📄 Third-Party Package Licenses
&copy; 2025 Databricks, Inc. All rights reserved. The source in this project is provided subject to the Databricks License [https://databricks.com/db-license-source]. All included or referenced third party libraries are subject to the licenses set forth below.

| Package | License | Copyright |
|---------|---------|-----------|
| rdkit | Cheminformatics package (C++ and Python based) | BSD 3-Clause |
| mols2grid | Interactive molecular grid viewer for Jupyter | BSD 3-Clause |
| databricks-ai-bridge | APIs to interact with Databricks AI features such as AI/BI Genie and Vector Search | Databricks |
| databricks-sdk | SDK to interact with Databricks | Apache 2.0 |
| databricks-vectorsearch | SDK to interact with Databricks Vector Search | Databricks |
| databricks-langchain | LangChain integration for Databricks including memory | Apache 2.0 |
| databricks-mcp | Model Context Protocol support for Databricks | Apache 2.0 |
| databricks-agents | SDK for deploying and managing Databricks agents | Databricks |
| mlflow | ML lifecycle management and agent serving framework | Apache 2.0 |
| langchain-core | Core abstractions for the LangChain framework | MIT |
| langchain-mcp-adapters | LangChain adapters for Model Context Protocol tools | MIT |
| langgraph-supervisor | Multi-agent supervisor orchestration for LangGraph | MIT |
| mcp | Model Context Protocol Python SDK | MIT |
| openai | OpenAI API client library | Apache 2.0 |
| fastapi | Modern Python web framework for building APIs | MIT |
| uvicorn | ASGI web server for Python | BSD 3-Clause |
| pydantic | Data validation using Python type annotations | MIT |
| psycopg | PostgreSQL database adapter for Python | LGPL 3.0 |
| PyYAML | YAML parser and emitter for Python | MIT |
| react | JavaScript library for building user interfaces | MIT |
| react-dom | React package for DOM rendering | MIT |
| react-markdown | Markdown renderer for React | MIT |
| remark-gfm | GitHub Flavored Markdown plugin for remark | MIT |
| uuid | RFC-compliant UUID generation for JavaScript | MIT |
| vite | Next-generation frontend build tool | MIT |
