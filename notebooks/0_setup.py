# Databricks notebook source
# MAGIC %pip install -U mlflow databricks-sdk psycopg psycopg_pool rdkit
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# Provide SP credentials here for connecting to LakeBase
# Method 1: Get from secrets
client_id = dbutils.secrets.get(scope="aichemy", key="client_id")
client_secret = dbutils.secrets.get(scope="aichemy", key="client_secret")

# COMMAND ----------

# Method 2: Enter into widgets
dbutils.widgets.text(name="client_id", defaultValue=client_id,  label="Service Principal Client ID")
dbutils.widgets.text(name="client_secret", defaultValue=client_secret, label="Service Principal Client Secret")
client_id = dbutils.widgets.get("client_id")
client_secret = dbutils.widgets.get("client_secret")

# COMMAND ----------

from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")
cfg.to_dict()

# COMMAND ----------

from databricks.sdk import WorkspaceClient

instance_name = cfg.get("lakebase_agent").get("instance_name")
# ws_client = WorkspaceClient(
#     host=cfg.get("host"),
#     client_id=client_id,
#     client_secret=client_secret
# )
ws_client = WorkspaceClient()

# COMMAND ----------

ws_info = ws_client.current_user.me()
display(ws_info)

# COMMAND ----------

from databricks.sdk.service.database import DatabaseInstance

# Check if database instance exist
if any(db.name == instance_name for db in ws_client.database.list_database_instances()):
    print(f"Database instance {instance_name} already exists")
else:  # database instance does not exist
    instance = ws_client.database.create_database_instance(
        DatabaseInstance(name=instance_name, capacity="CU_1")
    )

# COMMAND ----------

# MAGIC %md
# MAGIC Ensure that you have:
# MAGIC 1. Granted the necessary permissions (SP can CreateDB) to the Lakebase instance
# MAGIC 2. `CREATE DATABASE <database_name>;`
# MAGIC 3. `GRANT ALL PRIVILEGES ON SCHEMA public TO "<CLIENT_ID>";`

# COMMAND ----------

del LakebaseConnect

# COMMAND ----------

from src.lakebase import LakebaseConnect
from databricks.sdk import WorkspaceClient

# Test connection to Provisioned Lakebase
dbClient = LakebaseConnect(
    user = "yen.low@databricks.com",
    password = None, # leave None to generate ephemeral token (1h)
    instance_name = cfg.get("lakebase_agent").get("instance_name"), 
    database = cfg.get("lakebase_agent").get("database"),
    wsClient = ws_client
)
dbClient.test_query()

# COMMAND ----------

# Test connection to autoscaled Lakebase
dbClient2 = LakebaseConnect(
    user = "yen.low@databricks.com",
    password = None, # leave None to generate ephemeral token (1h)
    project_id = cfg.get("lakebase").get("project_id"),
    branch_id = cfg.get("lakebase").get("branch_id"),
    endpoint_id = cfg.get("lakebase").get("endpoint_id"),
    wsClient = ws_client
)
dbClient2.test_query()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create functions as tools
# MAGIC 1. `molecule_png_url` to get the molecule image URL from PubChem based on the CID
# MAGIC 2. `get_embedding` to compute molecular fingerprint embeddings for searching ZINC vector store

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION healthcare_lifesciences.qsar.molecule_png_url(cid INTEGER)
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the molecule image url of a CID from PubChem'
# MAGIC LANGUAGE PYTHON
# MAGIC AS $$
# MAGIC url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{str(cid)}/png"
# MAGIC return url
# MAGIC $$;

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION healthcare_lifesciences.qsar.get_embedding(smiles STRING)
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the ECFP molecular fingerprint from SMILES'
# MAGIC LANGUAGE PYTHON
# MAGIC ENVIRONMENT (
# MAGIC   dependencies = '["rdkit"]',
# MAGIC   environment_version = 'None'
# MAGIC )
# MAGIC AS $$
# MAGIC from rdkit.Chem import MolFromSmiles
# MAGIC from rdkit.Chem.AllChem import GetMorganGenerator
# MAGIC fpgen = GetMorganGenerator(radius=2, fpSize=1024)
# MAGIC mol = MolFromSmiles(smiles)
# MAGIC vector = fpgen.GetFingerprintAsNumPy(mol)
# MAGIC bitstring = "".join([str(i) for i in vector])
# MAGIC return bitstring
# MAGIC $$;
