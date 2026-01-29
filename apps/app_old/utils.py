import os
import yaml
import logging
import rdkit
from rdkit.Chem import MolFromSmiles, AllChem
import pubchempy as pcp
import numpy as np
import pandas as pd
from typing import List, Union, Tuple, Optional
import re
import requests
from pikachu.general import draw_smiles, read_smiles, svg_string_from_structure
import pprint
import json
from urllib.parse import quote
from dataclasses import dataclass
from databricks.sdk import WorkspaceClient

# Set up logging
logging.basicConfig(level=logging.ERROR)


@dataclass
class BioassayInfo:
    """Dataclass to hold bioassay information"""

    active: Optional[bool] = None
    aid: Optional[int] = None
    name: Optional[str] = None
    target: Optional[str] = None
    species: Optional[str] = None


PROPERTIES = [
    #    "cid",
    "iupac_name",
    "isomeric_smiles",
    "inchi",
    "molecular_formula",
    "molecular_weight",
    "xlogp",
    "tpsa",
    "heavy_atom_count",
    "h_bond_acceptor_count",
    "h_bond_donor_count",
    "rotatable_bond_count",
    "synonyms",
]


# https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth?language=Streamlit#retrieve-user-authorization-credentials
# def get_user_token_from_streamlit():
#     from streamlit.web.server.websocket_headers import _get_websocket_headers
#     headers = _get_websocket_headers()
#     return headers.get("X-Forwarded-Access-Token")


def get_databricks_client():
    return WorkspaceClient(
        host=os.getenv("DATABRICKS_HOST"),
        # if user PAT
        # token=os.getenv("DATABRICKS_TOKEN"),
        # if OBO auth
        client_id=os.getenv("DATABRICKS_CLIENT_ID"),
        client_secret=os.getenv("DATABRICKS_CLIENT_SECRET"),
    )


# Load configuration from YAML file
def load_config(config_path: str = "config.yaml"):
    """Load configuration from config.yaml file"""
    try:
        with open(config_path, "r") as file:
            config = yaml.safe_load(file)
        return config
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Configuration file not found: {config_path}. {e}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"{e}")
    except Exception as e:
        raise Exception(f"Error loading configuration: {e}")


def genie_name_to_config(genie_name: str, genie_config: dict) -> str:
    key = [k for k, d in genie_config.items() if d["name"] == genie_name][0]
    return genie_config[key]


def get_ecfp(
    mol: rdkit.Chem.rdchem.Mol, radius: int = 3, fpSize: int = 1024
) -> np.array:
    fpgen = AllChem.GetMorganGenerator(radius=radius, fpSize=fpSize)
    return fpgen.GetFingerprintAsNumPy(mol)


def multi_inputs_to_list(inputs: str) -> List[str]:
    _inputs = inputs.split(",")
    input_list = [m.strip() for m in _inputs]
    return input_list


def cids_to_pandas(cids: List[int]) -> pd.DataFrame:
    df = pcp.get_compounds(cids, as_dataframe=True)
    return format_pandas(df)


def input_to_pcpCompound(input: str) -> Union[pcp.Compound, str]:
    if input.isdigit():
        # if all integer => CID
        cid = int(input)
        try:
            # look up in pubchem
            cpd = pcp.Compound.from_cid(cid)
            # smiles = cpd.isomeric_smiles
            return cpd
        except Exception as e:
            raise Exception(f"Failed to look up CID {cid} in PubChem: {e}")
    else:
        try:
            # if can be converted to a Mol => SMILES
            mol = MolFromSmiles(input, sanitize=False)
            cpd = pcp.get_compounds(input, "smiles")
            print(cpd)
            if len(cpd) == 0:
                logging.warning(
                    f"{input} not found by SMILES in PubChem. This could be a new compound. Returning SMILES instead of a PubChem compound."
                )
                return input
            else:
                return cpd[0]
            return cpd
        except:
            # Not CID or SMILES => name
            # then lookup SMILES by name
            try:
                cpd = pcp.get_compounds(input, "name")
                if len(cpd) == 0:
                    raise Exception(
                        f"{input} not found by name in PubChem. Please try another synonym, CID or SMILES."
                    )
                else:
                    return cpd[0]
            except Exception as e:
                raise Exception(
                    f"Failed to look up SMILES/name {input} in PubChem: {e}"
                )


