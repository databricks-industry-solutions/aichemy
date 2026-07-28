---
name: create-docx-report
description: Create a Databricks-branded Word (.docx) report from findings. Use when the user asks for a Word/DOCX download, branded report, executive summary document, or to package conversation results into a formal handout. Triggers include "export as Word", "create a docx", "download a report", "create .docx report", or "package this as a document". Uses the create_docx tool and applies Databricks–inspired formatting (vivid red accents, clean white space, professional tables).
---

# Create .docx Report Skill

Produce a polished Word report via the **`create_docx`** tool. Visual styling is
**inspired by** publicly known Databricks brand cues (vivid red accent, clean
white space, professional sans-serif).

## Workflow Overview

1. **Gather content** → Use other agents/tools first if the user needs data.
2. **Structure the report** → Follow the section order and markdown conventions below.
3. **Call `create_docx`** → Pass `title`, `content` (markdown body), and `filename`.
4. **Reply with the download link** → Paste the tool’s markdown link **verbatim**.

## Step 1: When to Use This Skill

Call `create_docx` when the user wants a downloadable Word file. Do **not** dump
raw HTML or base64 into chat. Prefer this skill whenever they ask to export,
download, or formalize results as a document.

If research is still needed, finish tool/agent calls first, then export.

## Step 2: Brand-Inspired Formatting Rules

The `create_docx` tool **loads visual styling from this skill** — specifically
`references/theme.yml`. It does **not** hardcode brand colors in Python. To change colors/fonts/margins, edit
`theme.yml` (picked up on the next tool call).

Applied from this skill's theme:

| Element | Treatment |
|---------|-----------|
| Title / H1–H3 | Accent color from theme, heading font, bold |
| Title underline | Thin accent horizontal rule (if `layout.title_rule`) |
| Body text | Near-black, body font/size, configured line spacing |
| Tables | Accent header row + white bold text; alternating alt-row fill |
| Notes / captions | Muted gray, smaller type (prefix with `Note:`) |
| Margins | From `layout.margin_inches` |

When calling the tool, pass `skill_name="create-docx-report"` (or omit — that is
the default) so the correct theme is applied.

Your job is to **structure markdown** so those styles land correctly.

### Content conventions for `content`

```markdown
## Executive Summary
2–4 sentences. Lead with the decision-relevant takeaway.

## Key Findings
- Bullet one clear finding per line
- Prefer short, scannable lines over long paragraphs

## Results
| Column A | Column B | Column C |
|----------|----------|----------|
| value    | value    | value    |

## Implications
1. Numbered recommendation or next step
2. Second recommendation

---

Note: Sources and caveats go here in muted style.
```

### Do

- Use `#` only inside `content` for **section** headings (`##` / `###`). The
  document title is the separate `title` argument (do not repeat as `#` in body).
- Keep tables compact (≤ 6 columns when possible).
- Put units and confidence in the same cell (e.g. `0.42 (high)`).
- End with a short `Note:` line for data provenance / limitations.
- Choose a descriptive `filename`, e.g. `egfr_hit_summary.docx`.

### Don’t
- Don’t claim official brand-guideline compliance.
- Don’t wrap the entire report in a single giant paragraph.
- Don’t omit the download link from the final chat reply.

## Step 3: Call `create_docx`

```
create_docx(
  title="<Clear Report Title>",
  content="<markdown body per conventions above>",
  filename="<snake_or_kebab_name>.docx",
  skill_name="create-docx-report"
)
```

`skill_name` selects which skill folder's `references/theme.yml` to use.
Omit it to default to `create-docx-report`.

Example title patterns:

- `EGFR Hit Identification Summary`
- `Orforglipron Safety Literature Brief`
- `Market Opportunity Snapshot — Semaglutide`

## Step 4: Final Reply to the User

1. One short sentence confirming the report was created.
2. Include the **exact** markdown download link returned by `create_docx`.
3. Optionally list the sections included (bullets).

Do not regenerate the full report body in chat unless the user asks.

## Suggested Section Sets by Use Case

### Hit / target / compound research
1. Executive Summary  
2. Key Findings  
3. Results (table of entities, scores, phases)  
4. Supporting Evidence  
5. Next Steps  
6. Note: sources

### Safety / ADME / assessment
1. Executive Summary  
2. Assessment Snapshot (table)  
3. Risks & Flags  
4. Literature Highlights  
5. Recommendations  
6. Note: study-design caveats

### Market / coverage / commercial
1. Executive Summary  
2. Addressable Opportunity  
3. Coverage & Access  
4. Competitive Landscape (table)  
5. Implications  
6. Note: data vintage

## Voice & Tone

- Clinical-commercial clarity: precise, neutral, non-hype.
- Prefer active voice and specific numbers over vague adjectives.
- Spell out acronyms on first use in the Executive Summary.
