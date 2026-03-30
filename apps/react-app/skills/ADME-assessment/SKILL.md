---
name: ADME-assessment
description: Based on a compound, get its ADME and other properties. Assess compounds for ADME (Absorption, Distribution, Metabolism, Excretion) characteristics, chemical properties, and drug-likeness using PubChem. Use when the user wants to evaluate compound suitability as a lead candidate. Triggers include requests like "assess drug-likeness for [compound]", "evaluate ADME for [CID]", "ADME assessment", "check Lipinski rules for [compound]", "molecular properties of [drug]", or "is [compound] a good lead candidate". Accepts PubChem CIDs, compound names, SMILES, or InChI as input.
---

# ADME Assessment Skill

Assess compounds for lead optimization by evaluating chemical properties, drug-likeness, and ADME characteristics via PubChem MCP tools.

## Workflow Overview

1. **Resolve compound identifier** → Get PubChem CID from name/SMILES/InChI
2. **Get molecular properties** → MW, logP, TPSA, HBD, HBA, rotatable bonds
3. **Assess drug-likeness** → Lipinski Rule of Five, Veber rules, PAINS filters
4. **Predict ADME properties** → Absorption, distribution, metabolism, excretion
5. **Analyze molecular complexity** → Synthetic accessibility, structural features
6. **Format output** → Present assessment as markdown table with pass/fail indicators

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

If multiple CIDs are provided (batch assessment), process each compound sequentially.

## Step 2: Get Molecular Properties

```
PubChem:get_compound_properties(cid=<CID>)
```

Extract key properties:
- **Molecular Weight (MW)**
- **LogP** (partition coefficient)
- **TPSA** (topological polar surface area)
- **HBD** (hydrogen bond donors)
- **HBA** (hydrogen bond acceptors)
- **Rotatable Bonds**
- **Ring Count**
- **Aromatic Ring Count**

Also retrieve structural information:
```
PubChem:get_compound_info(cid=<CID>)
```

Returns: molecular formula, SMILES, InChI, canonical structure.

## Step 3: Assess Drug-Likeness

```
PubChem:assess_drug_likeness(cid=<CID>)
```

Evaluates against established rules:

### Lipinski Rule of Five
| Rule | Threshold | Interpretation |
|------|-----------|----------------|
| MW | ≤ 500 Da | Good oral absorption |
| LogP | ≤ 5 | Adequate lipophilicity |
| HBD | ≤ 5 | Hydrogen bond donors |
| HBA | ≤ 10 | Hydrogen bond acceptors |

*One violation allowed for oral drugs*

### Veber Rules (Oral Bioavailability)
| Rule | Threshold |
|------|-----------|
| TPSA | ≤ 140 Å² |
| Rotatable Bonds | ≤ 10 |

### PAINS Filters
Identifies pan-assay interference compounds (false positives in HTS).

## Step 4: Predict ADME Properties

```
PubChem:predict_admet_properties(cid=<CID>)
```

Extract ADME-relevant predictions (exclude toxicity):

### Absorption
- Intestinal absorption
- Caco-2 permeability
- P-glycoprotein substrate/inhibitor

### Distribution
- Blood-brain barrier penetration
- Plasma protein binding
- Volume of distribution

### Metabolism
- CYP450 substrate (CYP1A2, CYP2C9, CYP2C19, CYP2D6, CYP3A4)
- CYP450 inhibitor predictions

### Excretion
- Renal clearance predictions
- Half-life estimates (if available)

## Step 5: Analyze Molecular Complexity

```
PubChem:analyze_molecular_complexity(cid=<CID>)
```

Assess:
- **Synthetic accessibility score** (1-10, lower = easier)
- **Fraction sp3 carbons** (higher = more 3D character)
- **Stereocenters count**
- **Structural complexity metrics**

Optional - for pharmacophore insights:
```
PubChem:get_pharmacophore_features(cid=<CID>)
```

## Step 6: Format Output

Present results in this format:

```markdown
## ADME Assessment for [COMPOUND_NAME]

**Compound**: [NAME] (CID: [CID])  
**Formula**: [FORMULA]  
**SMILES**: [SMILES]

### Molecular Properties

| Property | Value | Threshold | Status |
|----------|-------|-----------|--------|
| Molecular Weight | X Da | ≤ 500 | ✓/✗ |
| LogP | X | ≤ 5 | ✓/✗ |
| TPSA | X Å² | ≤ 140 | ✓/✗ |
| HBD | X | ≤ 5 | ✓/✗ |
| HBA | X | ≤ 10 | ✓/✗ |
| Rotatable Bonds | X | ≤ 10 | ✓/✗ |

### Drug-Likeness Summary

| Rule Set | Violations | Status |
|----------|------------|--------|
| Lipinski Ro5 | X/4 | Pass/Fail |
| Veber | X/2 | Pass/Fail |
| PAINS | X alerts | Pass/Concern |

### ADME Predictions

| Property | Prediction | Confidence |
|----------|------------|------------|
| Intestinal Absorption | High/Low | X% |
| BBB Penetration | Yes/No | X% |
| CYP3A4 Substrate | Yes/No | X% |
| CYP2D6 Inhibitor | Yes/No | X% |
| ... | ... | ... |

### Complexity Analysis

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Synthetic Accessibility | X/10 | Easy/Moderate/Difficult |
| Fsp3 | X | Low/Moderate/High 3D character |
| Stereocenters | X | Complexity consideration |

### Overall Assessment

[Brief summary: Is this a good lead candidate? Key strengths and liabilities.]
```

## Error Handling

- **Compound not found**: If search returns no results, suggest alternative names, check SMILES validity, or ask for CID directly
- **Missing ADME predictions**: Note which predictions are unavailable; some compounds lack sufficient data
- **Multiple matches**: If search returns multiple CIDs, list top matches and ask user to specify

## Example Usage

**User**: "Assess erlotinib as a lead compound"

**Claude workflow**:
1. `PubChem:search_compounds(query="erlotinib")` → CID 176870
2. `PubChem:get_compound_properties(cid=176870)`
3. `PubChem:assess_drug_likeness(cid=176870)`
4. `PubChem:predict_admet_properties(cid=176870)` (exclude toxicity)
5. `PubChem:analyze_molecular_complexity(cid=176870)`
6. Format and present assessment table

## Batch Assessment

For multiple compounds, present a comparison table:

```markdown
## ADME Comparison

| Compound | MW | LogP | TPSA | Ro5 | Veber | PAINS | Synth. Access. |
|----------|-----|------|------|-----|-------|-------|----------------|
| Compound A | X | X | X | ✓ | ✓ | ✓ | 3.2 |
| Compound B | X | X | X | ✓ | ✗ | ✓ | 5.1 |
```
