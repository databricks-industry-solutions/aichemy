# Databricks notebook source
# MAGIC %pip install rdkit ipywidgets
# MAGIC %pip install -U mlflow
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

#import mols2grid
import pandas as pd
import numpy as np
import rdkit
from rdkit.Chem import Descriptors, Draw, MolFromSmiles, AllChem, DataStructs
from rdkit.Chem.rdchem import Mol
from ipywidgets import interact, widgets
import urllib
from IPython.display import display as ipython_display
#import py3Dmol
from pyspark.sql.functions import pandas_udf, udf
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, BinaryType, ArrayType, FloatType
from typing import Dict, Optional, List, Iterator
import re
import os

# COMMAND ----------

import mlflow
from mlflow.models import ModelConfig

cfg = ModelConfig(development_config="config.yml")

catalog_name = cfg.get("catalog")
schema_name = cfg.get("schema")
volume_path = f"/Volumes/{catalog_name}/{schema_name}/data"
# Download Drugbank subset of FDA-approved drugs
data_path = "data/drugbank_approved.csv"
table_destination = f"{catalog_name}.{schema_name}.drugbank"
table_description = "Drugbank dataset as used in ADMET-AI in 10.1093/bioinformatics/btae416"

# COMMAND ----------

# MAGIC %sh
# MAGIC # # Open terminal and copy from local to Vol
# MAGIC # cp /Workspace/Repos/yen.low@databricks.com/aichemy/data/drugbank_approved.csv /Volumes/aichemy2_catalog/aichemy/data/.

# COMMAND ----------

df = spark.read.csv(f"{volume_path}/drugbank_approved.csv", header=True, inferSchema=True)
display(df)

# COMMAND ----------

df.write.mode("overwrite").option("overwriteSchema", "True").saveAsTable(
    table_destination
)

# COMMAND ----------

spark.sql(
    f"""
ALTER TABLE {table_destination} SET TBLPROPERTIES('comment'='{table_description}')
"""
)

# COMMAND ----------

df = spark.table(table_destination)
df.count()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compute ECFP

# COMMAND ----------

from src.descriptors import smiles_to_ecfp, smiles_to_desc, fpgen

smiles_to_ecfp("C1=Cc2ccccc2NN=C1", fpgen)

# COMMAND ----------

schema_string = ', '.join([f"{name} float" for name, _ in Descriptors.descList])

@pandas_udf(ArrayType(FloatType()))
def udf_smiles_to_ecfp(smiles: Iterator[pd.Series]) -> Iterator[pd.Series]:
    fpgen = AllChem.GetMorganGenerator(radius=2, fpSize=1024)
    for batch in smiles:
        results = []
        for smi in batch:
            desc_dict = smiles_to_ecfp(smi, fpgen)
            results.append(desc_dict)
        yield pd.Series(results)

@pandas_udf(schema_string)
def udf_smiles_to_desc(smiles: Iterator[pd.Series]) -> Iterator[pd.DataFrame]:
    for batch in smiles:
        results = []
        for smi in batch:
            desc_dict = smiles_to_desc(smi)
            results.append(desc_dict)
        yield pd.DataFrame(results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compute RDkit descriptors

# COMMAND ----------

df = df.repartition(32)

df_desc = (df
    .withColumn("ecfp", udf_smiles_to_ecfp("smiles"))
    .withColumn("descriptors", udf_smiles_to_desc("smiles"))
)
display(df_desc.limit(10))

# COMMAND ----------

df = df.repartition(32)

df_desc = (df
    .withColumn("ecfp", udf_smiles_to_ecfp("smiles"))
    .withColumn("descriptors", udf_smiles_to_desc("smiles"))
)
display(df_desc.limit(10))

# COMMAND ----------

from src.descriptors import get_selected_descriptors

selected_desc = get_selected_descriptors()
selected_desc

# COMMAND ----------

selected_columns = df.columns + ["descriptors." + i for i in selected_desc] + ['ecfp']
selected_columns

# COMMAND ----------

display(df_desc.select(selected_columns).limit(5))

# COMMAND ----------

df_desc.select(selected_columns).write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{table_destination}_full")
