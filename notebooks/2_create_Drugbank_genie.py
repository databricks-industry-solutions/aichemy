# Databricks notebook source
# MAGIC %pip install -U databricks-sdk mlflow requests
# MAGIC %restart_python

# COMMAND ----------

import mlflow
from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="../apps/react-app/config.yml")

catalog_name = cfg.get("catalog")
schema_name = cfg.get("schema")
genie_cfg = cfg.get("genie").get("drugbank",{})
existing_space_id = genie_cfg.get("space_id")
drugbank_table = genie_cfg.get("table")

print(f"Table: {drugbank_table}")
print(f"Existing space ID: {existing_space_id}")

# COMMAND ----------

import json
import random
import datetime

def gen_hex_id():
    """Generate a 32-char lowercase hex ID (time-ordered UUID without hyphens)."""
    t = int((datetime.datetime.now() - datetime.datetime(1582, 10, 15)).total_seconds() * 1e7)
    hi = (t & 0xFFFFFFFFFFFF0000) | (1 << 12) | ((t & 0xFFFF) >> 4)
    lo = random.getrandbits(62) | 0x8000000000000000
    return f"{hi:016x}{lo:016x}"

serialized_space = json.dumps({
    "version": 2,
    "config": {
        "sample_questions": sorted([
            {"id": gen_hex_id(), "question": ["What are the top 10 drugs by molecular weight?"]},
            {"id": gen_hex_id(), "question": ["List all drugs that target the ACE2 receptor"]},
            {"id": gen_hex_id(), "question": ["How many drugs are in the kinase inhibitor category?"]},
            {"id": gen_hex_id(), "question": ["Show drugs with logP greater than 5"]},
            {"id": gen_hex_id(), "question": ["Which drugs have the highest number of hydrogen bond donors?"]},
        ], key=lambda x: x["id"])
    },
    "data_sources": {
        "tables": [
            {
                "identifier": drugbank_table,
                "description": [
                    "FDA-approved drugs from Drugbank including drug names, SMILES structures, "
                    "targets, categories, molecular descriptors, and ADMET properties."
                ],
            }
        ]
    },
    "instructions": {
        "text_instructions": [
            {
                "id": gen_hex_id(),
                "content": [
                    "This table contains FDA-approved drugs from the Drugbank database. ",
                    "When asked about molecular properties, use columns like mwt (molecular weight), ",
                    "logp, hbd (hydrogen bond donors), hba (hydrogen bond acceptors). ",
                    "SMILES column contains the molecular structure as a SMILES string."
                ]
            }
        ]
    }
})
serialized_space

# COMMAND ----------

from databricks.sdk import WorkspaceClient

ws = WorkspaceClient()
host = ws.config.host.rstrip("/")

# Pick a running warehouse
warehouse_id = None
for wh in ws.warehouses.list():
    if wh.state and wh.state.value == "RUNNING":
        warehouse_id = wh.id
        break

if warehouse_id is None:
    warehouses = list(ws.warehouses.list())
    if warehouses:
        warehouse_id = warehouses[0].id
    else:
        raise RuntimeError("No SQL warehouses found in the workspace")

print(f"Using warehouse: {warehouse_id}")

# COMMAND ----------

headers = dict(ws.config.authenticate())
headers

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or update the Genie Space via REST API

# COMMAND ----------

import requests

space_title = "Drugbank – FDA-approved drugs"
description = (
    "Ask natural-language questions about FDA-approved drugs from the "
    "Drugbank database. Includes drug names, SMILES structures, targets, "
    "categories, molecular descriptors, and ADMET properties."
)
username = ws.current_user.me().user_name

if existing_space_id:
    print(f"Updating existing Genie Space: {existing_space_id}")
    resp = requests.put(
        f"{host}/api/2.0/genie/spaces/{existing_space_id}",
        headers=headers,
        json={
            "title": space_title,
            "description": description,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
        },
    )
else:
    print("Creating new Genie Space…")
    resp = requests.post(
        f"{host}/api/2.0/genie/spaces",
        headers=headers,
        json={
            "title": space_title,
            "description": description,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
            "parent_path": f"/Workspace/Users/{username}",
        },
    )

resp.raise_for_status()
result = resp.json()
space_id = result.get("space_id")
print(f"Genie Space ID: {space_id}")
print(f"URL: {host}/genie/rooms/{space_id}")
print(json.dumps(result, indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Update config.yml
# MAGIC If this is a new space, update `apps/react-app/config.yml` with the new `space_id`:
# MAGIC ```yaml
# MAGIC genie:
# MAGIC   drugbank:
# MAGIC     space_id: <new_space_id>
# MAGIC     table: aichemy2_catalog.aichemy.drugbank_full
# MAGIC ```
