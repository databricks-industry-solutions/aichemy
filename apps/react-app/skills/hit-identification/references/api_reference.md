# API Reference

## Open Targets MCP Tools

### `Open Targets:search_entities`
Convert gene symbols/names to standardized IDs.

```
Open Targets:search_entities(query_strings=["EGFR", "BRAF"])
```

Response: `{"EGFR": [{"id": "ENSG00000146648", "entity": "target"}]}`

### `Open Targets:get_open_targets_graphql_schema`
Retrieve the full GraphQL schema.

### `Open Targets:query_open_targets_graphql`
Execute a single GraphQL query.

```
Open Targets:query_open_targets_graphql(
  query_string="query { target(ensemblId: $id) { ... } }",
  variables={"id": "ENSG00000146648"}
)
```

### `Open Targets:batch_query_open_targets_graphql`
Execute the same query with multiple variable sets.

### Key GraphQL Fields

```graphql
target(ensemblId: String!) {
  approvedSymbol
  knownDrugs {
    uniqueDrugs
    rows {
      drug { id, name, drugType, mechanismsOfAction { rows { mechanismOfAction, references { source, ids } } } }
      phase    # 0-4 (4=approved)
      status
      references { source, ids }
    }
  }
}
```

---

## PubChem MCP Tools

### Compound Search & Info

| Tool | Purpose |
|------|---------|
| `PubChem:search_compounds` | Search by name, CAS, formula, or identifier |
| `PubChem:get_compound_info` | Get detailed info by CID |
| `PubChem:get_compound_synonyms` | Get all names and synonyms |
| `PubChem:get_compound_properties` | Get MW, logP, TPSA, etc. |

### Structure-Based Search

| Tool | Purpose |
|------|---------|
| `PubChem:search_by_smiles` | Exact match by SMILES |
| `PubChem:search_by_inchi` | Search by InChI/InChI key |
| `PubChem:search_similar_compounds` | Tanimoto similarity search |
| `PubChem:substructure_search` | Find compounds with substructure |

### Bioactivity & Target

| Tool | Purpose |
|------|---------|
| `PubChem:search_by_target` | Find compounds tested against a target |
| `PubChem:get_compound_bioactivities` | Get all bioassay results for a compound |
| `PubChem:search_bioassays` | Search assays by target/description |
| `PubChem:get_assay_info` | Get assay details by AID |
| `PubChem:compare_activity_profiles` | Compare activities across compounds |

### Safety & Regulatory

| Tool | Purpose |
|------|---------|
| `PubChem:get_safety_data` | GHS hazard classifications |
| `PubChem:get_toxicity_info` | LD50, carcinogenicity, mutagenicity |
| `PubChem:get_regulatory_info` | FDA, EPA, international data |

### References & Cross-Links

| Tool | Purpose |
|------|---------|
| `PubChem:get_literature_references` | PubMed citations |
| `PubChem:get_external_references` | Links to ChEMBL, DrugBank, KEGG, etc. |
| `PubChem:search_patents` | Chemical patent information |

---

## URL Formats

- **PubChem Compound**: `https://pubchem.ncbi.nlm.nih.gov/compound/{CID}`
- **PubMed Article**: `https://pubmed.ncbi.nlm.nih.gov/{PMID}`

---

## Clinical Phase Values

| Phase | Meaning |
|-------|---------|
| 4 | Approved |
| 3 | Phase III |
| 2 | Phase II |
| 1 | Phase I |
| 0 | Preclinical |
