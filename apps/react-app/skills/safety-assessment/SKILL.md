---
name: safety-assessment
description: Based on a compound, get its safety info. Assess compound safety profile including toxicity, hazard classifications, and regulatory information using PubChem and PubMed.
---

# Safety Assessment Skill

Assess compound safety via PubChem (GHS hazards, toxicity, regulatory) and PubMed (literature evidence).

## Workflow

1. **Resolve compound** → PubChem CID
2. **Safety data** → GHS hazard classifications
3. **Toxicity info** → LD50, carcinogenicity, mutagenicity, reproductive toxicity
4. **Regulatory info** → FDA, EPA, REACH status
5. **PubMed search** → Supporting safety literature
6. **Format output** → Assessment with literature references

## Step 1: Resolve Compound Identifier

Use the appropriate PubChem search tool based on input type:
- By name: `PubChem:search_compounds(query="<name>")`
- By SMILES: `PubChem:search_by_smiles(smiles="<SMILES>")`
- By InChI: `PubChem:search_by_inchi(inchi="<InChI>")`
- By CAS: `PubChem:search_by_cas_number(cas_number="<CAS>")`

## Step 2: Get Safety Data

`PubChem:get_safety_data(cid=<CID>)` — returns GHS hazard statements (H-codes), precautionary statements (P-codes), signal word, pictograms, and hazard classes.

## Step 3: Get Toxicity Information

`PubChem:get_toxicity_info(cid=<CID>)` — returns LD50/LC50 values, IARC/NTP carcinogenicity classifications, Ames test mutagenicity, and reproductive toxicity data.

For environmental toxicity: `PubChem:assess_environmental_fate(cid=<CID>)`

## Step 4: Get Regulatory Information

`PubChem:get_regulatory_info(cid=<CID>)` — returns FDA approval/warnings, EPA registration, REACH status, and other agency data.

## Step 5: Search PubMed for Evidence

```
PubMed:search_articles(query="<compound> toxicity", max_results=10)
```

Also search for: `<compound> carcinogenicity`, `<compound> safety`, `<compound> adverse effects`.

Get metadata for relevant PMIDs: `PubMed:get_article_metadata(pmids=[...])`

Cross-reference with: `PubChem:get_literature_references(cid=<CID>)`

## Step 6: Format Output

Present as structured markdown with sections for GHS classification, toxicity data (acute, carcinogenicity, mutagenicity, reproductive), regulatory status, supporting literature table (PMID, title, journal, year), and a brief safety summary.

## Error Handling

- **Compound not found**: Suggest alternative names or ask for CID
- **Limited data**: Note gaps; some compounds lack comprehensive testing
- **No PubMed results**: Note absence; suggest broader search terms
- **Conflicting data**: Present all sources and note discrepancies
