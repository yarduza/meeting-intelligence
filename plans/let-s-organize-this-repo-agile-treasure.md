# Organize the meeting-intelligence repo

## Context

Today the repo is a flat `meeting-intelligence-skill/` folder plus an empty root `README.md`. `SKILL.md` references `references/system-prompt.md` which doesn't exist — the real content lives in `analytical-persona.md` + `output-formats.md` — so the skill is broken on first load.

The brief (see `Focus of meeting intelligence repo.md`) clarifies the bigger frame: this is a three-layer system.

- **Layer 1** — the analytical persona + prompts. "Core value, everything else is optional."
- **Layer 2** — scripts (transcription, slicing, visual analysis). Infrastructure.
- **Layer 3** — orchestration. A Claude skill is *one of four viable shapes* (skill, Claude Code project, plain CLI, scheduler).

The current layout buries Layer 1 inside `skill/references/`, inverting the architecture. The brief's Week 1 guidance — "Layer 1 only. Three prompt files. Test in Claude.ai by pasting transcripts manually" — is awkward when prompts are two folders deep inside a skill wrapper.

This plan restructures the repo so prompts are repo-root citizens (Layer 1 first-class, easy to paste-test), scripts are repo-root citizens (Layer 2 callable by any orchestration shape), and `SKILL.md` lives at repo root as one orchestration option. The repo *is* the skill when symlinked into `~/.claude/skills/meeting-intelligence/`. Future orchestration shapes (CLI, scheduler, automation watcher) plug in as siblings.

## Target layout

```
meeting-intelligence/
├── README.md                    # system overview, three-layer framing
├── SKILL.md                     # Claude skill entry — references prompts/ and scripts/
├── requirements.txt
├── .env.example                 # ASSEMBLYAI_API_KEY / GEMINI_API_KEY / GEMINI_MODEL
├── prompts/                     # Layer 1 — core product
│   ├── analytical-persona.md
│   ├── monetera-context.md      # domain context; keep project-specific name
│   └── output-formats.md
├── scripts/                     # Layer 2 — infrastructure
│   ├── slice.py
│   ├── transcribe.py
│   └── analyze_slices.py
└── plans/
    └── let-s-organize-this-repo-agile-treasure.md   # this plan, copied in as last step
```

Install: `ln -s "$(pwd)" ~/.claude/skills/meeting-intelligence`. Non-skill files (`plans/`, `.env.example`, `.git`) live alongside but Claude Code only loads `SKILL.md` and the paths it references.

## Execution

### 1. Move prompts to repo root

```
mkdir prompts scripts
mv meeting-intelligence-skill/analytical-persona.md prompts/
mv meeting-intelligence-skill/monetera-context.md prompts/
mv meeting-intelligence-skill/output-formats.md prompts/
```

### 2. Move scripts to repo root

```
mv meeting-intelligence-skill/slice.py scripts/
mv meeting-intelligence-skill/transcribe.py scripts/
mv meeting-intelligence-skill/analyze_slices.py scripts/
```

Scripts' docstrings already assume `python scripts/slice.py ...` invocation from repo root. No code changes needed — they operate on absolute paths of videos and meeting folders, so cwd is not load-bearing (verified in [slice_video](scripts/slice.py#L31), [transcribe main](scripts/transcribe.py#L93-L133), [analyze_one_slice](scripts/analyze_slices.py#L59-L82)).

### 3. Move SKILL.md and requirements.txt to repo root

```
mv meeting-intelligence-skill/SKILL.md .
mv meeting-intelligence-skill/requirements.txt .
```

### 4. Fix SKILL.md — two content bugs

**Bug A (critical)**: `references/system-prompt.md` does not exist. The "Before you do anything else" block (currently around lines 14-17) must load three files:
1. `prompts/analytical-persona.md` — Truth Protocol, evidence discipline, non-negotiable principles
2. `prompts/monetera-context.md` — category, wedge, accounts, people, proof artifacts, diagnostic priors
3. `prompts/output-formats.md` — Mode 1/2/3/5 templates and meeting-type lenses

**Bug B (path prefix)**: every remaining occurrence of `references/` in SKILL.md becomes `prompts/`. Grep SKILL.md for `references/` to find all cases (prior inspection: Mode 1 analysis step around line 84, Mode 2 synthesis step around line 140 — confirm exact lines during execution).

### 5. Overwrite the empty root `README.md`

