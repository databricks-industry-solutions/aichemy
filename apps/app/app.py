import re
import logging
from databricks.sdk import WorkspaceClient
import pandas as pd
import numpy as np
from typing import Union

import sys
import distro
import pubchempy as pcp

import streamlit as st
from streamlit.components.v1 import html
from utils import *
from genie import GenieWrapper, GenieResponse

logging.basicConfig(level=logging.ERROR)

print(sys.version)  # 3.11
print(distro.info())  # Ubuntu 22.04 jammy

# Get current working directory
# sys.path.append(os.getcwd() + "/streamlit")
print(f"Current Working Directory: {os.getcwd()}")

# Load configuration
config = load_config("config.yaml")

# Configuration variables from YAML
if config:
    try:
        vs_config = config["vector_search"]
        genie_config = config["genie"]
    except KeyError as e:
        st.error(f"Missing configuration section: {e}")

# Initialize variables
filters_str = None
active_cids = None
active_pandas = None
vs_output = None
first_smile = None
cpds = None
min_similarity = 0.0

# try:
#     # no apt, dpkg, conda, cmake
#     # subprocess.run(["tar", "xvf", "data.tar"], check=True)
#     # result = subprocess.run(["dpkg -i "], shell=True, check=True)
#     print(result.stdout)
#     subprocess.run('ls -al "$LD_LIBRARY_PATH/x86_64-linux-gnu"', check=True, shell=True)
# except subprocess.CalledProcessError as e:
#     print(f"Error installing libxrender1: {e}")

# Initialize Databricks SDK client
workspace_client = get_databricks_client()

# Initialize session state for conversation management
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "genie_search_clicked" not in st.session_state:
    st.session_state.genie_search_clicked = False
if "previous_geniespace" not in st.session_state:
    st.session_state.previous_geniespace = None


def create_search_box():
    """Create a search box that can be refreshed"""
    search_container = st.empty()
    search_query = search_container.text_input(
        label="genie_input",
        key="genie_input",
        placeholder="Ask me about your drugs library",
        label_visibility="collapsed",
    )
    return search_query


def display_pubchem_pandas(cpds: pd.DataFrame):
    try:
        st.dataframe(
            cpds,
            hide_index=True,
            row_height=100,
            use_container_width=True,
            column_config={
                "structure": st.column_config.ImageColumn("Structure", width="medium"),
                "url": st.column_config.LinkColumn(
                    "CID",
                    validate=r"^https://pubchem.ncbi.nlm.nih.gov/compound/\d+$",
                    pinned=True,
                    max_chars=10,
                    display_text=r"https://pubchem.ncbi.nlm.nih.gov/compound/(\d+)",
                ),
            },
        )
    except Exception as e:
        st.error(f"Error displaying dataframe from PubChem: {e}")


def display_genie_result(result: GenieResponse):
    ans_col, sql_col = st.columns([4, 1])
    try:
        with ans_col:
            st.write(result.description)
        with sql_col:
            with st.popover(
                label=r"$\textsf{\scriptsize Show SQL}$",
                help="Show SQL query generated by Genie",
                # icon=":material/code:",
                use_container_width=True,
            ):
                st.markdown(result.query)
        st.markdown(result.result)
    except Exception as e:
        st.error(f"Error displaying Genie result: {e}")


def handle_genie_search(genie_config: dict):
    """Handle genie search functionality"""
    if st.session_state.genie_search_clicked and genie_input:
        try:
            # Show loading indicator
            with st.spinner(f"🔍 Querying {genie_config['name']}..."):
                # Initialize genie instance if not exists
                genie = GenieWrapper(genie_config["space_id"])

                # If no conversation exists, start a new one
                if st.session_state.conversation_id is None:
                    genie_response = genie.ask_first_question(genie_input)
                    result = genie.poll_result(genie_response)
                    if isinstance(result, GenieResponse):
                        st.session_state.conversation_id = genie.get_conversation_id(
                            genie_response
                        )
                    display_genie_result(result)
                    # reset the click flag
                    st.session_state.genie_search_clicked = False
                else:
                    # Ask follow-up question in existing conversation
                    followup_response = genie.ask_followup_question(
                        genie_input, st.session_state.conversation_id
                    )
                    followup_result = genie.poll_result(followup_response)
                    display_genie_result(followup_result)
                    # reset the click flag
                    st.session_state.genie_search_clicked = False

        except Exception as e:
            st.error(f"❌ Genie error: {e}")

        # Reset the click flag
        st.session_state.genie_search_clicked = False


