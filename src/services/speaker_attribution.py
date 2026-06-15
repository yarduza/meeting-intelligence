"""Re-attribute generic Speaker A/B/... labels in a transcript to named attendees.

The diarizer (pyannote.audio or AssemblyAI's) collapses voices that share an
acoustic path — e.g. on a single-mic recording of a remote meeting, three
remote participants all sound like "audio from the laptop speaker" and end up
under one Speaker label. This module sends the existing transcript + the
attendee roster to Gemini and asks it to re-attribute each utterance using
conversational cues (direct address, self-introduction, topic ownership,
turn-taking) instead of voice prints.

Reads:  transcript_<provider>_<ts>.md
Writes: transcript_<provider>_<ts>_attributed.md (+ attribution_log_<ts>.md
        if any utterances came back low-confidence)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.services.transcription import (
    _generate_with_retry,
    parse_transcript_file,
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


PROMPT_TEMPLATE = """You are re-attributing speaker labels in a diarized meeting transcript.

RECORDING CONTEXT
This meeting was recorded on a single microphone (Yarden Even's laptop). Yarden
spoke directly into the mic; the other participants joined remotely and were
captured second-hand through Yarden's laptop speakers. The diarizer correctly
separated Yarden from the remote audio path but COLLAPSED ALL REMOTE VOICES
into a single speaker label because they share the same acoustic path. Your job
is to split that collapsed label back into named individuals using conversational
cues only — you cannot rely on voice characteristics.

ATTENDEES (closed roster — every utterance attributes to one of these or "UNKNOWN")
{attendee_lines}

KNOWN LABEL HINTS (strong prior; override only if conversational cues clearly conflict)
{known_label_lines}

CUES TO USE
1. Direct address — "תגיד לי, ארון..." means the CURRENT speaker is not Aaron
   and the NEXT response is likely Aaron.
2. Self-introduction — "אני נדב" pins that utterance to Nadav.
3. Topic ownership — once a person's role is established (e.g. Aaron leads X),
   subsequent utterances on that topic from the collapsed label likely belong
   to them.
4. Turn-taking — short acknowledgments ("כן", "אוקיי", "נכון") after a long turn
   are usually from a different remote speaker than the one who just spoke.
5. Question→answer continuity — a question usually gets a direct response from
   a different speaker.

CONFIDENCE
- high   : two or more independent cues align unambiguously.
- medium : one strong cue or pattern-based inference (topic ownership, turn-taking).
- low    : no clear cue, or cues conflict. Use honestly — low-confidence lines
           are flagged for human review, not silently guessed.

If you cannot match a speaker to anyone in the roster, return "UNKNOWN" with
confidence "low". Never invent a name not in the roster.

OUTPUT FORMAT
Return ONLY a JSON array. No markdown fences, no prose. Each element MUST be:
  {{"start_ms": <int from input>, "speaker_name": "<name from roster or UNKNOWN>",
   "confidence": "high"|"medium"|"low"}}

Return EXACTLY {n_utterances} objects, in the same order as the input, with
start_ms values matching the input exactly. Do not merge, split, drop, or reorder.

TRANSCRIPT
{utterance_block}
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_VALID_CONFIDENCE = {"high", "medium", "low"}
_UNKNOWN_NAME = "UNKNOWN"


def _format_timestamp(ms: int) -> str:
    total_seconds = ms // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _render_utterance_block(utterances: list[dict]) -> str:
    """Emit `{start_ms=N} [MM:SS] Speaker X: text` per line.

    The inline start_ms lets the LLM echo it back, which makes round-trip
    alignment trivial and gives `_validate_response` a hard check that no
    lines were skipped or reordered.
    """
    lines = []
    for u in utterances:
        ts = _format_timestamp(u["start_ms"])
        lines.append(f"{{start_ms={u['start_ms']}}} [{ts}] Speaker {u['speaker']}: {u['text']}")
    return "\n".join(lines)


def _build_prompt(
    utterances: list[dict],
    attendees: list[str],
    known_labels: dict[str, str] | None,
) -> str:
    attendee_lines = "\n".join(f"- {name}" for name in attendees)
    if known_labels:
        known_label_lines = "\n".join(f"- Speaker {k} → {v}" for k, v in known_labels.items())
    else:
        known_label_lines = "(none)"
    return PROMPT_TEMPLATE.format(
        attendee_lines=attendee_lines,
        known_label_lines=known_label_lines,
        n_utterances=len(utterances),
        utterance_block=_render_utterance_block(utterances),
    )


def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = _generate_with_retry(
        client,
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # Match the budget transcription.py uses — Hebrew names + structured JSON
            # for 100s of utterances easily blows past 16k tokens.
            max_output_tokens=65536,
        ),
    )
    return (response.text or "").strip()


