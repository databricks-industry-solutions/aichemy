---
name: ADME-assessment
description: Based on a compound, get its ADME and other properties. Assess compounds for ADME (Absorption, Distribution, Metabolism, Excretion) characteristics, physicochemical properties, and drug-likeness using ChEMBL MCP, the directly available predict_admet tool, and PubMed. Then package findings with create_docx. Use when the user wants to evaluate compound suitability as a lead candidate. Triggers include requests like "assess drug-likeness for [compound]", "evaluate ADME for [ChEMBL ID]", "ADME assessment", "check Lipinski rules for [compound]", "molecular properties of [drug]", or "is [compound] a good lead candidate". Accepts ChEMBL IDs, compound names, or SMILES as input.
---

# ADME Assessment Skill

Build an ADME / drug-likeness assessment by combining:

1. **ChEMBL MCP** — resolve the compound, get structure/metadata, and any experimental bioactivities
2. **`predict_admet` (direct tool)** — fullname is `healthcare_lifesciences__qsar__predict_admet`. Predict ADMET + physicochemical properties from SMILES (ADMET-AI / ChemProp)
3. **PubMed MCP** — supporting ADME / PK / bioavailability literature
4. **`create_docx`** — package the assessment as a downloadable Word report

Do **not** call blacklisted or non-existent tools such as `predict_admet_properties`, `assess_drug_likeness`, `analyze_molecular_complexity`, or `get_pharmacophore_features`. Use the tools listed below only.

`predict_admet` and `create_docx` belong to the supervisor; only the ChEMBL and PubMed steps are delegated to the mcp agent. The mcp agent must return its lookups (SMILES, citations) rather than attempt those two tools.

**Autonomous execution — no permission prompts:** Run the full workflow end-to-end in one session. After ChEMBL returns SMILES, immediately call `predict_admet` yourself — do **not** ask the user "shall I run ADMET prediction?" or wait for confirmation. After the assessment is complete, call `create_docx` automatically unless the user explicitly asked for chat-only output. Only stop to ask the user if the compound cannot be resolved (ambiguous name with no clear parent molecule).

## Workflow Overview

1. **Resolve compound** → ChEMBL ID + SMILES via `chembl_search_molecules` / `chembl_get_molecule`
2. **Predict ADMET** → Call `healthcare_lifesciences__qsar__predict_admet(smiles=...)` directly (required for missing ADMET endpoints)
3. **Assess drug-likeness** → Apply Lipinski / Veber rules from predicted or available physicochemical properties
4. **Optional experimental context** → `chembl_get_bioactivities` for ADME-relevant assay data
5. **Literature** → PubMed search for ADME / PK evidence
6. **Format findings** → Structure markdown per the assessment template below
7. **Export DOCX** → Call `create_docx`, then paste the download link in the chat reply

## Step 1: Resolve Compound Identifier (ChEMBL)

### By name or synonym

```
chembl_search_molecules(query="<compound_name>", search_by="name", max_results=10)
```

### By SMILES

```
chembl_search_molecules(query="<SMILES_string>", search_by="smiles", max_results=10)
```

### By known ChEMBL ID

```
chembl_get_molecule(chembl_id="CHEMBL...")
```

From search hits, prefer the parent small molecule (not salt forms) when both exist (e.g. `CHEMBL553` over `CHEMBL1079742` for erlotinib). Then confirm with:

```
chembl_get_molecule(chembl_id="<CHEMBL_ID>")
```

Extract and keep:

- `chembl_id`, `pref_name`, `smiles`, `inchi_key`, `max_phase`, `molecule_type`, `synonyms`

**Critical:** Do not fabricate SMILES. Always take SMILES from ChEMBL tool output before calling `predict_admet`.

If the user already provides a valid SMILES and ChEMBL lookup fails, proceed with `predict_admet` using that SMILES and note that ChEMBL enrichment was unavailable.

## Step 2: Predict ADMET Properties

Call the directly available `predict_admet` tool (named `healthcare_lifesciences__qsar__predict_admet` in full):

```
predict_admet(smiles="<SMILES_from_ChEMBL>")
```

This calls the ADMET-AI ChemProp models and returns JSON with physicochemical properties plus ~40 ADMET endpoints (classification probabilities and regression values, often with DrugBank percentiles).

Use these predictions to fill ADME gaps that ChEMBL does not provide (BBB, CYP liabilities, solubility, bioavailability, half-life, clearance, hERG, etc.).

### Focus on ADME (de-emphasize pure toxicity unless asked)

**Absorption**

- Human intestinal absorption / oral bioavailability
- Caco-2 / PAMPA-like permeability (if present)
- P-gp substrate/inhibitor (if present)
- Aqueous solubility

**Distribution**

- Blood–brain barrier penetration
- Plasma protein binding / VDss (if present)

**Metabolism**

- CYP450 substrate / inhibitor endpoints (1A2, 2C9, 2C19, 2D6, 3A4, etc.)

**Excretion**

- Clearance, half-life (if present)

When presenting classification outputs, report the predicted probability (and percentile if returned). For regression outputs, include units from the tool response.

## Step 3: Assess Drug-Likeness from Properties

ChEMBL MCP does **not** expose a dedicated drug-likeness tool. Compute rules yourself from physicochemical fields returned by `predict_admet` (and any MW/logP/TPSA-like fields if present in ChEMBL metadata).

### Lipinski Rule of Five