def run_vector_search(
    smiles: str,
    vs_config: dict,
    score_threshold: float = 0.0,
    num_results: int = 3,
    filters_json: str = None,
) -> Union[pd.DataFrame, str]:

    index_name = vs_config.get("index")
    col_display = vs_config.get("col_display")
    col_simscore = vs_config.get("col_simscore")

    prompt_vector = smiles2vector(smiles)
    if prompt_vector is None:
        return "Failed to generate embeddings for the prompt."

    try:
        query_result = workspace_client.vector_search_indexes.query_index(
            index_name=index_name,
            columns=col_display,
            query_vector=prompt_vector,
            #            query_type="HYBRID",
            num_results=num_results,
            score_threshold=score_threshold,
            filters_json=filters_json,
        )
        return pd.DataFrame(
            query_result.result.data_array, columns=col_display + col_simscore
        )
    except Exception as e:
        error_msg = f"Error finding {num_results} similars of {smiles} within {score_threshold} similarity and with filters {filters_json}. {e}"
        logging.error(error_msg)
        return error_msg


st.set_page_config(page_title="ChemSearch", layout="wide")
st.logo("logo.svg", size="large", link=None)

# Row 1: SMILES input and similarity slider
col1, col2 = st.columns([1, 1], border=True)


with col1:
    title_col, geniespace_col, blank_col = st.columns([1, 2, 2])
    with title_col:
        st.markdown("##### Ask about")
    with geniespace_col:  # Add some spacing to align with input
        geniespace = st.selectbox(
            label="",
            options=[genie_config["drugbank"]["name"], genie_config["zinc"]["name"]],
            label_visibility="collapsed",
            help="Select database to chat with",
            key="geniespace_selectbox",
        )

        # Check if geniespace changed
        geniespace_changed = (
            st.session_state.previous_geniespace is not None
            and st.session_state.previous_geniespace != geniespace
        )

        # Update previous geniespace
        st.session_state.previous_geniespace = geniespace

    resetbutton_col, genie_col, geniebutton_col = st.columns([1, 8, 1])
    with resetbutton_col:
        reset_button = st.button(
            label="",
            icon=":material/delete_history:",
            help="Start a new chat",
            use_container_width=True,
            key="reset_button",
        )
        if reset_button or geniespace_changed:
            st.session_state.conversation_id = None
            st.rerun()

    with genie_col:
        genie_input = create_search_box()

    with geniebutton_col:
        geniesearch_button = st.button(
            label="", type="primary", icon=":material/search:", key="geniesearch_button"
        )
        if geniesearch_button:
            st.session_state.genie_search_clicked = True

    st.text("Examples: What is ozempic and its molecular weight?\nList drugs with an azo group and their indications.")

    # Handle genie search
    genie_config_selected = genie_name_to_config(geniespace, genie_config)
    handle_genie_search(genie_config_selected)

