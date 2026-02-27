# Databricks notebook source
# MAGIC %md
# MAGIC ## OPTIONAL: to test that VS retrieves as expected
# MAGIC This is not required for the app

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch databricks-langchain rdkit mols2grid
# MAGIC %pip install -U mlflow
# MAGIC %restart_python

# COMMAND ----------

import mlflow
from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")
endpoint_name=cfg.get("retriever").get("vs_endpoint")
vs_index=cfg.get("retriever").get("vs_index")

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

client = VectorSearchClient()
index = client.get_index(index_name=vs_index)

# COMMAND ----------

from src.descriptors import get_ecfp
import pandas as pd
import numpy as np
import rdkit
from rdkit.Chem import MolFromSmiles, AllChem
import mols2grid
from IPython.display import display as idisplay

# test molecule: Furanylfentanyl
test_smiles = "O=C(C1=CC=CO1)N(C2=CC=CC=C2)C3CCN(CCC4=CC=CC=C4)CC3"
test_mol = MolFromSmiles(test_smiles)
test_embedding = get_ecfp(test_mol)
print(test_embedding.tolist())

# COMMAND ----------

results = index.similarity_search(
    query_vector=test_embedding.tolist(),
    columns=["zinc_id", "smiles", "mwt", "logp", "ecfp"],
    num_results=3,
    #filters={"molecular_weight >": 250, "molecular_weight <=": 500}
    )
results

# COMMAND ----------

columns = [i['name'] for i in results['manifest']['columns']]
columns

# COMMAND ----------

results_df = pd.DataFrame(results['result']['data_array'], columns=columns)
#results_df['mol'] = results_df["smiles"].apply(MolFromSmiles)
results_df

# COMMAND ----------

mols2grid.display([test_mol])

# COMMAND ----------

mols2grid.display(
    results_df,
    smiles_col="smiles",
    # set the fields  displayed on the grid
    tooltip=["mwt"],
    subset=["zinc_id", "score"]
)
