# API Reference

## ChEMBL Tools

| Tool | Purpose |
|------|---------|
| `ChEMBL:search_compounds` | Search by name, CAS, formula |
| `ChEMBL:search_by_smiles` | Exact match by SMILES |
| `ChEMBL:search_by_inchi` | Search by InChI/InChI key |
| `ChEMBL:search_by_cas_number` | Search by CAS Registry Number |
| `ChEMBL:get_toxicity_info` | LD50, carcinogenicity, mutagenicity, reproductive toxicity |
| `ChEMBL:assess_environmental_fate` | Biodegradation, bioaccumulation, aquatic toxicity |
| `ChEMBL:get_regulatory_info` | FDA, EPA, REACH, international agency data |
| `ChEMBL:get_literature_references` | PubMed citations linked to compound |

## PubMed Tools

| Tool | Purpose |
|------|---------|
| `PubMed:search_articles` | Search PubMed (`query`, `max_results`, `date_from`, `date_to`) |
| `PubMed:get_article_metadata` | Get article details by PMID (`pmids` array) |

## URL Formats

- **ChEMBL Compound**: `https://www.ebi.ac.uk/chembl/compound_report_card/{CHEMBL_ID}`
- **PubMed Article**: `https://pubmed.ncbi.nlm.nih.gov/{PMID}`
