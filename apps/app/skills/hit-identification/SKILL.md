---
name: hit-identification
description: Based on a target, get its associated drugs. Identify small molecule hits for therapeutic targets by querying Open Targets and PubChem. Use when the user provides a gene symbol (e.g., EGFR, BRAF, KRAS) or protein name and wants to find known compounds, drugs, or chemical matter with activity against that target. Returns compound identifiers, names, bioactivity data, clinical trial phases, mechanism of action summaries, and supporting literature with PubMed links. Triggers include requests like "find hits for [target]", "what compounds bind [gene]", "identify drugs targeting [protein]", "small molecules for [target]", or "hit identification for [gene symbol]".
---

# Hit Identification Skill

Identify known small molecule hits for a therapeutic target by querying Open Targets and PubChem via MCP tools.

## Workflow Overview

1. **Resolve target identifier** → Convert gene symbol/protein name to Ensembl ID
2. **Query Open Targets** → Get associated drugs, clinical phases, mechanism of action, and literature
3. **Query PubChem** → Get compound IDs, bioactivity data, and additional references
4. **Merge and prioritize** → Combine results and rank by association score, trial phase, bioactivity
5. **Format output** → Present top 25 hits as markdown table

## Step 1: Resolve Target Identifier

Use **Open Targets MCP**:

```
Open Targets:search_entities(query_strings=["<user_input>"])
```

Select the result where `entity` = "target" to get the Ensembl gene ID (e.g., `ENSG00000146648` for EGFR).

## Step 2: Query Open Targets and PubChem for Known Drugs

### 2a. Query Open Targets

First, call `Open Targets:get_open_targets_graphql_schema` to understand available fields.

Then execute with `Open Targets:query_open_targets_graphql`:

```graphql
query TargetDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    knownDrugs {
      uniqueDrugs
      rows {
        drug {
          id
          name
          mechanismsOfAction {
            rows {
              mechanismOfAction
              references {
                source
                ids
              }
            }
          }
        }
        phase
        status
        references {
          source
          ids
        }
      }
    }
  }
}
```

Variables: `{"ensemblId": "<ENSEMBL_ID>"}`

Extract from results:
- **ChEMBL ID**: `drug.id`
- **Drug name**: `drug.name`
- **Trial phase**: `phase` (4 = approved, 3 = Phase III, etc.)
- **MoA**: `mechanismsOfAction.rows[].mechanismOfAction`
- **PMIDs**: Filter `references` where `source` = "PubMed"

### 2b. Query PubChem by Target

Also search PubChem for compounds tested against the target:

```
PubChem:search_by_target(target_name="<gene_symbol>")
```

This returns compounds with bioassay data against the target, including those not yet in Open Targets. Merge these results with Open Targets hits, avoiding duplicates.

## Step 3: Enrich Compound Data from PubChem

Use **PubChem MCP tools** to enrich compound information for hits from Steps 2a and 2b.

### 3a. Get PubChem CID and Basic Info

For each drug name or ChEMBL ID from Open Targets:

```
PubChem:search_compounds(query="<drug_name>")
```

Or search by external reference:

```
PubChem:get_external_references(cid=<CID>)
```

This returns cross-references to ChEMBL, DrugBank, KEGG, etc.

### 3b. Get Compound Details

Once you have the CID:

```
PubChem:get_compound_info(cid=<CID>)
```

Returns: molecular formula, weight, SMILES, InChI, synonyms.

### 3c. Get Bioactivity Data

Query bioassay results for the compound:

```
PubChem:get_compound_bioactivities(cid=<CID>)
```

Extract activity values (IC50, EC50, Ki, etc.). Filter for assays related to the target gene.

### 3d. Get Literature References (PMIDs)

```
PubChem:get_literature_references(cid=<CID>)
```

Returns PubMed citations. Use only PMIDs also referenced in Open Targets or directly related to target activity.

## Step 4: Merge and Prioritize Results

Combine data from both sources and rank by:

1. **Open Targets association score** (higher = stronger evidence)
2. **Clinical trial phase** (4 > 3 > 2 > 1 > 0)
3. **Bioactivity potency** (lower IC50/Ki = more potent)

Return top 25 hits after ranking.

## Step 5: Format Output as Markdown Table

Present results in this format:

```markdown
## Hit Identification Results for [TARGET_SYMBOL]

**Target**: [GENE_SYMBOL] ([ENSEMBL_ID])  
**Total hits found**: [N]  
**Showing**: Top 25 ranked by association score, trial phase, and bioactivity

| Rank | Name | CID | Bioactivity | Phase | MoA Summary | References |
|------|------|-----|-------------|-------|-------------|------------|
| 1 | [Drug Name] | [CID](https://pubchem.ncbi.nlm.nih.gov/compound/[CID]) | IC50: X nM | 4 | [Brief MoA] | [PMID1](https://pubmed.ncbi.nlm.nih.gov/[PMID1]), [PMID2](https://pubmed.ncbi.nlm.nih.gov/[PMID2]) |
| 2 | ... | ... | ... | ... | ... | ... |
```

### Column Definitions

| Column | Content |
|--------|---------|
| Rank | Priority ranking (1 = highest) |
| Name | Compound or drug name |
| CID | PubChem Compound ID with hyperlink |
| Bioactivity | Most relevant activity value (IC50, Ki, EC50) with units |
| Phase | Clinical trial phase (0-4, or "-" if none) |
| MoA Summary | Brief mechanism of action (≤50 words) |
| References | PMIDs with PubMed hyperlinks (max 3) |

## Error Handling

- **Target not found**: If `search_entities` returns no target match, inform user and suggest alternative spellings or synonyms
- **No drugs found**: If Open Targets returns empty `knownDrugs`, report this and suggest checking related targets or pathway members
- **PubChem lookup fails**: If CID lookup fails for a ChEMBL ID, include the compound with ChEMBL ID only and note "CID not found"
- **Missing bioactivity**: If no assay data available, use "-" in the Bioactivity column

## Example Usage

**User**: "Find hits for BRAF"

**Claude workflow**:
1. `search_entities(["BRAF"])` → `ENSG00000157764`
2. Query Open Targets GraphQL for target drugs
3. For each ChEMBL ID, fetch PubChem CID and bioassay data
4. Merge, rank, and output top 25 as markdown table
