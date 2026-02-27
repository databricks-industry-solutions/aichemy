---
name: safety-assessment
description: Based on a compound, get its safety info. Assess compound safety profile including toxicity, hazard classifications, and regulatory information using PubChem and PubMed. Use when the user wants to evaluate safety concerns for a compound or drug candidate. Triggers include requests like "safety assessment for [compound]", "toxicity profile of [drug]", "is [compound] safe", "hazard information for [CID]", "regulatory status of [drug]", "LD50 for [compound]", or "carcinogenicity data for [drug]". Accepts PubChem CIDs, compound names, SMILES, or InChI as input. Returns safety data with supporting literature from PubMed.
---

# Safety Assessment Skill

Assess compound safety profile including toxicity data, hazard classifications, and regulatory information via PubChem and PubMed MCP tools.

## Workflow Overview

1. **Resolve compound identifier** → Get PubChem CID from name/SMILES/InChI
2. **Get safety data** → GHS hazard classifications, safety warnings
3. **Get toxicity information** → LD50, carcinogenicity, mutagenicity, reproductive toxicity
4. **Get regulatory information** → FDA, EPA, and international agency data
5. **Search PubMed for evidence** → Find supporting literature on compound safety
6. **Format output** → Present assessment with literature references

## Step 1: Resolve Compound Identifier

Convert user input to PubChem CID using appropriate **PubChem MCP tool**:

**By name or identifier:**
```
PubChem:search_compounds(query="<compound_name>")
```

**By SMILES:**
```
PubChem:search_by_smiles(smiles="<SMILES_string>")
```

**By InChI:**
```
PubChem:search_by_inchi(inchi="<InChI_string>")
```

**By CAS number:**
```
PubChem:search_by_cas_number(cas_number="<CAS>")
```

## Step 2: Get Safety Data (GHS Hazards)

```
PubChem:get_safety_data(cid=<CID>)
```

Extract GHS (Globally Harmonized System) information:
- **Hazard Statements** (H-codes): e.g., H301 "Toxic if swallowed"
- **Precautionary Statements** (P-codes): e.g., P264 "Wash hands thoroughly after handling"
- **Signal Word**: Danger / Warning
- **Pictograms**: Health hazard, flame, corrosion, etc.
- **Hazard Classes**: Acute toxicity, carcinogenicity, etc.

## Step 3: Get Toxicity Information

```
PubChem:get_toxicity_info(cid=<CID>)
```

Extract toxicological data:

### Acute Toxicity
- **LD50** (oral, dermal, inhalation) with species and route
- **LC50** for inhalation toxicity

### Chronic/Long-term Toxicity
- **Carcinogenicity**: IARC classification, NTP status
- **Mutagenicity**: Ames test results, genotoxicity data
- **Reproductive Toxicity**: Teratogenicity, developmental effects
- **Organ Toxicity**: Target organs, repeated dose effects

### Environmental Toxicity
```
PubChem:assess_environmental_fate(cid=<CID>)
```
- Aquatic toxicity (LC50 fish, EC50 daphnia)
- Biodegradation potential
- Bioaccumulation factor

## Step 4: Get Regulatory Information

```
PubChem:get_regulatory_info(cid=<CID>)
```

Extract regulatory status from:
- **FDA**: Drug approval status, warnings, black box warnings
- **EPA**: Pesticide registration, toxic substances
- **REACH**: European chemicals regulation
- **Other agencies**: OSHA, NIOSH, state regulations

## Step 5: Search PubMed for Supporting Evidence

Use **PubMed MCP tools** to find literature on compound safety.

### 5a. Search for Toxicity Studies

```
PubMed:search_articles(query="<compound_name> toxicity", max_results=10)
```

Additional targeted searches:
```
PubMed:search_articles(query="<compound_name> carcinogenicity")
PubMed:search_articles(query="<compound_name> mutagenicity")
PubMed:search_articles(query="<compound_name> safety")
PubMed:search_articles(query="<compound_name> adverse effects")
```

### 5b. Get Article Metadata

For relevant PMIDs found:
```
PubMed:get_article_metadata(pmids=["<PMID1>", "<PMID2>", ...])
```

Extract: title, authors, journal, publication date, abstract.

### 5c. Cross-Reference with PubChem Literature

```
PubChem:get_literature_references(cid=<CID>)
```

Merge PMIDs from PubChem with PubMed search results, prioritizing safety-related publications.

## Step 6: Format Output

Present results in this format:

```markdown
## Safety Assessment for [COMPOUND_NAME]

**Compound**: [NAME] (CID: [CID])

### GHS Hazard Classification

| Category | Information |
|----------|-------------|
| Signal Word | [Danger/Warning] |
| Pictograms | [List] |
| Hazard Class | [Classes] |

**Hazard Statements:**
- [H-code]: [Statement]
- [H-code]: [Statement]

**Precautionary Statements:**
- [P-code]: [Statement]

### Toxicity Data

#### Acute Toxicity
| Route | Species | Value | Reference |
|-------|---------|-------|-----------|
| Oral LD50 | Rat | X mg/kg | [PMID](link) |
| Dermal LD50 | Rabbit | X mg/kg | [PMID](link) |

#### Carcinogenicity
| Source | Classification | Details |
|--------|----------------|---------|
| IARC | Group [X] | [Description] |
| NTP | [Status] | [Details] |

#### Mutagenicity
| Test | Result | Reference |
|------|--------|-----------|
| Ames Test | Positive/Negative | [PMID](link) |

#### Reproductive Toxicity
[Summary with references]

### Regulatory Status

| Agency | Status | Details |
|--------|--------|---------|
| FDA | [Status] | [Details] |
| EPA | [Status] | [Details] |
| REACH | [Status] | [Details] |

### Supporting Literature

| PMID | Title | Journal | Year |
|------|-------|---------|------|
| [PMID](https://pubmed.ncbi.nlm.nih.gov/[PMID]) | [Title] | [Journal] | [Year] |
| [PMID](https://pubmed.ncbi.nlm.nih.gov/[PMID]) | [Title] | [Journal] | [Year] |

### Safety Summary

[Brief summary: Key safety concerns, risk level, recommendations for handling]
```

## Error Handling

- **Compound not found**: Suggest alternative names or ask for CID directly
- **Limited safety data**: Note data gaps; some compounds lack comprehensive toxicity testing
- **No PubMed results**: Report that no safety literature was found; suggest broader search terms
- **Conflicting data**: Present all sources and note discrepancies

## Example Usage

**User**: "Safety assessment for acetaminophen"

**Claude workflow**:
1. `PubChem:search_compounds(query="acetaminophen")` → CID 1983
2. `PubChem:get_safety_data(cid=1983)`
3. `PubChem:get_toxicity_info(cid=1983)`
4. `PubChem:get_regulatory_info(cid=1983)`
5. `PubMed:search_articles(query="acetaminophen toxicity", max_results=10)`
6. `PubMed:get_article_metadata(pmids=[...])` for top results
7. Format and present safety assessment with literature links

## Batch Assessment

For multiple compounds, present a comparison table:

```markdown
## Safety Comparison

| Compound | LD50 (oral) | Carcinogen | Mutagen | GHS Signal | Key Concern |
|----------|-------------|------------|---------|------------|-------------|
| Compound A | X mg/kg | No | No | Warning | Hepatotoxicity |
| Compound B | X mg/kg | Group 2B | No | Danger | Nephrotoxicity |
```
