// Workflow registry — single source of truth for the sidebar's "Guided
// workflows" radio list AND the chat panel's canned-prompt templates. The
// order in this array is the order shown in the sidebar.
//
// Each workflow has:
//   name              unique key (matches the `skills/<name>/` folder if a
//                     matching SKILL.md exists, in which case the "Skills"
//                     checkbox can enrich the prompt with the SKILL.md body)
//   label             display name shown in the sidebar radio
//   caption           short tooltip text shown on hover
//   canned_prompt     prompt template with ${workflowInput} (and optionally
//                     ${compoundProps}) tokens that get substituted on submit
//   input_placeholder placeholder text for the workflow's input field
//   variant           optional: 'adme' for the multi-pill ADME panel,
//                     otherwise the default single-input + Enter layout

export const WORKFLOWS = [
  {
    name: 'target-identification',
    label: 'Target Identification',
    caption: 'Based on a disease, identify therapeutic targets',
    canned_prompt:
      'Use OpenTargets to find targets associated with ${workflowInput}. Show their scores if any and rank in descending order of scores.',
    input_placeholder: "your input, e.g., breast cancer, Alzheimer's disease",
  },
  {
    name: 'hit-identification',
    label: 'Hit Identification',
    caption: 'Based on a target, get its associated drugs',
    canned_prompt:
      'Use OpenTargets to find drugs associated with ${workflowInput}. Show their scores if any and rank in descending order of scores.',
    input_placeholder: 'your input, e.g., BRCA1, GLP-1',
  },
  {
    name: 'ADME-assessment',
    label: 'ADME Assessment',
    caption: 'Based on a compound, get its ADME and other properties',
    canned_prompt:
      'Use PubChem to get ${compoundProps} properties of ${workflowInput}.',
    input_placeholder: 'your input, e.g., acetaminophen, semaglutide, CHEMBL25',
    variant: 'adme',
  },
  {
    name: 'safety-assessment',
    label: 'Safety Assessment',
    caption: 'Based on a compound, get its safety info',
    canned_prompt:
      'Use PubMed to find the safety profile of ${workflowInput}. If citing studies, please state the strength of the evidence based on the study design.',
    input_placeholder: 'your input, e.g., orforglipron, semaglutide',
  },
  {
    name: 'indication-expansion',
    label: 'Indication Expansion',
    caption: 'Find potential new indications for a drug',
    canned_prompt:
      'What are potential indications of ${workflowInput}? Consider supporting evidence from OpenTargets, clinical trials, and the literature.',
    input_placeholder: 'your input, e.g., semaglutide, vemurafenib',
  },
  {
    name: 'coverage-analysis',
    label: 'Coverage Analysis',
    caption: 'Get current Medicare coverage for a drug or service',
    canned_prompt:
      'Get the current Medicare coverage for ${workflowInput}.',
    input_placeholder: 'your input, e.g., semaglutide, vemurafenib',
  },
  {
    name: 'market-sizing',
    label: 'Market Sizing',
    caption: 'Estimate the market opportunity for a drug',
    canned_prompt:
      'Size the market oppportunities for ${workflowInput}. Consider potential indications, coverage, eligible patient demographics, and competitor landscape.',
    input_placeholder: 'your input, e.g., semaglutide, vemurafenib',
  },
]

export const WORKFLOWS_BY_NAME = Object.fromEntries(
  WORKFLOWS.map(w => [w.name, w])
)

// Display strings for the unfilled placeholder slots in the prompt preview.
export const PLACEHOLDER_LABELS = {
  workflowInput: '___your_input___',
  compoundProps: '___your_properties___',
}
