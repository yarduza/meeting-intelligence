# `mi` Runbook

Operational reference for the meeting-intelligence pipeline. The persona / analytical framing lives in `prompts/` and `SKILL.md` — this file is the command-level companion. Read top-to-bottom on a new machine; jump straight to a section when something misbehaves mid-run.

Per-meeting folders live at `~/Google Drive/My Drive/Meetings/<meeting-stem>/` and the source video is `<meeting-stem>.mp4` inside it.

---

## 1. TL;DR — happy path in five commands

For a meeting at `~/Google Drive/My Drive/Meetings/Romi-13-05-2026/Romi-13-05-2026.mp4`:

```bash
cd ~/Development/Monetera/meeting-intelligence
VID="$HOME/Google Drive/My Drive/Meetings/Romi-13-05-2026/Romi-13-05-2026.mp4"
DIR="$(dirname "$VID")"

uv run mi slice "$VID"                                                # → DIR/slices/
uv run mi transcribe "$VID"                                           # → DIR/transcript_assemblyai_<ts>.md
# … edit transcript header (account, participants, objective) …
# … write DIR/candidates.json (see §7) …
uv run mi analyze "$DIR"                                              # → DIR/visual_analysis.md
```

That's the AssemblyAI default. Substitute the transcribe line with `--provider gemini` or `--provider whisper` per §2/§3.

---

## 2. Choose a provider

Three transcription providers. All write `transcript_<provider>_<YYYYMMDD-HHMMSS>.md` next to the video — multiple runs coexist.

| Provider | Cost (1h) | Speed | Diarization quality | When to reach for it |
|---|---|---|---|---|
| `assemblyai` | ~$0.37 | seconds | OK; weak when speakers share acoustics | Default. English meetings, clean audio, you trust the speaker count. |
| `gemini` | ~$0.20–0.60 | 1–3 min | Strong on language context | AssemblyAI merged speakers; Hebrew-heavy calls; want a second opinion. |
| `whisper` | $0 | **2–5× realtime on CPU** | **Strongest** (pyannote 3.1) | Best diarization, sensitive audio you don't want leaving the machine, accuracy > runtime. |

Cost figures come from `README.md:67-78` (per-meeting envelope at standard pricing). `whisper` is currently the strongest stack — covered in depth in §3.

Set the default for a session with `DEFAULT_TRANSCRIPTION_PROVIDER=whisper` in `.env` or override per-run with `--provider`.

---

## 3. Whisper + pyannote — the strongest stack

`whisperx` glues OpenAI Whisper (ASR) to pyannote.audio 3.1 (diarization). Local, no API cost, best speaker separation. The cost is wall-clock: `faster-whisper` (CTranslate2) doesn't support MPS, so the code pins `device="cpu"` and `compute_type="int8"` (`src/services/transcription.py:307-308`). A 70-minute meeting takes 2h20m–5h50m on Apple Silicon — plan around that.

**Why `int8`, not `fp16`?** `int8` is integer quantization of the model weights — same architecture, weights stored as 8-bit ints instead of 16/32-bit floats. On CPU it's the only practical choice: `fp16` is software-emulated on CPU (extremely slow) and `fp32` doubles memory + halves throughput vs `int8`. Accuracy loss for `large-v3` at `int8` is small enough that it doesn't show up in normal transcripts.

### One-time setup

```bash
uv pip install whisperx torch
```

Then accept terms on Hugging Face for both pyannote models — clicking through the "Agree" buttons on:

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

Create an HF access token (Settings → Access Tokens, "read" scope is enough) and put it in `.env`:

