# API Reference

## PubChem MCP Tools for ADME Assessment

### Compound Search & Identification

| Tool | Purpose | Parameters |
|------|---------|------------|
| `PubChem:search_compounds` | Search by name, CAS, formula, identifier | `query` |
| `PubChem:search_by_smiles` | Exact match by SMILES | `smiles` |
| `PubChem:search_by_inchi` | Search by InChI/InChI key | `inchi` |
| `PubChem:search_by_cas_number` | Search by CAS Registry Number | `cas_number` |
| `PubChem:get_compound_info` | Get detailed compound info | `cid` |
| `PubChem:get_compound_synonyms` | Get all names and synonyms | `cid` |

### Molecular Properties

| Tool | Purpose | Key Outputs |
|------|---------|-------------|
| `PubChem:get_compound_properties` | Get molecular properties | MW, logP, TPSA, HBD, HBA, rotatable bonds |
| `PubChem:calculate_descriptors` | Calculate molecular descriptors & fingerprints | Comprehensive descriptor set |

### Drug-Likeness Assessment

| Tool | Purpose |
|------|---------|
| `PubChem:assess_drug_likeness` | Lipinski Ro5, Veber rules, PAINS filters |

**Lipinski Rule of Five:**
- MW ≤ 500 Da
- LogP ≤ 5
- HBD ≤ 5
- HBA ≤ 10

**Veber Rules:**
- TPSA ≤ 140 Å²
- Rotatable bonds ≤ 10

### ADME Predictions

| Tool | Purpose |
|------|---------|
| `PubChem:predict_admet_properties` | Predict ADME (and toxicity - filter out) |

**Absorption metrics:**
- Intestinal absorption
- Caco-2 permeability
- P-gp substrate/inhibitor

**Distribution metrics:**
- BBB penetration
- Plasma protein binding
- Volume of distribution

**Metabolism metrics:**
- CYP450 substrates (1A2, 2C9, 2C19, 2D6, 3A4)
- CYP450 inhibitors

**Excretion metrics:**
- Renal clearance
- Half-life

### Structural Analysis

| Tool | Purpose |
|------|---------|
| `PubChem:analyze_molecular_complexity` | Synthetic accessibility, Fsp3, stereocenters |
| `PubChem:get_3d_conformers` | 3D conformer data |
| `PubChem:analyze_stereochemistry` | Chirality and isomer information |
| `PubChem:get_pharmacophore_features` | Pharmacophore features and binding site info |

### Structure Searching (for SAR)

| Tool | Purpose |
|------|---------|
| `PubChem:search_similar_compounds` | Tanimoto similarity search |
| `PubChem:substructure_search` | Find compounds with substructure |
| `PubChem:superstructure_search` | Find larger containing structures |

---

## Interpretation Guidelines

### Synthetic Accessibility Score
| Score | Interpretation |
|-------|----------------|
| 1-3 | Easy to synthesize |
| 4-6 | Moderate difficulty |
| 7-10 | Difficult to synthesize |

### Fraction sp3 (Fsp3)
| Value | Interpretation |
|-------|----------------|
| < 0.25 | Flat, aromatic-heavy |
| 0.25-0.50 | Moderate 3D character |
| > 0.50 | Good 3D character (preferred) |

### BBB Penetration
- **Yes**: Potential CNS drug candidate
- **No**: Suitable for peripheral targets

---

## URL Format

- **PubChem Compound**: `https://pubchem.ncbi.nlm.nih.gov/compound/{CID}`
