# API Reference

## PubChem MCP Tools for Safety Assessment

### Compound Identification

| Tool | Purpose | Parameters |
|------|---------|------------|
| `PubChem:search_compounds` | Search by name, CAS, formula | `query` |
| `PubChem:search_by_smiles` | Exact match by SMILES | `smiles` |
| `PubChem:search_by_inchi` | Search by InChI/InChI key | `inchi` |
| `PubChem:search_by_cas_number` | Search by CAS Registry Number | `cas_number` |
| `PubChem:get_compound_info` | Get detailed compound info | `cid` |

### Safety & Toxicity

| Tool | Purpose |
|------|---------|
| `PubChem:get_safety_data` | GHS hazard classifications, pictograms, H/P codes |
| `PubChem:get_toxicity_info` | LD50, carcinogenicity, mutagenicity, reproductive toxicity |
| `PubChem:assess_environmental_fate` | Biodegradation, bioaccumulation, aquatic toxicity |
| `PubChem:get_regulatory_info` | FDA, EPA, REACH, international agency data |

### Literature References

| Tool | Purpose |
|------|---------|
| `PubChem:get_literature_references` | PubMed citations linked to compound |

---

## PubMed MCP Tools

### Article Search

| Tool | Purpose | Parameters |
|------|---------|------------|
| `PubMed:search_articles` | Search PubMed | `query`, `max_results`, `date_from`, `date_to` |
| `PubMed:get_article_metadata` | Get article details by PMID | `pmids` (array) |

### Useful Search Queries for Safety

```
"<compound> toxicity"
"<compound> carcinogenicity"
"<compound> mutagenicity"  
"<compound> genotoxicity"
"<compound> reproductive toxicity"
"<compound> teratogenicity"
"<compound> hepatotoxicity"
"<compound> nephrotoxicity"
"<compound> adverse effects"
"<compound> safety profile"
"<compound> LD50"
```

---

## GHS Hazard Classifications

### Signal Words
| Word | Severity |
|------|----------|
| **Danger** | More severe hazards |
| **Warning** | Less severe hazards |

### Common Hazard Statements (H-codes)

#### Acute Toxicity
| Code | Statement |
|------|-----------|
| H300 | Fatal if swallowed |
| H301 | Toxic if swallowed |
| H302 | Harmful if swallowed |
| H310 | Fatal in contact with skin |
| H330 | Fatal if inhaled |

#### Carcinogenicity
| Code | Statement |
|------|-----------|
| H350 | May cause cancer |
| H351 | Suspected of causing cancer |

#### Mutagenicity
| Code | Statement |
|------|-----------|
| H340 | May cause genetic defects |
| H341 | Suspected of causing genetic defects |

#### Reproductive Toxicity
| Code | Statement |
|------|-----------|
| H360 | May damage fertility or the unborn child |
| H361 | Suspected of damaging fertility or the unborn child |

---

## IARC Carcinogen Classifications

| Group | Meaning |
|-------|---------|
| Group 1 | Carcinogenic to humans |
| Group 2A | Probably carcinogenic to humans |
| Group 2B | Possibly carcinogenic to humans |
| Group 3 | Not classifiable |

## NTP Classifications

| Category | Meaning |
|----------|---------|
| Known | Known to be human carcinogen |
| RAHC | Reasonably anticipated to be human carcinogen |

---

## URL Formats

- **PubChem Compound**: `https://pubchem.ncbi.nlm.nih.gov/compound/{CID}`
- **PubMed Article**: `https://pubmed.ncbi.nlm.nih.gov/{PMID}`