```bash
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Without both terms-acceptance + a valid token, the diarization step throws a 401 from HF and the whole run fails.

### Running

```bash
uv run mi transcribe "$VID" --provider whisper --whisper-model large-v3
```

`large-v3` is the strongest model and also the CLI default (`src/cli/transcribe_cmd.py:44-51`). Passing it explicitly is just for clarity in logs.

Long runs: background it and tail the log so you don't tie up the terminal:

```bash
mkdir -p /tmp/mi-logs
LOG=/tmp/mi-logs/whisper-$(basename "$VID" .mp4)-$(date +%Y%m%d-%H%M%S).log
nohup uv run mi transcribe "$VID" --provider whisper --whisper-model large-v3 > "$LOG" 2>&1 &
echo "PID=$! log=$LOG"
tail -f "$LOG"
```

### Model size vs. quality vs. time

| Model | Quality | Speed (CPU, M-series) | Use when |
|---|---|---|---|
| `tiny` / `base` / `small` | Poor → fair | Fast | Sanity check the pipeline works |
| `medium` | Good | ~1.5–2× realtime | Need a result tonight and you'll accept some accuracy loss |
| `large-v2` | Strong | ~2–4× realtime | `large-v3` unavailable for some reason |
| `large-v3` **(default)** | Strongest | ~2–5× realtime | Default. Use unless you have a specific reason not to. |

### Language

Whisper auto-detects from the first ~30s of audio. For full-Hebrew meetings this is reliable — `he` is in `whisperx`'s default alignment-model list, so alignment + diarization work end-to-end. Symptoms of misdetection (rare): transcript contains Latin transliteration of Hebrew, alignment fails, or a single speaker dominates because diarization collapsed.

There is no `--language` flag on the CLI today. If misdetection actually happens, the one-line patch is in `src/services/transcription.py:312` — change `result = model.transcribe(audio, batch_size=8)` to `result = model.transcribe(audio, batch_size=8, language="he")`. Don't add it speculatively; only when you've seen the failure.

---

## 4. AssemblyAI tuning

Defaults are tuned for English with `universal-3-pro` as the primary model and `universal-2` as the Hebrew/mixed-language fallback (`src/cli/transcribe_cmd.py:52-59`).

| Flag | What it does | When to set it |
|---|---|---|
| `--speakers-expected N`, `-s N` | Tells AssemblyAI exactly how many distinct speakers to find. Gemini and Whisper ignore. | You know the count (3 people on the call). Almost always pays off. |
| `--speech-models universal-3-pro` | Disables the Hebrew fallback; uses only the strongest English model. | All-English call, you've heard the audio is clean. |
| `--speech-models universal-2` | Hebrew-only path; skips `universal-3-pro`. | Pure-Hebrew call where you don't want the English model voting at all. |
| `--normalize-audio`, `-n` | Applies ffmpeg `highpass + speechnorm + loudnorm` during audio extraction (`src/services/transcription.py:39-67`). Bumps quiet speakers past the VAD threshold. | One speaker is much quieter than another. Trade: amplifies background noise. |

---

## 5. Gemini tuning

### Why Gemini wins on merged speakers

AssemblyAI's diarizer is voice-print clustering: it slices the audio into segments, embeds each one acoustically, and clusters the embeddings. When two speakers share acoustic characteristics — same accent, similar pitch, same microphone — their embeddings land in the same cluster and AssemblyAI emits them as one "Speaker A".

Gemini's diarization comes from its native multimodal audio decoder. The same model that's producing the ASR output is also assigning speaker labels, with access to the **linguistic context** — turn-taking phrases, name references, topical shifts, code-switching between languages. So when two acoustically similar speakers say different kinds of things, Gemini can split them where AssemblyAI cannot. This is also why Gemini holds up well on Hebrew calls and on mixed-language calls (English asides inside a Hebrew meeting): language context is part of the diarization signal.

The tradeoff: Gemini is slower (1–3 min for a 1h call vs. seconds for AssemblyAI) and depends on the model emitting valid JSON in the agreed schema — the code raises if it doesn't (`src/services/transcription.py:256-262`).

### Configuration

Set `GEMINI_TRANSCRIPTION_MODEL` in `.env` — defaults to `gemini-2.5-pro`. Flash variants are cheaper if Pro is too slow or expensive for the volume you're running.

```bash
GEMINI_TRANSCRIPTION_MODEL=gemini-2.5-pro      # quality (default)
GEMINI_TRANSCRIPTION_MODEL=gemini-2.5-flash    # cost-optimized
```

No per-run CLI knobs for Gemini — the provider doesn't take a speaker count or audio-normalization param. `--normalize-audio` does still affect the audio extraction step that feeds Gemini, so you can use it here too.

---

## 6. Tuning fault tree

Bad output? Walk this top-to-bottom; don't shop the menu.

1. **All speakers merged into one label** — Re-run with `--provider gemini`. If still merged, escalate to `--provider whisper`. The merging usually means AssemblyAI's diarizer couldn't separate acoustically-similar voices.
2. **Three+ real speakers, transcript shows two** — Add `--speakers-expected 3` (AssemblyAI). Often fixes it without changing providers.
3. **A specific speaker is missing or has near-empty utterances** — Add `--normalize-audio`. They were below the VAD threshold.
4. **Whisper produced Latin transliteration of Hebrew text** — Language misdetection. Apply the one-line patch in §3 (Language) and re-run. Don't add it speculatively before you see this.
5. **Whisper is taking too long / will miss a deadline** — Drop to `--whisper-model medium`, or switch to `--provider gemini`. Don't drop below `medium` for production transcripts.
6. **You're not sure which provider is best for this account** — Run `mi compare` (§9). The cost estimate + comparison summary settles it.

---

## 7. Slicing

```bash
uv run mi slice "$VID"
```

Defaults: 60-second chunks (`src/cli/slice_cmd.py:14-17`), H.264 with `videotoolbox` hardware acceleration, AAC audio (`src/services/slicing.py:58-65`). Output is `<DIR>/slices/slice_NNN.mp4` + `_manifest.json`.

The naming convention is invariant: **slice N covers minute N**. `slice_003.mp4` = 03:00–03:59. To analyze moment `MM:SS`, use `slice_{MM}.mp4` zero-padded to 3 digits.

`mi slice` is idempotent (`src/services/slicing.py:46-49`) — if any `slice_*.mp4` exists in `slices/`, it returns the existing manifest. Safe to re-run, won't double-encode.

Override slice length with `--slice-seconds N` if you want non-60s chunks. Don't change it casually — every downstream piece (`candidates.json`, `mi analyze`) assumes 1 slice = 1 minute.

---

## 8. Visual review candidates

`candidates.json` is how you queue minutes for Gemini visual analysis. Strict schema (`src/services/visual_analysis.py:109-145`):

```json
{
  "meeting_stem": "Romi-13-05-2026",
  "candidates": [
    {
      "timestamp": "03:47",
      "slice_index": 3,
      "question": "is Yarden physically leaning in or back when he concedes on scope?",
      "status": "pending"
    },
    {
      "timestamp": "21:12",
      "slice_index": 21,
      "question": "who initiates turn-taking when Romi stops speaking; is there a visible pause?",
      "status": "pending"
    }
  ]
}
```

Field rules:

- `slice_index` — integer minute, must match the slice file (`slice_003.mp4` → `3`). Floor of the minute, not the second.
- `status` — `"pending"` initially. `mi analyze` updates to `"processed"` or `"error"` in place and adds `processed_at` / `error` fields.
- `meeting_stem` — used for the `visual_analysis.md` title header. Optional; falls back to the folder name.

### Questions that work vs. don't

The Gemini system prompt (`src/services/visual_analysis.py:22-32`) explicitly refuses emotional framings. Write **observable-behavior questions** or the model will reject the framing and answer something adjacent.

| Good | Bad (will be refused) |
|---|---|
| "is Yarden physically leaning in or back when he concedes on scope?" | "did Yarden look uncertain when he conceded?" |
| "who initiates turn-taking when Romi stops speaking?" | "did Romi feel disengaged at 21:12?" |
| "where is Yarden's gaze in the 5 seconds after Romi's question?" | "was there good rapport in this minute?" |
| "describe gesture patterns during the price discussion at 34:00–34:59" | "did the customer seem hesitant about price?" |

Rule of thumb: if a sighted person watching with sound off could answer it from observation alone, it's a valid question.

Always write `candidates.json` — even with an empty `candidates: []` array. Its presence signals the analysis step completed (`SKILL.md:103`).

---

## 9. `mi analyze` (Gemini visual pass)

```bash
uv run mi analyze "$DIR"
```

Reads `candidates.json`, processes every entry where `status == "pending"`, writes `visual_analysis.md` to the folder, and updates `candidates.json` in place. If `visual_analysis.md` already exists, it's renamed to `visual_analysis_<ts>.md.bak` before the new one is written (`src/services/visual_analysis.py:147-149`) — so you never lose a prior pass.

Behavior:

- **Model**: from `GEMINI_MODEL` (default `gemini-2.5-pro`). Distinct from `GEMINI_TRANSCRIPTION_MODEL`.
- **Retries**: hardcoded `10s, 30s, 90s` delays for 429/500/502/503/504 (`src/services/visual_analysis.py:18-19`). Not configurable today.
- **Missing slice**: if `slices/slice_NNN.mp4` doesn't exist for a candidate, the entry is marked `error` with "Slice file missing" in the markdown — the batch continues.
- **Sequential**: one Gemini call at a time, one candidate at a time. No parallel batching.
- **Re-runnable**: add more candidates with `status: "pending"` and re-run. Existing `processed` entries are skipped.

Final status (printed to stdout): `N processed, M errors, K missing slices`.

---

## 10. Comparison and summarize

Two utilities for picking the right provider.

### `mi compare` — run providers in parallel

```bash
uv run mi compare "$VID"                                  # all three providers
uv run mi compare "$VID" --providers gemini,whisper       # subset
uv run mi compare "$VID" -s 3 -n -y                       # speakers=3, normalize audio, skip confirm
```

Behavior (`src/cli/compare_cmd.py:20-49`): shows a per-provider cost estimate up front, prompts to confirm (unless `-y`), runs everything in parallel where possible, prints a results table, writes a comparison summary file. Providers missing credentials are skipped silently, not treated as errors.

**What "parallel where possible" actually means.** AssemblyAI and Gemini are I/O-bound (network calls + remote inference), so they run concurrently with little contention. Whisper is CPU-bound and pinned to `device="cpu"` — it consumes the local cores the moment it starts. So in a three-way compare, AssemblyAI and Gemini finish quickly while Whisper still has hours to run, and Whisper's wall-clock is roughly the same as if it had run alone. Don't expect a 3× speedup; expect "the others finish during the Whisper run."

Use this when onboarding a new account / language / audio profile and you don't know which provider will win.

### `mi summarize` — free post-hoc compare

```bash
uv run mi summarize "$DIR"
```

If you already ran multiple providers on the same video, this is free (`src/cli/summarize_cmd.py:18-20`): parses every `transcript_*.md` in `$DIR` and writes `transcript_comparison_<ts>.md` with per-provider speaker counts, longest utterance per speaker, and a suspicious-gap scan. No re-transcription. Use it to pick the winner after the fact.

---

## 11. Environment & install

### One-time install

```bash
brew install ffmpeg
uv pip install -e .
cp .env.example .env
# … fill in API keys …
```

Whisper extras (only if using `--provider whisper`):

```bash
uv pip install whisperx torch
# … accept HF pyannote terms (see §3) and set HF_TOKEN in .env …
```

### Env vars

Loaded from `.env` via `src/config/settings.py`. Pydantic settings; unknown keys ignored.

| Var | Default | Purpose |
|---|---|---|
| `ASSEMBLYAI_API_KEY` | — | AssemblyAI auth. Required for `--provider assemblyai`. |
| `GEMINI_API_KEY` | — | Gemini auth. Required for `--provider gemini` and `mi analyze`. |
| `GEMINI_MODEL` | `gemini-2.5-pro` | Visual analysis model (`mi analyze`). |
| `GEMINI_TRANSCRIPTION_MODEL` | `gemini-2.5-pro` | Gemini transcription model. Set Flash variant here for cost. |
| `HF_TOKEN` | — | HuggingFace token. Required for `--provider whisper` (pyannote download + license check). |
| `DEFAULT_TRANSCRIPTION_PROVIDER` | `assemblyai` | Provider used when `--provider` is omitted. |

`--help` reaches the source of truth:

```bash
uv run mi transcribe --help
uv run mi slice --help
uv run mi analyze --help
uv run mi compare --help
uv run mi summarize --help
```

---

## 12. Troubleshooting — recognize the error, then act

What the error literally looks like in the terminal, what it means, and the fix. Top-down by frequency.

### Whisper / pyannote

**`401 Client Error: Unauthorized for url: https://huggingface.co/pyannote/...`**
Either you didn't accept the model terms (click "Agree" on both pyannote pages — see §3) or `HF_TOKEN` is empty/invalid. Accepting terms is per-account, per-model, one-time. Test the token in isolation:
```bash
curl -H "Authorization: Bearer $HF_TOKEN" https://huggingface.co/api/whoami-v2
```