| Rule | Threshold |
|------|-----------|
| MW | ≤ 500 Da |
| LogP | ≤ 5 |
| HBD | ≤ 5 |
| HBA | ≤ 10 |

*One violation allowed for oral drugs.*

### Veber Rules (oral bioavailability)

| Rule | Threshold |
|------|-----------|
| TPSA | ≤ 140 Å² |
| Rotatable bonds | ≤ 10 |

Mark each rule Pass/Fail. If a property is missing from tool output, mark it as `n/a` — do not invent values.

## Step 4: Optional Experimental Bioactivities (ChEMBL)

For experimental ADME-related context (not a substitute for `predict_admet`):

```
chembl_get_bioactivities(chembl_id="<CHEMBL_ID>", id_type="molecule", max_results=20)
```

Optionally filter with `standard_type` (e.g. related to permeability, clearance, or CYP assays when known). Summarize only ADME-relevant rows; skip unrelated potency assays unless the user asks.

`chembl_search_targets` is usually unnecessary for ADME assessment unless the user asks about a specific ADME-related target (e.g. CYP3A4, P-gp/ABCB1).

## Step 5: PubMed Literature Support

Search for ADME / PK evidence:

```
pubmed_search_articles(query="<compound_name> ADME OR pharmacokinetics OR bioavailability OR absorption", max_results=10)
```

Useful alternate queries:

- `"<compound> CYP OR metabolism"`
- `"<compound> blood-brain barrier OR BBB"`
- `"<compound> clearance OR half-life"`

Fetch details for the most relevant hits:

```
pubmed_get_article(pmid="<PMID>")
```

Optionally refine MeSH terms first:

```
pubmed_search_mesh_terms(term="pharmacokinetics")
```

Cite ~3 strong papers with PMID links. Prefer reviews and human PK studies when available.

## Step 6: Structure Findings for Export

Structure the report body for `create_docx` using this section set (from create-docx-report skill):

1. Executive Summary  
2. Assessment Snapshot (table)  
3. Risks & Flags  
4. Literature Highlights  
5. Recommendations  
6. Note: study-design caveats / data provenance

### Content conventions for `create_docx`

```markdown
## Executive Summary
2–4 sentences. Lead with the decision-relevant takeaway (lead suitability and main ADME liabilities).

## Assessment Snapshot
| Property | Value | Threshold | Status | Source |
|----------|-------|-----------|--------|--------|
| Molecular Weight | X Da | ≤ 500 | Pass/Fail | predict_admet |
| LogP | X | ≤ 5 | Pass/Fail | predict_admet |
| ... | ... | ... | ... | ... |

## Risks & Flags
- One clear risk or flag per bullet
- Prefer short, scannable lines with specific numbers

## Literature Highlights
| PMID | Finding | Study type |
|------|---------|------------|
| [PMID](https://pubmed.ncbi.nlm.nih.gov/PMID) | Brief ADME-relevant takeaway | Review / human PK / ... |

## Recommendations
1. Numbered next step
2. Second recommendation

---

Note: ChEMBL for identity/structure; predict_admet (ADMET-AI) for modeled endpoints; PubMed for literature. Predictions are not clinical evidence.
```

## Step 7: Export DOCX

```
create_docx(
  title="<Compound> ADME Assessment",
  content="<markdown body per conventions above>",
  filename="<compound>_adme_assessment.docx"
)
```

### Final reply to the user

1. One short sentence confirming the report was created.
2. Include the **exact** markdown download link returned by `create_docx`.
3. Optionally list the sections included (bullets).

Based on whatever relevant ADME data was retrieved or predicted, go on to automatically produce the .docx report — do not ask the user for permission first.

## Error Handling

- **Compound not found in ChEMBL**: Try alternate names/synonyms; if SMILES is provided, still run `predict_admet` and PubMed by name/SMILES context
- **`predict_admet` fails**: Report the error; still return ChEMBL metadata + PubMed; do not invent ADMET values
- **Multiple ChEMBL matches**: List top hits (ID, name, max_phase) and continue with the best parent molecule unless the user specified otherwise
- **No PubMed hits**: Note absence; broaden query (e.g. INN name only + "pharmacokinetics")
- **Salt vs parent**: Prefer parent molecule for ADME prediction unless the user asked about a specific salt
- **DOCX export fails**: Still present the markdown assessment in chat and note that the Word export failed

## Example Usage

**User**: "Assess erlotinib as a lead compound"

**Agent workflow**:

1. `chembl_search_molecules(query="erlotinib", search_by="name")` → `CHEMBL553`, SMILES
2. `chembl_get_molecule(chembl_id="CHEMBL553")` → confirm metadata
3. `predict_admet(smiles="<SMILES>")` → physchem + ADMET endpoints
4. Score Lipinski / Veber from returned properties
5. Optional: `chembl_get_bioactivities(chembl_id="CHEMBL553", id_type="molecule")`
6. `pubmed_search_articles(query="erlotinib pharmacokinetics OR ADME OR bioavailability", max_results=10)`
7. `pubmed_get_article(pmid=...)` for top citations
8. `create_docx(title="Erlotinib ADME Assessment", content=..., filename="erlotinib_adme_assessment.docx")`
9. Reply with a short confirmation and the exact download link

## Batch Assessment

For multiple compounds, resolve each via ChEMBL, call `predict_admet` per SMILES, and present a comparison table in both chat and the DOCX Assessment Snapshot section.
