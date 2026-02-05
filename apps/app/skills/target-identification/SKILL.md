---
name: target-identification
description: Based on a disease, identify therapeutic targets. Use this skill when users ask to find drug targets, therapeutic targets, or druggable genes for any disease or condition. Triggers include queries like "find druggable targets for [disease]", "what are therapeutic targets for [disease]", "identify drug targets for [condition]", or any request to discover targetable genes/proteins for a disease. The skill uses Open Targets Platform for disease-target associations, clinical precedence, and tractability data, combined with PubMed for supporting mechanistic evidence. Outputs a ranked table of top 10 targets with evidence summaries.
---

# Druggable Targets Identification

Identify and prioritize druggable therapeutic targets for a disease using Open Targets and PubMed.

## Workflow Overview

1. **Resolve disease** → Get Open Targets disease ID
2. **Retrieve disease context** → Understand etiology/pathophysiology
3. **Query associated targets** → Get targets ranked by association score
4. **Enrich with clinical precedence** → Check existing drugs and trial phases
5. **Gather PubMed evidence** → Find supporting literature for top targets
6. **Generate output** → Markdown table with top 10 targets

## Step 1: Resolve Disease Identifier

Use `Open Targets:search_entities` to convert disease name to EFO/MONDO ID.

```
search_entities(query_strings=["<disease name>"])
```

Select the result where `entity` = "disease". If user provides an ID directly (EFO_*, MONDO_*), skip this step.

## Step 2: Retrieve Disease Context and Associated Targets

Query Open Targets for the disease and its associated targets in a single call. See `references/opentargets_queries.md` for the full GraphQL query.

Key fields to retrieve:
- Disease: `name`, `description`, `therapeuticAreas`
- Associated targets: sorted by `score` descending, retrieve top 25 to allow filtering
- For each target: `approvedSymbol`, `approvedName`, `id`, association `score`, `tractability`, `knownDrugs`

## Step 3: Prioritize Targets

From the associated targets, prioritize based on:

1. **Association score** (primary) — higher is better
2. **Clinical precedence** (primary) — targets with existing drugs score higher
3. **Tractability** (secondary) — targets with small molecule or antibody tractability preferred
4. **Safety** (secondary) — flag targets with known safety liabilities

Scoring heuristic:
- Base score = association score (0-1)
- Clinical bonus: +0.2 if approved drug exists, +0.1 if Phase III, +0.05 if Phase II
- Tractability bonus: +0.05 if small molecule tractable, +0.03 if antibody tractable

Re-rank top 25 targets using this composite score, select top 10.

## Step 4: Gather PubMed Evidence

For each of the top 10 targets, search PubMed for mechanistic evidence linking target to disease.

```
PubMed:search_articles(
  query="<target symbol> AND <disease name>",
  max_results=3,
  sort="relevance"
)
```

Then retrieve metadata for the top 1-2 most relevant articles:
```
PubMed:get_article_metadata(pmids=["<pmid1>", "<pmid2>"])
```

Extract: title, authors, year, and construct PMID link: `https://pubmed.ncbi.nlm.nih.gov/<pmid>/`

## Step 5: Generate Output

### Disease Overview (2-3 sentences)
Summarize the disease etiology based on Open Targets description and therapeutic areas.

### Druggable Targets Table

Output as markdown table with columns:

| Rank | Target | Association Score | Clinical Precedence | Tractability | Evidence Summary |
|------|--------|-------------------|---------------------|--------------|------------------|

**Column definitions:**
- **Rank**: 1-10
- **Target**: Gene symbol (full name), linked to Open Targets: `[SYMBOL](https://platform.opentargets.org/target/<ensembl_id>)`
- **Association Score**: 0-1, two decimal places
- **Clinical Precedence**: Highest phase drug if exists (e.g., "Phase IV: Tamoxifen") or "No drugs"
- **Tractability**: "SM" (small molecule), "Ab" (antibody), "Both", or "Limited"
- **Evidence Summary**: 1-3 sentences summarizing mechanistic link + PMID links

## Example Output

For query: "Find druggable targets for ER+ breast cancer"

---

### Disease Overview

Estrogen receptor-positive (ER+) breast cancer is characterized by tumor cells expressing estrogen receptors, driving proliferation through estrogen signaling. It represents approximately 70% of breast cancers and is associated with hormone-dependent growth pathways.

### Top 10 Druggable Targets

| Rank | Target | Association Score | Clinical Precedence | Tractability | Evidence Summary |
|------|--------|-------------------|---------------------|--------------|------------------|
| 1 | [ESR1](https://platform.opentargets.org/target/ENSG00000091831) (Estrogen Receptor 1) | 0.95 | Phase IV: Tamoxifen, Fulvestrant | Both | ESR1 is the primary driver of ER+ breast cancer proliferation. Endocrine therapies targeting ESR1 are first-line treatment. [PMID: 32555149](https://pubmed.ncbi.nlm.nih.gov/32555149/) |
| 2 | ... | ... | ... | ... | ... |

---

## Error Handling

- **Disease not found**: If search returns no disease matches, inform user and suggest checking spelling or using an EFO/MONDO ID
- **No associated targets**: Rare, but report that no significant target associations exist in Open Targets
- **PubMed search fails**: Proceed with Open Targets data alone, note that literature evidence is unavailable
