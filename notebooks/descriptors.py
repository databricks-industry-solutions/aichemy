import pandas as pd
import numpy as np
import rdkit
from rdkit.Chem import Descriptors, MolFromSmiles, AllChem, DataStructs
from rdkit.Chem.rdchem import Mol
from pyspark.sql.functions import pandas_udf
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, ArrayType, FloatType
from typing import Dict, Iterator, List, Optional
import re


fpgen = AllChem.GetMorganGenerator(radius=2, fpSize=1024)

# # https://datagrok.ai/help/datagrok/solutions/domains/chem/descriptors
def get_selected_descriptors() -> List[str]:
    from rdkit.Chem import Descriptors

    desc = [desc for desc, _ in Descriptors.descList]
    unselect_regex = re.compile(r"^Max|^Min|^MolWt$|^FpDensityMorgan|^BCUT2D|Ipc$|AvgIpc|BalabanJ|BertzCT|^Chi|^Kappa|LabuteASA|^PEOE_|^SMR_|^SlogP_|EState|VSA_EState|MolLogP|MolMR|HallKier|qed|TPSA|NumHAcceptors|NumHDonors")
    selected_desc = [d for d in desc if not unselect_regex.match(d)]
    return selected_desc


# For a single molecule
def get_ecfp(mol: rdkit.Chem.rdchem.Mol, radius: int=2, fpSize: int=1024) -> np.array:
    fpgen = AllChem.GetMorganGenerator(radius=radius, fpSize=fpSize)
    return fpgen.GetFingerprintAsNumPy(mol)

# For a single smiles
def smiles_to_ecfp(smiles: str, fpgen: rdkit.Chem.rdFingerprintGenerator.FingerprintGenerator64) -> np.array:
    from rdkit.Chem import MolFromSmiles
    mol = MolFromSmiles(smiles)
    return fpgen.GetFingerprintAsNumPy(mol)

def smiles_to_desc(smiles: str, desc: Optional[List[str]] = None):
    from rdkit.Chem import Descriptors, MolFromSmiles
    mol = MolFromSmiles(smiles)
    # desc option does not work
    if desc:
        calculator = Descriptors.Properties(desc)
        return calculator.CalcDescriptors(mol)
    else: #all descriptors
        return Descriptors.CalcMolDescriptors(mol)