def _validate_response(
    raw: str,
    expected_starts: list[int],
    roster: set[str],
) -> tuple[list[dict], int]:
    """Parse + validate Gemini's JSON. Returns (records, out_of_roster_count).

    Records have shape: {"start_ms": int, "speaker_name": str, "confidence": str}.
    Names outside the roster are kept as-is but confidence is forced to "low" and
    counted in out_of_roster_count — the user will see them in the attribution log.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned non-JSON: {e}; first 500 chars: {raw[:500]}") from e

    if not isinstance(parsed, list):
        raise RuntimeError(f"Gemini output is not a JSON array; first 500 chars: {raw[:500]}")

    if len(parsed) != len(expected_starts):
        raise RuntimeError(
            f"Gemini returned {len(parsed)} attributions for {len(expected_starts)} utterances; "
            f"first 500 chars: {raw[:500]}"
        )

    records: list[dict] = []
    out_of_roster = 0
    for i, (item, expected_start) in enumerate(zip(parsed, expected_starts)):
        if not isinstance(item, dict) or {"start_ms", "speaker_name", "confidence"} - item.keys():
            raise RuntimeError(f"Gemini row {i} missing required keys: {item!r}")
        if item["start_ms"] != expected_start:
            raise RuntimeError(
                f"Gemini row {i} start_ms={item['start_ms']} but expected {expected_start} — "
                "the LLM reordered or dropped utterances"
            )
        conf = item["confidence"]
        if conf not in _VALID_CONFIDENCE:
            raise RuntimeError(f"Gemini row {i} invalid confidence {conf!r}")
        name = item["speaker_name"]
        if name != _UNKNOWN_NAME and name not in roster:
            out_of_roster += 1
            conf = "low"
        records.append({"start_ms": expected_start, "speaker_name": name, "confidence": conf})
    return records, out_of_roster


def _render_attributed_line(utt: dict, attribution: dict) -> str:
    ts = _format_timestamp(utt["start_ms"])
    name = attribution["speaker_name"]
    conf = attribution["confidence"]
    if conf == "high":
        return f"[{ts}] {name}: {utt['text']}"
    if conf == "medium":
        return f"[{ts}] {name}?: {utt['text']}"
    return f"[{ts}] Speaker {utt['speaker']} (unattributed): {utt['text']}"


def _render_attributed_transcript(
    parsed: dict,
    attributions: list[dict],
    source_filename: str,
    attendees: list[str],
    model: str,
    counts: dict,
) -> str:
    header = (
        f"Source transcript: {source_filename}\n"
        f"Source provider: {parsed['header_provider_label']}\n"
        f"Speaker-attributed: {datetime.now().isoformat()}\n"
        f"Attribution model: Gemini ({model})\n"
        f"Attendee roster: {', '.join(attendees)}\n"
        f"Confidence counts: {counts['high']} high, {counts['medium']} medium, "
        f"{counts['low']} low ({counts['out_of_roster']} out-of-roster)\n"
        f"Rendering: high → `Name:` · medium → `Name?:` · low → original Speaker label "
        f"with `(unattributed)` marker\n"
        f"---\n\n"
    )
    body_lines = [
        _render_attributed_line(u, a)
        for u, a in zip(parsed["utterances"], attributions)
    ]
    return header + "\n".join(body_lines) + "\n"


def _render_attribution_log(
    parsed: dict,
    attributions: list[dict],
    source_filename: str,
) -> str:
    """List low-confidence + out-of-roster lines for human review."""
    flagged = []
    for u, a in zip(parsed["utterances"], attributions):
        is_low = a["confidence"] == "low"
        if not is_low:
            continue
        ts = _format_timestamp(u["start_ms"])
        flagged.append(
            f"- [{ts}] original=Speaker {u['speaker']} · guess={a['speaker_name']} · "
            f"text: {u['text']}"
        )
    header = (
        f"# Attribution log — low-confidence lines\n"
        f"Source transcript: {source_filename}\n"
        f"Generated: {datetime.now().isoformat()}\n"
        f"Lines below need human review and (if known) manual correction.\n\n"
    )
    return header + "\n".join(flagged) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def attribute_speakers(
    transcript_path: Path,
    attendees: list[str],
    *,
    gemini_api_key: str,
    gemini_model: str = "gemini-2.5-pro",
    known_labels: dict[str, str] | None = None,
) -> dict:
    """Re-attribute utterances in `transcript_path` to named `attendees` via Gemini.

    `known_labels` (e.g. {"B": "Yarden Even"}) is passed to the LLM as a strong
    prior, not a hard lock — diarizers sometimes leak the local-mic speaker into
    the remote bucket on a stray utterance, and the LLM may override the hint
    when conversational cues clearly conflict.

    Writes `<stem>_attributed.md` next to the source. If any lines come back
    low-confidence, also writes `attribution_log_<ts>.md`. Returns:
      {
        "output_path": str,
        "log_path": str | None,
        "counts": {"high": int, "medium": int, "low": int, "out_of_roster": int},
        "model": str,
      }
    """
    if not gemini_api_key:
        raise ValueError("Gemini API key is required")
    if not attendees:
        raise ValueError("At least one attendee is required")

    transcript_path = Path(transcript_path).expanduser().resolve()
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    parsed = parse_transcript_file(transcript_path)
    if not parsed["utterances"]:
        raise ValueError(f"Transcript has no utterances: {transcript_path}")

    roster = set(attendees)
    if known_labels:
        unknown_names = {v for v in known_labels.values() if v not in roster}
        if unknown_names:
            raise ValueError(
                f"--known references names not in --attendees: {sorted(unknown_names)}"
            )

    prompt = _build_prompt(parsed["utterances"], attendees, known_labels)
    raw = _call_gemini(prompt, gemini_api_key, gemini_model)

    expected_starts = [u["start_ms"] for u in parsed["utterances"]]
    attributions, out_of_roster = _validate_response(raw, expected_starts, roster)

    counts = {
        "high": sum(1 for a in attributions if a["confidence"] == "high"),
        "medium": sum(1 for a in attributions if a["confidence"] == "medium"),
        "low": sum(1 for a in attributions if a["confidence"] == "low"),
        "out_of_roster": out_of_roster,
    }

    out_path = transcript_path.with_name(f"{transcript_path.stem}_attributed.md")
    if out_path.exists():
        backup = out_path.with_suffix(
            f".{datetime.now().strftime('%Y%m%d-%H%M%S')}.md.bak"
        )
        out_path.rename(backup)
    out_path.write_text(_render_attributed_transcript(
        parsed, attributions, transcript_path.name, attendees, gemini_model, counts,
    ))

    log_path = None
    if counts["low"]:
        log_path = transcript_path.with_name(
            f"attribution_log_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        )
        log_path.write_text(_render_attribution_log(parsed, attributions, transcript_path.name))

    return {
        "output_path": str(out_path),
        "log_path": str(log_path) if log_path else None,
        "counts": counts,
        "model": gemini_model,
    }
