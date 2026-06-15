# Meeting Intelligence

A personal meeting-intelligence system for Yarden Even (CEO, Monetera). Turns recorded business meetings — customer calls, investor conversations, partner meetings — into decision-grade written analyses, not note-taker summaries. Applies a rigorous set of diagnostic frameworks to every transcript, optionally runs visual behavior analysis on flagged moments, and iterates each report through conversation.

The analytical discipline is the product. The scripts are infrastructure.

## Three-layer architecture

```
meeting-intelligence/
├── prompts/        # Layer 1 — analytical persona + domain context + output formats
├── src/            # Layer 2 — services (slice / transcribe / analyze) + `mi` CLI
│                   #   services/  (pure logic, reusable by CLI and future API)
│                   #   cli/       (Typer commands wrapping the services)
│                   #   config/    (Pydantic settings loading .env)
├── SKILL.md        # Layer 3 — Claude skill orchestration (one of several viable shapes)
└── plans/          # active and archived planning docs
```

- **Layer 1 — Prompts.** The three files in `prompts/` define the analyst: its Truth Protocol, what it knows about Monetera (accounts, priors, commitments), and the exact output templates for each analysis mode. Loaded as system prompt or equivalent. Core value; everything else is optional.
- **Layer 2 — Scripts.** `slice.py` cuts a video into 60-second chunks. `transcribe.py` sends audio to AssemblyAI with speaker diarization. `analyze_slices.py` runs Gemini on flagged slices under an observation-only prompt (no emotion inference). Each does one thing.
- **Layer 3 — Orchestration.** A Claude skill (this repo) that auto-triggers on meeting-related queries and walks the 6-step workflow. Alternative shapes — plain CLI, Claude Code project with CLAUDE.md, scheduled runner — all work. Pick what fits.

Per-meeting outputs live in `~/Google Drive/My Drive/Monetera/Meetings/<meeting-stem>/` (video, `slices/`, `transcript.md`, `candidates.json`, `visual_analysis.md`, `report_vN.md`, `conversation_log.md`). Versioned reports are never overwritten — the progression traces how understanding shifts.

## Install as a Claude skill

```
ln -s "$(pwd)" ~/.claude/skills/meeting-intelligence
```

Open Claude Code anywhere. Say something meeting-related — "analyze the latest meeting", "what's the status of FalconX", "coach me on my last three calls" — the skill auto-triggers from the phrasing and walks the 6-step workflow in `SKILL.md`.

Verify the install: ask "what principles are you operating under?" — the response should cite the Truth Protocol from `prompts/analytical-persona.md`.

## Use Layer 1 standalone (no install)

For iterating on the prompts themselves or running analysis from Claude.ai:

1. Open a fresh Claude.ai chat.
2. Paste the contents of `prompts/analytical-persona.md`, `prompts/monetera-context.md`, and `prompts/output-formats.md` as context.
3. Paste a transcript.
4. Ask for Mode 1 analysis.

No scripts, no skill install, no API keys required. The brief's Week 1 loop for validating analytical quality.

## Setup for Layer 2 (scripts)

```
brew install ffmpeg
uv pip install -e .                    # installs the `mi` command
cp .env.example .env                   # then fill in ASSEMBLYAI_API_KEY and GEMINI_API_KEY
```

## CLI

The `mi` command exposes three verbs. Each writes its output alongside the input.

| Command                           | Purpose                                                                 |
|-----------------------------------|-------------------------------------------------------------------------|
| `mi slice <video>`                | Slice video into 60-second chunks → `<video_parent>/slices/`            |
| `mi transcribe <video>`           | Transcribe via AssemblyAI with diarization → `<video_parent>/transcript.md` |
| `mi analyze <meeting-folder>`     | Gemini visual analysis on `candidates.json` → `<folder>/visual_analysis.md` |

`mi --help` and `mi <cmd> --help` for options. All three are thin CLI wrappers over `src/services/` — a future API layer imports the same functions.

## Cost envelope (per 1-hour meeting)

| Component                              | Cost          |
|----------------------------------------|---------------|
| Slicing (local ffmpeg)                 | $0            |
| AssemblyAI transcription               | ~$0.37        |
| Claude Mode 1 analysis                 | $0.50 – $1.50 |
| Gemini visual (2 candidates avg)       | $0.20 – $0.60 |
| Conversation rounds (3 typical)        | $0.60 – $1.50 |
| **Total per meeting**                  | **$1.70 – $4.00** |

At 20 meetings/month: roughly $35–$80.

## What's next

Active and archived plans live in `plans/`. Next candidates (not yet started): a Drive watcher that runs prep (slice + transcribe) automatically when a new video appears; a plain-CLI orchestrator for non-Claude-Code invocation; Hebrew-transcription routing via Gemini 2.5 for Hebrew-heavy calls.
