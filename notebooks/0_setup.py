# Databricks notebook source
# MAGIC %pip install -U mlflow databricks-sdk psycopg psycopg_pool rdkit
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# MAGIC %md
# MAGIC ### Provide SP credentials here for connecting to LakeBase

# COMMAND ----------

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

cfg = ModelConfig(development_config="../apps/react-app/config.yml")
cfg.to_dict()

# COMMAND ----------

from databricks.sdk import WorkspaceClient

ws_client = WorkspaceClient(
    host=cfg.get("host"), client_id=client_id, client_secret=client_secret
)
ws_info = ws_client.current_user.me()
display(ws_info)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create an [Autoscaling Lakebase Project](https://docs.databricks.com/aws/en/oltp/projects/get-started)
# MAGIC Ensure that you have:
# MAGIC 1. Granted the necessary permissions (SP can CreateDB) to the Lakebase project
# MAGIC 2. `CREATE DATABASE <database_name>;`
# MAGIC 3. `GRANT ALL PRIVILEGES ON SCHEMA public TO "<CLIENT_ID>";`

# COMMAND ----------

from lakebase import LakebaseConnect
from databricks.sdk import WorkspaceClient

# Test connection to autoscaled Lakebase
dbClient = LakebaseConnect(
    user = client_id,
    password = None, # leave None to generate ephemeral token (1h)
    project_id = cfg.get("lakebase").get("project_id"),
    branch_id = cfg.get("lakebase").get("branch_id"),
    endpoint_id = cfg.get("lakebase").get("endpoint_id"),
    wsClient = ws_client
)
dbClient.test_query()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create functions as tools
# MAGIC 1. `molecule_png_url` to get the molecule image URL from PubChem based on the CID
# MAGIC 2. `get_embedding` to compute molecular fingerprint embeddings for searching ZINC vector store
# MAGIC 2. `predict_admet` to predict ADMET properties using an external multi-task ChemProp MPNN model.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION healthcare_life_sciences.qsar.molecule_png_url(cid INTEGER)
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the molecule image url of a CID from PubChem'
# MAGIC LANGUAGE PYTHON
# MAGIC AS $$
# MAGIC url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{str(cid)}/png"
# MAGIC return url
# MAGIC $$;

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION healthcare_life_sciences.qsar.get_embedding(smiles STRING COMMENT 'A valid SMILES molecular structure string, e.g. CCO for ethanol or c1ccccc1 for benzene. Must be a syntactically valid SMILES that RDKit can parse.')
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Returns the ECFP4 molecular fingerprint as a 1024-char bitstring from a SMILES string. Returns an error message if the SMILES is invalid.'
# MAGIC LANGUAGE PYTHON
# MAGIC ENVIRONMENT (
# MAGIC   dependencies = '["rdkit"]',
# MAGIC   environment_version = 'None'
# MAGIC )
# MAGIC AS $$
# MAGIC if not smiles or not smiles.strip():
# MAGIC     return "ERROR: smiles parameter is empty or null"
# MAGIC from rdkit.Chem import MolFromSmiles
# MAGIC from rdkit.Chem.AllChem import GetMorganGenerator
# MAGIC mol = MolFromSmiles(smiles.strip())
# MAGIC if mol is None:
# MAGIC     return f"ERROR: invalid SMILES string '{smiles}' - RDKit could not parse it"
# MAGIC fpgen = GetMorganGenerator(radius=2, fpSize=1024)
# MAGIC vector = fpgen.GetFingerprintAsNumPy(mol)
# MAGIC bitstring = "".join([str(i) for i in vector])
# MAGIC return bitstring
# MAGIC $$;

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION healthcare_life_sciences.qsar.predict_admet(
# MAGIC   smiles STRING COMMENT 'A single SMILES string representing the molecule'
# MAGIC )
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Predicts ADMET properties for a molecule (given as SMILES) by calling the public ADMET-AI web app. Returns a JSON object mapping each ADMET property name to its predicted value.'
# MAGIC LANGUAGE PYTHON
# MAGIC AS $$
# MAGIC import csv
# MAGIC import http.cookiejar
# MAGIC import io
# MAGIC import json
# MAGIC import urllib.parse
# MAGIC import urllib.request
# MAGIC
# MAGIC BASE_URL = "https://admet.ai.greenstonebio.com"
# MAGIC TIMEOUT = 120
# MAGIC
# MAGIC if not smiles or not smiles.strip():
# MAGIC     return json.dumps({"error": "Empty SMILES string"})
# MAGIC
# MAGIC cookies = http.cookiejar.CookieJar()
# MAGIC opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
# MAGIC opener.addheaders = [("User-Agent", "databricks-uc-function/admet-ai")]
# MAGIC
# MAGIC # 1) Prime a session so the server issues us a user_id cookie.
# MAGIC try:
# MAGIC     opener.open(BASE_URL + "/", timeout=TIMEOUT).read()
# MAGIC except Exception as e:
# MAGIC     return json.dumps({"error": f"Failed to reach ADMET-AI: {e}"})
# MAGIC
# MAGIC # 2) Submit the SMILES via the same form the web UI uses.
# MAGIC form = urllib.parse.urlencode({
# MAGIC     "text-smiles": smiles.strip(),
# MAGIC     "draw-smiles": "",
# MAGIC     "smiles-column": "smiles",
# MAGIC }).encode("utf-8")
# MAGIC req = urllib.request.Request(
# MAGIC     BASE_URL + "/",
# MAGIC     data=form,
# MAGIC     headers={"Content-Type": "application/x-www-form-urlencoded"},
# MAGIC )
# MAGIC try:
# MAGIC     opener.open(req, timeout=TIMEOUT).read()
# MAGIC except Exception as e:
# MAGIC     return json.dumps({"error": f"Prediction request failed: {e}"})
# MAGIC
# MAGIC # 3) Fetch the per-session CSV of predictions.
# MAGIC try:
# MAGIC     resp = opener.open(BASE_URL + "/download_predictions", timeout=TIMEOUT)
# MAGIC     body = resp.read().decode("utf-8")
# MAGIC except Exception as e:
# MAGIC     return json.dumps({"error": f"Download failed: {e}"})
# MAGIC
# MAGIC rows = list(csv.DictReader(io.StringIO(body)))
# MAGIC if not rows:
# MAGIC     return json.dumps({"error": "No predictions returned (invalid SMILES?)"})
# MAGIC
# MAGIC row = rows[0]
# MAGIC out = {}
# MAGIC for k, v in row.items():
# MAGIC     if k == "smiles":
# MAGIC         continue
# MAGIC     try:
# MAGIC         out[k] = float(v)
# MAGIC     except (TypeError, ValueError):
# MAGIC         out[k] = v
# MAGIC return json.dumps({"smiles": row.get("smiles", smiles.strip()), "properties": out})
# MAGIC $$;
