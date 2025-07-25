# AiChemy Solution Accelerator

[![Databricks](https://img.shields.io/badge/Databricks-Solution_Accelerator-FF3621?style=for-the-badge&logo=databricks)](https://databricks.com)
[![Unity Catalog](https://img.shields.io/badge/Unity_Catalog-Enabled-00A1C9?style=for-the-badge)](https://docs.databricks.com/en/data-governance/unity-catalog/index.html)
[![Serverless](https://img.shields.io/badge/Serverless-Compute-00C851?style=for-the-badge)](https://docs.databricks.com/en/compute/serverless.html)

## Usage
#### 1. Chat with your chemical library, e.g. Drugbank
Powered by [AI/BI Genie](https://www.databricks.com/product/business-intelligence/ai-bi-genie) to generate text-to-SQL to query your chemical library
![ ](./img/genie_drugbank.png)

#### 2. Search [PubChem](https://pubchem.ncbi.nlm.nih.gov/) via [PUG REST API](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)
Supports exact/substructure/superstructure search by SMILES, name, CID
![ ](./img/pubchem.png)

#### 3. Similarity Search
Find structurally similar molecules in your chemical library based on molecular fingerprints. Powered by [Databricks Vector Search](https://www.databricks.com/product/machine-learning/vector-search).
![ ](./img/vectorsearch.png)

## Installation
1. Clone this repo into your Databricks workspace as a git folder

<img width="1726" height="677" alt="Screenshot 2025-07-23 at 11 05 25 AM" src="https://github.com/user-attachments/assets/55b1729f-ad07-420e-a271-843266abfb71" />

2. Open the Asset Bundle Editor in the Databricks UI

<img width="1120" height="665" alt="Screenshot 2025-07-23 at 11 06 12 AM" src="https://github.com/user-attachments/assets/d1f91256-eb8f-4456-8d88-c0a37b1bd4c5" />

3. Click on "Deploy"

<img width="1523" height="902" alt="Screenshot 2025-07-23 at 11 09 37 AM" src="https://github.com/user-attachments/assets/9564cbdd-c5c5-4210-bf27-2b19e6efc85b" />

4. Navigate to the Deployments tab in the Asset Bundle UI (🚀 icon) and click "Run" on the job available. This will run the notebooks from this project sequentially.

<img width="1527" height="880" alt="Screenshot 2025-07-23 at 11 10 13 AM" src="https://github.com/user-attachments/assets/0f612882-7123-449b-8349-1835bc59523c" />

NB: Genie spaces need to be created via the UI

## Contributing
1. **git clone** this project locally
2. Utilize the Databricks CLI to test your changes against a Databricks workspace of your choice
3. Contribute to repositories with pull requests (PRs), ensuring that you always have a second-party review from a capable teammate

## 📄 Third-Party Package Licenses - FILL IN WITH YOUR PROJECT'S OPEN SOURCE PACKAGES + LICENSING
&copy; 2025 Databricks, Inc. All rights reserved. The source in this project is provided subject to the Databricks License [https://databricks.com/db-license-source]. All included or referenced third party libraries are subject to the licenses set forth below.

| Package | License | Copyright |
|---------|---------|-----------|
| rdkit | Cheminformatics package (C++ and Python based) | BSD 3-Clause |
| pubchempy | Interact with PubChem in Python | MIT |
| pikachu-chem | Cheminformatics package (Python-based) | MIT |
| databricks-ai-bridge | APIs to interact with Databricks AI features such as AI/BI Genie and Vector Search | Databricks |
| databricks-sdk | SDK to interact with Databricks | Apache 2.0 |
| databricks-vectorsearch | SDK to interact with Databricks | Databricks |
| streamlit | lightweight Python framework for developing web applications | Apache 2.0 |
