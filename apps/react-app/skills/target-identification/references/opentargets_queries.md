# Open Targets GraphQL Queries

## Disease with Associated Targets Query

Use this query to retrieve disease information and associated targets in a single call.

```graphql
query DiseaseTargets($efoId: String!, $page: Pagination!) {
  disease(efoId: $efoId) {
    id
    name
    description
    therapeuticAreas {
      id
      name
    }
    associatedTargets(
      page: $page
      orderByScore: "score desc"
    ) {
      count
      rows {
        score
        target {
          id
          approvedSymbol
          approvedName
          biotype
          tractability {
            modality
            value
          }
          safetyLiabilities {
            event
            datasource
          }
        }
        datatypeScores {
          id
          score
        }
      }
    }
  }
}
```

**Variables:**
```json
{
  "efoId": "EFO_0000305",
  "page": { "index": 0, "size": 25 }
}
```

## Target Known Drugs Query

Use this query to get clinical precedence information for specific targets.

```graphql
query TargetDrugs($ensemblId: String!, $efoId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    knownDrugs(size: 10) {
      uniqueDrugs
      rows {
        drugId
        prefName
        drugType
        mechanismOfAction
        phase
        status
        diseaseId
      }
    }
  }
}
```

**Variables:**
```json
{
  "ensemblId": "ENSG00000091831",
  "efoId": "EFO_0000305"
}
```

## Batch Target Drugs Query

For efficiency, use batch query to get known drugs for multiple targets at once.

```graphql
query TargetKnownDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    knownDrugs(size: 5) {
      uniqueDrugs
      rows {
        drugId
        prefName
        phase
        status
        mechanismOfAction
      }
    }
  }
}
```

Use with `Open Targets:batch_query_open_targets_graphql`:
```json
{
  "query_string": "<query above>",
  "variables_list": [
    {"ensemblId": "ENSG00000091831"},
    {"ensemblId": "ENSG00000141736"},
    ...
  ],
  "key_field": "ensemblId"
}
```

## Interpreting Results

### Association Score
- Range: 0-1
- Higher = stronger evidence linking target to disease
- Aggregates genetic, somatic, literature, and other evidence types

### Tractability
- `modality: "SM"` with `value: true` = Small molecule tractable
- `modality: "AB"` with `value: true` = Antibody tractable
- `modality: "PR"` with `value: true` = PROTAC tractable

### Clinical Phase
- Phase 4 = Approved drug
- Phase 3 = Late-stage trials
- Phase 2 = Mid-stage trials
- Phase 1 = Early trials
- Phase 0.5 = Phase I (Early)

### Datatype Scores
Useful for understanding evidence composition:
- `genetic_association` — GWAS, rare variant studies
- `somatic_mutation` — Cancer genomics
- `known_drug` — Existing drug-target relationships
- `affected_pathway` — Pathway involvement
- `literature` — Text mining
