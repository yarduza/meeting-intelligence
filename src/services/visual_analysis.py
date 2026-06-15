"""Run Gemini visual analysis on pending candidates in a meeting folder.

Reads `<meeting_folder>/candidates.json`, runs Gemini on each pending candidate's
slice, writes `<meeting_folder>/visual_analysis.md`, marks candidates as processed.

Output is strictly observable-behavior: body orientation, gestures, gaze, pace,
turn-taking. Emotional inference ("frustrated", "engaged", etc.) is prohibited
at the prompt level.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


_GEMINI_RETRY_DELAYS = (10, 30, 90)
_GEMINI_RETRYABLE_STATUS = {"429", "500", "502", "503", "504"}


MODE_5_SYSTEM = (
    "You analyze video clips from business meetings. Report only observable "
    "behavior with timestamps: body orientation (forward lean, back, turned "
    "away), hand and gesture patterns, gaze direction as a pattern, speaking "
    "pace changes, turn-taking events, overlaps between speakers. "
    "Prohibited framings: emotional state (frustrated, engaged, bored, "
    "interested), intent, truthfulness, rapport quality, confidence in what "
    "someone is thinking or feeling. If the question requires emotional "
    "inference, refuse that framing and report the underlying observable "
    "behavior instead."
)

OUTPUT_FORMAT = (
    "Respond in this exact format:\n\n"
    "SLICE: <filename>\n"
    "QUESTION: <the question asked>\n\n"
    "OBSERVATIONS\n"
    "- [MM:SS within clip] — <specific observable behavior>\n"
    "- ...\n\n"
    "DIRECT ANSWER TO QUESTION\n"
    "<Answer strictly from observations above. If the question cannot be "
    "answered without emotional inference, say so and state what is observable.>"
)


def _analyze_one_slice(api_key: str, model: str, slice_path: Path, question: str, slice_index: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    context_line = (
        f"CONTEXT: This clip covers minute {slice_index:02d}:00 to "
        f"{slice_index:02d}:59 of the meeting."
    )

    parts = [
        types.Part(text=f"{MODE_5_SYSTEM}\n\n{context_line}\n\n"
                        f"QUESTION: {question}\n\n{OUTPUT_FORMAT}"),
        types.Part(inline_data=types.Blob(
            data=slice_path.read_bytes(),
            mime_type="video/mp4",
        )),
    ]

    last_error = None
    for delay in (*_GEMINI_RETRY_DELAYS, None):
        try:
            response = client.models.generate_content(
                model=model,
                contents=types.Content(parts=parts),
            )
            return response.text
        except Exception as e:
            msg = str(e)
            retryable = any(msg.lstrip().startswith(code) for code in _GEMINI_RETRYABLE_STATUS)
            last_error = e
            if delay is None or not retryable:
                raise
            time.sleep(delay)
    raise RuntimeError("Gemini retry loop exhausted") from last_error


def analyze_meeting_folder(folder: Path, api_key: str, model: str) -> dict:
    """Process pending candidates in `folder/candidates.json` via Gemini.

    Writes `visual_analysis.md` to the folder (backing up any prior version).
    Updates `candidates.json` in place (status: processed / error).

    Returns a dict with counts: {processed, errors, skipped_missing_slice}.

    Raises ValueError if api_key is empty, FileNotFoundError if
    candidates.json or slices/ is missing.
    """
    if not api_key:
        raise ValueError("Gemini API key is required")

    folder = Path(folder).expanduser().resolve()
    candidates_file = folder / "candidates.json"
    slices_dir = folder / "slices"
    output_file = folder / "visual_analysis.md"

    if not candidates_file.exists():
        raise FileNotFoundError(f"No candidates.json in {folder}")
    if not slices_dir.exists():
        raise FileNotFoundError(f"No slices/ in {folder}")

    data = json.loads(candidates_file.read_text())
    pending = [c for c in data.get("candidates", []) if c.get("status") == "pending"]

    if not pending:
        return {"processed": 0, "errors": 0, "skipped_missing_slice": 0}

    sections = [
        f"# Visual Analysis — {data.get('meeting_stem', folder.name)}",
        f"Generated: {datetime.now().isoformat()}",
        f"Model: {model}",
        "",
    ]

    counts = {"processed": 0, "errors": 0, "skipped_missing_slice": 0}

    for c in pending:
        slice_index = c["slice_index"]
        slice_path = slices_dir / f"slice_{slice_index:03d}.mp4"
        if not slice_path.exists():
            sections.append(
                f"## [{c['timestamp']}] {c['question']}\n\n"
                f"Slice file missing: {slice_path.name}\n"
            )
            c["status"] = "error"
            counts["skipped_missing_slice"] += 1
            continue

        try:
            result = _analyze_one_slice(api_key, model, slice_path, c["question"], slice_index)
            sections.append(f"## [{c['timestamp']}] {c['question']}\n\n{result}\n")
            c["status"] = "processed"
            c["processed_at"] = datetime.now().isoformat()
            counts["processed"] += 1
        except Exception as e:
            sections.append(f"## [{c['timestamp']}] {c['question']}\n\nError: {e}\n")
            c["status"] = "error"
            c["error"] = str(e)
            counts["errors"] += 1

    if output_file.exists():
        backup = folder / f"visual_analysis_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md.bak"
        output_file.rename(backup)

    output_file.write_text("\n".join(sections))
    candidates_file.write_text(json.dumps(data, indent=2))
    return counts