def get_pubchem_properties(cpd: pcp.Compound) -> Union[pd.DataFrame, str]:
    active_cids = None
    try:
        # if return dictionary
        # prop = {key: getattr(cpd, key) for key in properties}
        # if return pandas
        prop = pcp.compounds_to_frame(cpd, properties=PROPERTIES)
        key_aid = get_bioassay_info(cpd).aid
        if key_aid:
            assay_url = f"https://pubchem.ncbi.nlm.nih.gov/bioassay/{key_aid}"
            active_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/aid/{key_aid}/cids/TXT?cids_type=active"
            active_cids = requests.get(active_url).text.splitlines()
            prop["bioassay"] = assay_url
            prop["has_similar_bioactivity"] = None
        prop = prop.reset_index().T
        prop.columns = ["Value"]
        if active_cids:
            prop.at["has_similar_bioactivity", "Value"] = active_cids
        return prop
    except Exception as e:
        error_msg = f"Error getting PubChem properties. {e}"
        logging.exception(error_msg)
        return error_msg


def get_pubchem_url(cid: int) -> str:
    return f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"


def get_pubchem_img_url(cid: int) -> str:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/png"
    return url


def get_pubchem_description(cid: int) -> str:
    """
    Get description from PubChem API for a given CID
    """
    description_url = (
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/description/JSON"
    )

    try:
        response = requests.get(description_url)
        response.raise_for_status()  # Raise an exception for bad status codes
    except requests.RequestException as e:
        error_msg = f"Error fetching description from PubChem: {e}"
        logging.error(error_msg)
        return error_msg

    try:
        data = response.json()
        if "InformationList" in data and "Information" in data["InformationList"]:
            info = data["InformationList"]["Information"]
            description = [d.get("Description") for d in info if d.get("Description")]
            description_source = [
                d.get("DescriptionURL") for d in info if d.get("DescriptionURL")
            ]
            if len(description) > 0 and len(description_source) > 0:
                return f"{description[0]}\nSource:{description_source[0]}"
            elif len(description) > 0:
                return description[0]
            else:
                return "No description available"
        else:
            return "No description available"

    except Exception as e:
        error_msg = f"""Error processing PubChem description. Possibly missing description in JSON: {e}
        {pprint.pprint(data)}
        """
        logging.error(error_msg)
        return error_msg


def get_pubchem_info(cpd: Union[pcp.Compound, str]) -> Tuple[str, str, str, str]:
    if isinstance(cpd, pcp.Compound):
        # cpd.isomeric_smiles and cpd.canonical_smiles suddenly returns None
        # smile = cpd.isomeric_smiles
        smile = [
            i["value"]["sval"]
            for i in cpd.record["props"]
            if i["urn"].get("name") == "Absolute" and i["urn"]["label"] == "SMILES"
        ][0]
        name = cpd.synonyms[0]
        url = get_pubchem_url(cpd.cid)
        description = get_pubchem_description(cpd.cid)
    else:
        smile = cpd
        name = cpd
        url = None
        description = None
    return smile, name, url, description


def universal_search(
    smiles: str,
    searchtype: str = "exact",
    max_records: int = 100,
    max_seconds: int = 10,
) -> List[pcp.Compound]:
    if searchtype not in ["exact", "similarity", "substructure", "superstructure"]:
        raise ValueError(
            f"Invalid searchtype: {searchtype}. Must be one of: exact, similarity, substructure, superstructure"
        )
    if searchtype == "exact":
        try:
            cpd = input_to_pcpCompound(smiles)
            return cpd
        except Exception as e:
            raise Exception(
                f"Error looking up {smiles} in PubChem: {e}. Try using SMILES or CID instead."
            )
    # elif searchtype == "similarity":
    #     # TODO: implement vector search
    #     return input_to_pcpCompound(smiles)
    else:
        try:
            cpds = pcp.get_compounds(
                smiles,
                namespace="smiles",
                searchtype=searchtype,
                MaxRecords=max_records,
                MaxSeconds=max_seconds,
                as_dataframe=True,
            )
            if not cpds.empty:
                return format_pandas(cpds)
            else:
                raise Exception(
                    f"No results found for {searchtype} search of {smiles} in PubChem. Please enter a valid SMILES or raise max_seconds longer than {max_seconds}."
                )
        except Exception as e:
            raise Exception(
                f"For {searchtype} search of {smiles} in PubChem, please enter a valid SMILES, not name or CID. {e}. "
            )