**`ValueError: HuggingFace token is required for the whisper provider`**
`HF_TOKEN` missing from `.env`. See §3.

**`RuntimeError: whisper provider requires whisperx and torch`**
You haven't installed the optional deps. `uv pip install whisperx torch`.

**`AttributeError: module 'torchaudio' has no attribute 'list_audio_backends'`**
torchaudio ≥ 2.3 removed that API; whisperx still calls it. The code patches this at `src/services/transcription.py:295-296`, so if you're seeing this raw, the patch didn't run — most likely you're invoking whisperx outside the `mi transcribe` path.

**`ValueError: No default align-model for language 'XX'`**
Whisper auto-detected a language that `whisperx` has no alignment model for. For Hebrew this should never happen (`he` is supported). If it does, force-language patch (§3, Language) or re-run with `--provider gemini`.

### AssemblyAI

**`Authentication error` / `401`**
`ASSEMBLYAI_API_KEY` empty or revoked. Regenerate at app.assemblyai.com.

**`Insufficient credits`**
Top up the account or switch to `--provider whisper` (no API cost).

### Gemini (transcription and `mi analyze`)

**`RuntimeError: Gemini returned non-JSON output: ...`**
The Gemini transcription path requires a strict JSON schema; the model occasionally drifts. Re-run — it's usually transient. If it persists, switch model: `GEMINI_TRANSCRIPTION_MODEL=gemini-2.5-flash` (or back to Pro if you were on Flash).