Sections, in order:
- **Vision** — one paragraph pulled from the brief's "What we're building" + "Core value proposition" (condensed).
- **Three-layer architecture** — the tree + one-sentence description of each layer.
- **Install as a Claude skill** — `ln -s "$(pwd)" ~/.claude/skills/meeting-intelligence` + how to verify it loads.
- **Use Layer 1 standalone** — paste `prompts/*.md` into Claude.ai, paste transcript, ask for Mode 1. (Brief's Week 1 workflow.)
- **Setup for Layer 2** — `brew install ffmpeg`, `pip install -r requirements.txt`, copy `.env.example` → `.env` and fill in keys.
- **Cost envelope** — from the brief's cost table.
- **What's next** — one-line pointer to `plans/` for future work (automation, orchestrator, etc.).

Merge in the useful setup prose from current `meeting-intelligence-skill/README.md` rather than duplicating it.

### 6. Add `.env.example`

```
# Used by scripts/transcribe.py
ASSEMBLYAI_API_KEY=

# Used by scripts/analyze_slices.py
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3-pro   # verify current at https://ai.google.dev/gemini-api/docs/models

# Note: Claude auth is handled by Claude Code / Claude.ai. Scripts never call Anthropic directly.
```

### 7. Delete stale artifacts

```
rm meeting-intelligence-skill/meeting-intelligence.skill
rm meeting-intelligence-skill/README.md
rm plans/let-s-organize-this-repo-agile-treasure.md
rmdir meeting-intelligence-skill
```

The `.skill` zip was built from the broken layout — shipping it would ship the bug. Regenerable later when we actually distribute. The skill's README content is merged into root `README.md`. The prior plan file is replaced by this one.

### 8. Copy this plan into the repo

```
cp ~/.claude/plans/let-s-organize-this-repo-agile-treasure.md plans/
```

## Critical files

| Source | Destination | Change |
|---|---|---|
| `meeting-intelligence-skill/analytical-persona.md` | `prompts/analytical-persona.md` | move |
| `meeting-intelligence-skill/monetera-context.md` | `prompts/monetera-context.md` | move |
| `meeting-intelligence-skill/output-formats.md` | `prompts/output-formats.md` | move |
| `meeting-intelligence-skill/slice.py` | `scripts/slice.py` | move |
| `meeting-intelligence-skill/transcribe.py` | `scripts/transcribe.py` | move |
| `meeting-intelligence-skill/analyze_slices.py` | `scripts/analyze_slices.py` | move |
| `meeting-intelligence-skill/SKILL.md` | `SKILL.md` | move + edit (fix `system-prompt.md` → three-file load, fix all `references/` → `prompts/`) |
| `meeting-intelligence-skill/requirements.txt` | `requirements.txt` | move |
| `meeting-intelligence-skill/README.md` | — | delete (merged into root `README.md`) |
| `meeting-intelligence-skill/meeting-intelligence.skill` | — | delete (stale bundle) |
| `meeting-intelligence-skill/` | — | rmdir (empty) |
| `README.md` | `README.md` | overwrite (empty title → system overview) |
| — | `.env.example` | create |
| `plans/let-s-organize-this-repo-agile-treasure.md` | — | overwrite with this plan |

## What we're NOT doing

- **No `automation/` folder.** Phase 2 (Drive watcher) earns its own plan. Brief: "add only what the friction demands."
- **No `orchestrator/`, no `tests/`.** Brief lists them as optional. Add when we're ready.
- **No build tooling / `.skill` regeneration.** Only matters when we distribute.
- **No `.gitignore` churn.** Add opportunistically.

## Verification

1. `ls prompts/ scripts/` — three files in each.
2. `ls` at repo root — shows `README.md`, `SKILL.md`, `requirements.txt`, `.env.example`, `prompts/`, `scripts/`, `plans/`. No `meeting-intelligence-skill/`.
3. `grep -n "references/" SKILL.md` — zero matches.
4. `grep -rn "system-prompt.md" .` — zero matches.
5. `python scripts/slice.py --help` — prints usage without import errors.
6. **Skill install + trigger test** — `ln -s "$(pwd)" ~/.claude/skills/meeting-intelligence`. Open Claude Code in repo, mention a meeting ("what's the status of FalconX"). Skill auto-triggers (detected by the frontmatter's FalconX keyword). Ask "what principles are you operating under?" — response cites Truth Protocol, confirming `prompts/analytical-persona.md` loaded through the updated SKILL.md path.
7. **Layer 1 standalone test** (per brief's Week 1) — open a fresh Claude.ai chat, paste contents of `prompts/analytical-persona.md`, `prompts/monetera-context.md`, `prompts/output-formats.md`, then paste a real transcript and ask for Mode 1 analysis. Confirms Layer 1 works without any orchestration.