def format_pandas(cpds: pd.DataFrame) -> pd.DataFrame:
    show_first = ["url", "structure", "molecular_weight"]
    selected_columns = [i for i in cpds.columns if i in PROPERTIES]
    df = cpds[selected_columns].reset_index()
    df["structure"] = df["cid"].apply(get_pubchem_img_url)
    df["url"] = df["cid"].apply(get_pubchem_url)
    df.set_index("cid", inplace=True)
    # reorder columns
    return df[show_first + [i for i in selected_columns if i not in show_first]]


def smiles2vector(smiles: str) -> np.array:
    try:
        mol = MolFromSmiles(smiles)
    except Exception as e:
        raise Exception(f"{e}. Not a valid SMILES string.")

    try:
        fp_vec = get_ecfp(mol)
        return fp_vec.tolist()
    except Exception as e:
        raise Exception(f"Error generating embeddings: {e}")


def display_mol(smiles: str) -> str:
    import mols2grid

    mol = MolFromSmiles(smiles)
    im = mols2grid.display([mol])
    html = im.data
    return html


def smiles2svg(smiles: str) -> str:
    try:
        struc = read_smiles(smiles)
        svg_content = svg_string_from_structure(struc)
    except Exception as e:
        error_msg = f"Error generating SVG. {e}"
        logging.exception(f"Error generating SVG. {e}")
        return error_msg

    # Use regex to replace width and height attributes with variable numbers
    svg_content = re.sub(r'width="\d+\.*\d*pt" height="\d+\.*\d*pt"', "", svg_content)
    return svg_content


def mol2svg(smiles: List[str], labels: List[str] = None) -> str:
    from rdkit.Chem import Draw

    im = Draw.MolsToGridImage(
        [MolFromSmiles(mol) for mol in smiles],
        molsPerRow=5,
        # TODO: 'list' object is not callable
        legends=labels,
        subImgSize=(200, 200),
        useSVG=True,
        returnPNG=False,
    )
    # remove xml tag
    return re.sub(r"^<\?.+\?>\s*", "", im)


def svg_to_data_url(svg_content: str) -> str:
    try:
        # URL encode special characters in SVG content
        encoded_svg = quote(svg_content, safe="")
        # Create data URL with UTF-8 encoding
        data_url = f"data:image/svg+xml;utf8,{encoded_svg}"
        return data_url
    except Exception as e:
        error_msg = f"Error converting SVG to data URL: {e}"
        logging.exception(error_msg)
        return error_msg


def get_bioassay_info(cpd: pcp.Compound) -> BioassayInfo:
    bioassays = cpd.aids
    # select bioassay with 'Homo sapiens'

    for aid in bioassays:
        try:
            bioassay = pcp.Assay.from_aid(aid)
            # Convert bioassay record to JSON string for case-insensitive search
            bioassay_json = json.dumps(bioassay.record)

            # Search for 'homo sapiens' case insensitive
            if re.search(r"homo sapiens", bioassay_json, re.IGNORECASE):
                active = bioassay.results[0].get("ac")
                name = bioassay.name
                target = bioassay.target[0].get("name") if bioassay.target else None
                species = (
                    bioassay.record["assay"]["descr"]
                    .get("xref", [{}])[0]
                    .get("comment")
                    if bioassay.record.get("assay", {}).get("descr", {}).get("xref")
                    else None
                )
                return BioassayInfo(
                    active=active, aid=aid, name=name, target=target, species=species
                )
        except Exception as e:
            logging.warning(f"Error processing bioassay {aid}: {e}")
            continue
    return BioassayInfo()


# https://www.ncbi.nlm.nih.gov/pccompound/?term=150%3A200%5Bmw%5D
# https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/aid/1911918/cids/TXT?cids_type=active
# bioassay  = pcp.Assay.from_aid('1911918')
# bioassay.name
# bioassay.target[0]['name']
# if bioassay.record['assay']['descr']['xref'][0]['comment']=='Homo sapiens'