with col2:
    st.markdown("##### Search PubChem")
    (
        input_col,
        button_col,
        sketch_col,
        searchtype_col,
    ) = st.columns([3, 1, 3, 3])

    with input_col:
        query_input = st.text_input(
            label="input",
            placeholder="Enter SMILES, name or CID",
            label_visibility="collapsed",
        )
    with sketch_col:
        sketch_button = st.button(
            label="Sketch to SMILES",
            icon=":material/edit:",
            use_container_width=True,
        )
        if sketch_button:
            html(
                '<script>window.open("https://pubchem.ncbi.nlm.nih.gov//edit3/index.html", "_blank", "height=580,width=1150");</script>'
            )
    with button_col:  # Add some spacing to align with input
        search_button = st.button(
            label="", type="primary", icon=":material/search:", key="search_button"
        )
    with searchtype_col:  # Add some spacing to align with input
        searchtype = st.selectbox(
            label="",
            placeholder="Search type",
            options=["exact", "similarity", "substructure", "superstructure"],
            label_visibility="collapsed",
            help="[Learn about search types](https://pubchem.ncbi.nlm.nih.gov/search/help_search.html#SbSp)",
        )
        top_k = st.number_input(
            "Number of hits",
            min_value=1,
            max_value=None,
            value=3,
            step=1,
            help="Show this number of most similar molecules",
        )
        # min_similarity = st.number_input(
        #     "Minimum similarity",
        #     min_value=0.0,
        #     max_value=1.0,
        #     value=0.03,
        #     step=0.01,
        #     help="Show molecules with similarity score above this threshold",
        # )
        # mw_range = st.slider(
        #     "Molecular weight",
        #     min_value=0,
        #     max_value=5000,
        #     value=(200, 1000),
        #     step=10,
        #     help="Show compounds with molecular weight within this range",
        # )
        # mw_low, mw_upp = mw_range
        # filters_str = f"""{{"mwt >": {str(mw_low)},
        #             "mwt <=": {str(mw_upp)}}}"""

    # Pubchem search
    if search_button and query_input:
        with st.spinner("🔍 Searching ..."):
            input_list = multi_inputs_to_list(query_input)
            first_input = input_list[0]
            if len(input_list) > 1:
                st.info("Multiple inputs detected. Only the first one will be used.")

            try:
                # It looks like the code `cpds` is not a valid Python code snippet. It seems to be a
                # placeholder or a typo.
                cpds = universal_search(
                    first_input, searchtype=searchtype, max_records=top_k
                )
                if isinstance(cpds, pcp.Compound):
                    first_smile, name, url, description = get_pubchem_info(cpds)
                    pubchem_properties = get_pubchem_properties(cpds)
                    if isinstance(pubchem_properties, pd.DataFrame):
                        active_cids = pubchem_properties.loc[
                            "has_similar_bioactivity", "Value"
                        ]
                        if len(active_cids) > 0:
                            active_pandas = cids_to_pandas(active_cids)
                elif isinstance(cpds, pd.DataFrame):
                    first_smile = first_input
                    name, url, description, pubchem_properties = None, None, None, None
                    pass

            except Exception as e:
                st.error(
                    f"Error looking up {first_input} in PubChem. Try using SMILES or CID instead. {e}"
                )

            # Similarity search in ZINC
            if first_smile:
                vs_output = run_vector_search(
                    first_smile,
                    vs_config["zinc"],
                    score_threshold=min_similarity,
                    num_results=top_k,
                    filters_json=filters_str,
                )

                img = smiles2svg(first_smile)
                # If using mol2grid
                # Display seed molecule
                # html_output = display_mol(query_input)
                # st.components.v1.html(html_output, height=10000)

                # If using MolsToGridImage
                # Put smile and name in a list
                # smiles_list = [first_smile]
                # name_list = [name]
                # img = mol2svg(smiles_list, name_list)

                # Create two columns for image and properties
                props_col, img_col = st.columns([7, 3])

                with props_col:
                    if isinstance(pubchem_properties, pd.DataFrame):
                        st.dataframe(
                            pubchem_properties,
                            use_container_width=True,
                            height=350,
                            # TODO: does not work for a row in a pd series-like df
                            column_config={
                                "bioassay": st.column_config.LinkColumn(
                                    validate=r"^https://pubchem.ncbi.nlm.nih.gov/bioassay/\d+$",
                                    max_chars=10,
                                    display_text=r"https://pubchem.ncbi.nlm.nih.gov/bioassay/(\d+)",
                                ),
                            },
                        )

                with img_col:
                    if img.startswith("<"):
                        st.image(img, width=200, use_container_width=False)
                        if name:
                            st.markdown(
                                f"""**{name}**<br>
                                [PubChem URL]({url})""",
                                unsafe_allow_html=True,
                                help=description,
                            )
                    else:
                        st.error(f"Error displaying molecules. {img}")


if cpds is not None:
    if isinstance(active_pandas, pd.DataFrame):
        st.markdown(
            "##### Similar bioactivity in PubChem",
            help="Compounds active in the same human bioassay",
        )
        display_pubchem_pandas(active_pandas)

    if isinstance(cpds, pd.DataFrame):
        st.markdown("##### Similar structures in PubChem")
        display_pubchem_pandas(cpds)

if isinstance(vs_output, pd.DataFrame):
    st.markdown("##### Similar structures in ZINC")
    try:
        # If using PandasTools which requires libXrender.so.1
        # from rdkit.Chem import PandasTools
        # PandasTools.AddMoleculeColumnToFrame(vs_output, "smiles", "Molecule")

        # pandas_html = re.sub(
        #     r"^<table",
        #     '<table width="100%"',
        #     vs_output.to_html(escape=False),
        # )
        # st.markdown(pandas_html, unsafe_allow_html=True)

        # If using svg_to_data_url
        vs_output["structure"] = (
            vs_output["smiles"].apply(smiles2svg).apply(svg_to_data_url)
        )
        # Reorder columns
        col_order = (
            ["structure"]
            + vs_config["zinc"]["col_display"]
            + vs_config["zinc"]["col_simscore"]
        )
        st.dataframe(
            vs_output[col_order],
            row_height=100,
            column_config={
                "structure": st.column_config.ImageColumn("Structure", width="large")
            },
            hide_index=True,
            use_container_width=True,
        )

    except Exception as e:
        st.error(f"Error with displaying vs_output: {e}")
elif isinstance(vs_output, str):
    st.error(f"Vector Search exception: {vs_output}")