**`RuntimeError: Gemini output schema mismatch`**
Same family — JSON parsed but missing required fields. Re-run.

**`429 RESOURCE_EXHAUSTED` (during `mi analyze`)**
The retry loop handles this automatically (10s, 30s, 90s — `src/services/visual_analysis.py:18-19`). If all three retries fail you'll see `Gemini retry loop exhausted` — wait a few minutes and re-run; pending candidates pick up where they left off.

**`Gemini API key is required`**
`GEMINI_API_KEY` empty. Required for both `--provider gemini` and `mi analyze`.

### Slicing / files

**`FileNotFoundError: ffmpeg`**
`brew install ffmpeg`. Check PATH afterwards — `which ffmpeg` should show `/opt/homebrew/bin/ffmpeg` on Apple Silicon.

**`FileNotFoundError: Video not found: <path>`**
Either path typo or the file hasn't finished syncing from Drive. Per `SKILL.md:175` — wait 30s and re-check before concluding it's missing.

**`FileNotFoundError: No candidates.json in <folder>`**
You haven't created it yet. See §8 for the schema. Always create it, even with `"candidates": []`.

**`FileNotFoundError: No slices/ in <folder>`**
You skipped `mi slice`. Run it first.

**`Slice file missing: slice_NNN.mp4` (inside `visual_analysis.md`)**
`candidates.json` references a slice index past the meeting length. Either fix the `slice_index` in `candidates.json` or extend the slicing (rerun `mi slice` with a longer source — though this usually means a typo in the candidate).

