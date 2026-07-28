---
name: hit-identification
description: Based on a target, get its associated drugs. Identify small molecule hits for therapeutic targets by querying Open Targets and ChEMBL. Use when the user provides a gene symbol (e.g., EGFR, BRAF, KRAS) or protein name and wants to find known compounds, drugs, or chemical matter with activity against that target. Returns compound identifiers, names, bioactivity data, clinical trial phases, mechanism of action summaries, and supporting literature with PubMed links. Triggers include requests like "find hits for [target]", "what compounds bind [gene]", "identify drugs targeting [protein]", "small molecules for [target]", or "hit identification for [gene symbol]".
---

# Hit Identification Skill

Identify known small molecule hits for a therapeutic target by querying Open Targets and ChEMBL via MCP tools.

## Workflow Overview

1. **Resolve target identifier** → Convert gene symbol/protein name to Ensembl ID
2. **Query Open Targets** → Get associated drugs, clinical phases, mechanism of action, and literature
3. **Query ChEMBL** → Get compound IDs, bioactivity data, and additional references
4. **Merge and prioritize** → Combine results and rank by association score, trial phase, bioactivity
5. **Format output** → Present top 25 hits as markdown table

## Step 1: Resolve Target Identifier

Use **Open Targets MCP**:

```
Open Targets:search_entities(query_strings=["<user_input>"])
```

Select the result where `entity` = "target" to get the Ensembl gene ID (e.g., `ENSG00000146648` for EGFR).

## Step 2: Query Open Targets and ChEMBL for Known Drugs

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

### 2b. Query ChEMBL by Target

Also search ChEMBL for compounds tested against the target:

```
ChEMBL:search_by_target(target_name="<gene_symbol>")
```

This returns compounds with bioassay data against the target, including those not yet in Open Targets. Merge these results with Open Targets hits, avoiding duplicates.

## Step 3: Enrich Compound Data from ChEMBL

Use **ChEMBL MCP tools** to enrich compound information for hits from Steps 2a and 2b.

### 3a. Get ChEMBL ID and Basic Info

For each drug name or ChEMBL ID from Open Targets:

```
ChEMBL:search_compounds(query="<drug_name>")
```

Or get external references:

```
ChEMBL:get_external_references(chembl_id=<CHEMBL_ID>)
```

This returns cross-references to DrugBank, KEGG, etc.

### 3b. Get Compound Details

Once you have the ChEMBL ID:

```
ChEMBL:get_compound_info(chembl_id=<CHEMBL_ID>)
```

Returns: molecular formula, weight, SMILES, InChI, synonyms.

### 3c. Get Bioactivity Data

Query bioassay results for the compound:

```
ChEMBL:get_compound_bioactivities(chembl_id=<CHEMBL_ID>)
```

Extract activity values (IC50, EC50, Ki, etc.). Filter for assays related to the target gene.

### 3d. Get Literature References (PMIDs)

```
ChEMBL:get_literature_references(chembl_id=<CHEMBL_ID>)
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

| Rank | Name | ChEMBL ID | Bioactivity | Phase | MoA Summary | References |
|------|------|-----------|-------------|-------|-------------|------------|
| 1 | [Drug Name] | [CHEMBL_ID](https://www.ebi.ac.uk/chembl/compound_report_card/[CHEMBL_ID]) | IC50: X nM | 4 | [Brief MoA] | [PMID1](https://pubmed.ncbi.nlm.nih.gov/[PMID1]), [PMID2](https://pubmed.ncbi.nlm.nih.gov/[PMID2]) |
| 2 | ... | ... | ... | ... | ... | ... |
```

### Column Definitions

| Column | Content |
|--------|---------|
| Rank | Priority ranking (1 = highest) |
| Name | Compound or drug name |
| ChEMBL ID | ChEMBL compound ID with hyperlink |
| Bioactivity | Most relevant activity value (IC50, Ki, EC50) with units |
| Phase | Clinical trial phase (0-4, or "-" if none) |
| MoA Summary | Brief mechanism of action (≤50 words) |
| References | PMIDs with PubMed hyperlinks (max 3) |

## Error Handling

- **Target not found**: If `search_entities` returns no target match, inform user and suggest alternative spellings or synonyms
- **No drugs found**: If Open Targets returns empty `knownDrugs`, report this and suggest checking related targets or pathway members
- **ChEMBL lookup fails**: If enrichment fails for a ChEMBL ID, include the compound with the ID from Open Targets and note "enrichment unavailable"
- **Missing bioactivity**: If no assay data available, use "-" in the Bioactivity column

## Example Usage

**User**: "Find hits for BRAF"

**Claude workflow**:
1. `search_entities(["BRAF"])` → `ENSG00000157764`
2. Query Open Targets GraphQL for target drugs
3. For each ChEMBL ID, fetch bioassay and compound data from ChEMBL
4. Merge, rank, and output top 25 as markdown table
