# Output Formats

Exact output templates for each analysis mode. Use these verbatim.

---

## Mode 1 — Per-meeting analysis

### Step 1: Classify meeting type

One of:

| Type | Description |
|---|---|
| **Customer-Discovery** | First to mid-funnel commercial conversation with a prospect |
| **Customer-Deepening** | Later-stage with an engaged prospect moving toward design partnership |
| **Customer-Delivery** | Working session with an active design partner on actual usage |
| **Investor** | Fundraising or learning-mode investor conversation |
| **Advisor/Mentor** | Founder-advisor conversation, ecosystem connector, board-track figure |
| **Technical** | Eytan-led deep-dive with counterparty engineering, demo, or integration |
| **Partnership** | Ecosystem partner, connector, or integration partner |
| **Internal-Monetera** | Yarden + Eytan, or Monetera team only |
| **Other** | Doesn't fit above — classify and explain |

State classification + one-line evidence.

### Step 2: Select lens by type

| Meeting type | Signal Read focuses on |
|---|---|
| Customer-Discovery | Seriousness verdict (Theater / Thin / Operator) + buying intent vs. extraction pattern |
| Customer-Deepening | Progress delta vs. last call against design-partnership criteria + commercial signal delta |
| Customer-Delivery | Delivery against committed proof + usage signals + stretch asks that surfaced |
| Investor | What updated our prior about this investor + what they tested Monetera on + commitments / referrals / data asks + whether Yarden stayed in learning mode |
| Advisor/Mentor | Quality and specificity of advice + introductions offered + follow-through asks on Yarden |
| Technical | Depth of counterparty engagement + blockers or feasibility surfaces + whether an engineering DRI was named |
| Partnership | Alignment of mutual incentives + realistic delivery capacity + trap flags |
| Internal-Monetera | Decision hygiene (decisions actually made or deferred?) + Yarden-Eytan dynamics + commitments made with owner + date + metric |
| Other | Apply judgment; state the lens explicitly |

### Step 3: Output template

```
MEETING TYPE: [type] — [one-line evidence]

ESCALATION: [only if triggered per analytical-persona escalation list; otherwise omit entirely]

BLUF (≤5 lines)

SIGNAL READ
[Type-appropriate classification and analysis with evidence quotes. See lens table above.]

JOSHUA'S BIGGEST MISS + DRILL
One miss, timestamp-anchored, with a specific drill for the next call. Add up to two more only if genuinely present. If the call was clean on Yarden's side, say so — do not manufacture failures.
For Internal-Monetera meetings: if Yarden and Eytan were aligned and crisp, note that; otherwise surface the dynamic.

NEXT ACTION
One action. Owner. Absolute date (Asia/Jerusalem). Success criterion.

VISUAL REVIEW CANDIDATES
Up to 3 timestamps where visual inspection would meaningfully sharpen an inference.
Each candidate: [MM:SS] — [specific question about observable behavior, not emotion]
Good: "03:47 — is Yarden physically leaning in or back when he concedes on scope?"
Good: "21:12 — who initiates the turn-taking when Matthew stops speaking; is there a visible pause?"
Bad: "03:47 — did Matthew seem frustrated?" (emotion inference; refuse this framing)
If no visual review warranted: "None. Transcript is sufficient."
```

---

## Mode 2 — Cross-meeting synthesis

Triggered by queries spanning multiple analyses or transcripts.

```
BLUF (≤5 lines)

PATTERN
One paragraph naming the pattern clearly.

EVIDENCE TIMELINE
| Meeting | Date | Quote (speaker) | What it shows |
|---|---|---|---|

CONTRADICTIONS
Evidence that cuts against the pattern. If none: "No contradicting evidence found in the corpus."

INFERENCE
Your interpretation, labeled as inference. Distinguish what the pattern shows from what it might mean.

RECOMMENDATION
One action. Owner. Absolute date. Success criterion.
```

---

## Mode 3 — Self-coaching

Triggered by "coach me" or similar.

```
BLUF (≤5 lines)

TOP 3 RECURRING FAILURE MODES
For each:
  Pattern: [one-line]
  Evidence: [2-3 quotes from different meetings, with source and date]
  Drill: [specific practice for the next meeting]

PROGRESS CHECK (only if prior Mode 3 output is provided as input)
For each drill from last month: evidence the behavior changed, or evidence it didn't.
```

Bias toward Yarden's stated growth edges (see monetera-context.md). Praise only when calibration-useful.

---

## Mode 5 — Visual observation (internal, called by scripts)

The `scripts/analyze_slices.py` script uses this format. You rarely invoke it directly, but when integrating its output into reports, preserve the observation-only discipline:

```
SLICE: <filename>
QUESTION: <the question asked>

OBSERVATIONS
- [MM:SS within clip] — <specific observable behavior>
- ...

DIRECT ANSWER TO QUESTION
<Answer strictly from observations above.>
```

**Prohibited framings in visual analysis:**
- Emotional state ("frustrated," "engaged," "bored," "interested")
- Intent ("seemed to want," "appeared convinced")
- Truthfulness or sincerity
- Rapport quality
- Confidence in what someone is thinking or feeling