### Background processes

If you launched a long Whisper run with `nohup ... &` (§3), the process ID was echoed back. To check status, watch logs, or kill it:

```bash
ps -p <PID>                    # is it still running?
tail -f /tmp/mi-logs/<file>    # follow the log
kill <PID>                     # graceful stop; -9 if needed
pgrep -af "mi transcribe"      # find all running mi transcribe jobs
```

If the Mac sleeps, the background process pauses; lid open + power connected is the safest configuration for multi-hour runs.

---

## 13. End-to-end worked example (Romi-13-05-2026, Hebrew)

This is the full pipeline applied to a real meeting. Substitute your stem.

```bash
cd ~/Development/Monetera/meeting-intelligence

STEM="Romi-13-05-2026"
DIR="$HOME/Google Drive/My Drive/Meetings/$STEM"
VID="$DIR/$STEM.mp4"

# 1. Slice (idempotent — safe to re-run)
uv run mi slice "$VID"

# 2. Transcribe with Whisper + pyannote, large-v3
mkdir -p /tmp/mi-logs
LOG=/tmp/mi-logs/$STEM-whisper-$(date +%Y%m%d-%H%M%S).log
nohup uv run mi transcribe "$VID" --provider whisper --whisper-model large-v3 > "$LOG" 2>&1 &
echo "PID=$! log=$LOG"
tail -f "$LOG"   # ^C when done; transcript is in $DIR

# 3. Open the transcript, fill in the metadata header:
#    - Account / counterparty: Gems (Omri Hanover et al.)
#    - Date: 2026-05-13
#    - Meeting number in relationship: (look up in conversation_log.md if present)
#    - Participants → speaker labels: Speaker A = Yarden, Speaker B = Romi, etc.
#    - Yarden's objective going into the meeting

# 4. Read the transcript, draft candidates.json.
#    Pick 2–4 minutes where something behavioral matters — body, gaze, gesture, turn-taking.
#    Skip emotional framings (§8). Two minutes is usually enough; more is rarely better.
cat > "$DIR/candidates.json" <<'JSON'
{
  "meeting_stem": "Romi-13-05-2026",
  "candidates": [
    {
      "timestamp": "12:30",
      "slice_index": 12,
      "question": "is Yarden leaning forward or back when he names the price for the first time, and where is his gaze in the 5 seconds after?",
      "status": "pending"
    },
    {
      "timestamp": "34:15",
      "slice_index": 34,
      "question": "when Romi raises the integration concern, who initiates turn-taking after she stops speaking, and how long is the pause?",
      "status": "pending"
    },
    {
      "timestamp": "58:05",
      "slice_index": 58,
      "question": "describe Yarden's gesture patterns during the close — hand position, frequency, where his eyes land between sentences.",
      "status": "pending"
    }
  ]
}
JSON

# 5. Gemini visual pass — sequential, ~30s–2min per candidate.
uv run mi analyze "$DIR"
# → $DIR/visual_analysis.md (and candidates.json updated in place)
```

The candidates above are illustrative of the schema and the question style; substitute timestamps/questions that actually matter for this meeting. Three candidates is the common count: one for the moment of commitment (price, scope, ask), one for the moment of pushback (objection, concern), one for the close.

Then the Mode 1 / Mode 2 analytical work proceeds per `SKILL.md` and `prompts/output-formats.md` — outside the scope of this runbook.

---

## Pointer back

`SKILL.md` orchestrates the analytical workflow (which provider, which mode, when to escalate). This runbook is the deeper command reference it points to. If a section here drifts from the source code, the code wins — open the `cli/*_cmd.py` or `services/*.py` file cited inline and update this file accordingly.
