# API Reference

## PubChem Tools

| Tool | Purpose |
|------|---------|
| `PubChem:search_compounds` | Search by name, CAS, formula |
| `PubChem:search_by_smiles` | Exact match by SMILES |
| `PubChem:search_by_inchi` | Search by InChI/InChI key |
| `PubChem:search_by_cas_number` | Search by CAS Registry Number |
| `PubChem:get_toxicity_info` | LD50, carcinogenicity, mutagenicity, reproductive toxicity |
| `PubChem:assess_environmental_fate` | Biodegradation, bioaccumulation, aquatic toxicity |
| `PubChem:get_regulatory_info` | FDA, EPA, REACH, international agency data |
| `PubChem:get_literature_references` | PubMed citations linked to compound |

## PubMed Tools

| Tool | Purpose |
|------|---------|
| `PubMed:search_articles` | Search PubMed (`query`, `max_results`, `date_from`, `date_to`) |
| `PubMed:get_article_metadata` | Get article details by PMID (`pmids` array) |

## URL Formats

- **PubChem Compound**: `https://pubchem.ncbi.nlm.nih.gov/compound/{CID}`
- **PubMed Article**: `https://pubmed.ncbi.nlm.nih.gov/{PMID}`
