"""Transcribe a video to a speaker-diarized markdown transcript.

Three providers:
- `assemblyai` — Universal-3-Pro + Universal-2 fallback. Fast, cheap, good for English.
  Weak when two speakers share acoustic characteristics (e.g., same accent + similar mic).
- `gemini` — Gemini 2.5/3 native multimodal audio. Different diarization algorithm
  (uses language context, not only voice prints). Better when AssemblyAI merges speakers.
- `whisper` — Local Whisper + pyannote.audio. Best-in-class diarization. Requires a
  HuggingFace token and extra deps; CPU/MPS compute (no API cost).

All three share the audio-extraction step and write `transcript_<provider>_<YYYYMMDD-HHMMSS>.md`.

Also exports `summarize_transcripts(folder)` which reads existing transcript_*.md files in
a meeting folder and writes a comparison summary (no re-transcription).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests


ASSEMBLYAI_BASE = "https://api.assemblyai.com/v2"


# ---------------------------------------------------------------------------
# Common utilities
# ---------------------------------------------------------------------------


def _extract_audio(video_path: Path, out_path: Path, normalize: bool = False) -> None:
    """Extract audio from a video to mp3.

    If `normalize=True`, apply dynamic audio normalization + compression to level
    the playing field across speakers with uneven mic volumes. Also bumps mp3
    bitrate to 192kbps.
    """
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vn"]
    if normalize:
        # Aggressive speech-targeted chain. Pushes quieter speakers up past the
        # VAD threshold that pyannote / AssemblyAI / Gemini use. Will boost
        # background noise too — acceptable trade for capturing all speakers.
        #   highpass     — strip <80Hz rumble/HVAC/mic handling
        #   speechnorm   — ffmpeg's speech-aware normalizer (adaptive per-sample gain)
        #   loudnorm     — EBU R128 normalization to broadcast-standard -16 LUFS
        cmd.extend([
            "-af",
            "highpass=f=80,speechnorm=p=0.95:e=12.5,loudnorm=I=-16:TP=-1:LRA=7",
            "-acodec", "libmp3lame", "-ab", "192k",
        ])
    else:
        cmd.extend(["-acodec", "libmp3lame", "-ab", "128k"])
    cmd.append(str(out_path))
    subprocess.run(cmd, check=True, capture_output=True)


def _format_utterances(utterances: list[dict]) -> str:
    """Render utterances as `[MM:SS] Speaker X: text` lines."""
    lines = []
    for u in utterances:
        start_ms = u["start_ms"]
        ts = f"{start_ms // 60000:02d}:{(start_ms // 1000) % 60:02d}"
        lines.append(f"[{ts}] Speaker {u['speaker']}: {u['text']}")
    return "\n".join(lines)


def _build_header(video_name: str, provider_label: str) -> str:
    return (
        f"Source recording: {video_name}\n"
        f"Transcribed: {datetime.now().isoformat()}\n"
        f"Transcription provider: {provider_label}\n"
        f"---\n\n"
        f"Account: [fill in]\n"
        f"Date: [fill in]\n"
        f"Meeting #: [fill in]\n"
        f"Participants: [fill in with speaker label mapping, e.g. Speaker A = Matthew Whaley (FalconX, Head of Treasury)]\n"
        f"Yarden's objective going in: [fill in]\n"
        f"---\n\n"
    )


# ---------------------------------------------------------------------------
# AssemblyAI provider
# ---------------------------------------------------------------------------


def _aai_raise_for_status(r: requests.Response, action: str) -> None:
    if r.ok:
        return
    body = r.text[:500] if r.text else "(empty body)"
    raise RuntimeError(f"AssemblyAI {action} failed: HTTP {r.status_code} — {body}")


def _aai_upload(api_key: str, audio_bytes: bytes) -> str:
    r = requests.post(
        f"{ASSEMBLYAI_BASE}/upload",
        headers={"authorization": api_key},
        data=audio_bytes,
    )
    _aai_raise_for_status(r, "upload")
    return r.json()["upload_url"]


def _aai_request_transcript(
    api_key: str,
    audio_url: str,
    speakers_expected: int | None,
    speech_models: list[str] | None = None,
) -> str:
    payload = {
        "audio_url": audio_url,
        "speaker_labels": True,
        "speech_models": speech_models or ["universal-3-pro", "universal-2"],
    }
    if speakers_expected is not None:
        payload["speakers_expected"] = speakers_expected
    r = requests.post(
        f"{ASSEMBLYAI_BASE}/transcript",
        headers={"authorization": api_key},
        json=payload,
    )
    _aai_raise_for_status(r, "transcript request")
    return r.json()["id"]


def _aai_poll(api_key: str, tid: str, interval: int = 5) -> dict:
    while True:
        r = requests.get(f"{ASSEMBLYAI_BASE}/transcript/{tid}", headers={"authorization": api_key})
        _aai_raise_for_status(r, "transcript poll")
        data = r.json()
        status = data["status"]
        if status == "completed":
            return data
        if status == "error":
            raise RuntimeError(f"AssemblyAI processing error: {data.get('error')}")
        time.sleep(interval)


def _transcribe_assemblyai(
    audio_path: Path,
    api_key: str,
    speakers_expected: int | None,
    speech_models: list[str] | None = None,
) -> tuple[list[dict], int]:
    """Returns (utterances, audio_duration_ms)."""
    if not api_key:
        raise ValueError("AssemblyAI API key is required")
    audio_url = _aai_upload(api_key, audio_path.read_bytes())
    tid = _aai_request_transcript(api_key, audio_url, speakers_expected, speech_models)
    data = _aai_poll(api_key, tid)
    utterances = [
        {"start_ms": u["start"], "speaker": u["speaker"], "text": u["text"]}
        for u in data.get("utterances", [])
    ]
    return utterances, data.get("audio_duration", 0) * 1000


# ---------------------------------------------------------------------------
# Gemini provider (native multimodal audio)
# ---------------------------------------------------------------------------


GEMINI_DIARIZATION_PROMPT = """Transcribe this audio with speaker diarization.

Output ONLY a valid JSON array. No markdown fences, no explanatory prose, no trailing commentary. Only the JSON.

Each element must be an object with exactly these fields:
  "start_ms": integer, milliseconds from the start of the audio when the utterance begins.
  "speaker": single uppercase letter A, B, C, D, E, F, ... same person = same letter throughout.
  "text": the transcribed utterance including filler words (um, uh, like) and natural speech patterns.

Rules:
- Assign a consistent letter to each distinct voice across the entire audio.
- Include every utterance. Do not skip short ones or acknowledgments.
- If two speakers have similar voices, still try to separate them based on speech content, context, and timing. Err on the side of splitting rather than merging.
- Preserve repetitions and filler words; do not clean the transcript.
- Use precise millisecond timestamps; do not round to seconds.
"""


_GEMINI_RETRY_DELAYS = (10, 30, 90)
_GEMINI_RETRYABLE_STATUS = {"429", "500", "502", "503", "504"}


def _generate_with_retry(client, *, model, contents, config):
    """Call `client.models.generate_content` with exponential backoff on 5xx/429.

    Retries 3 times (delays 10s, 30s, 90s). Transient Google-side outages —
    especially 503 UNAVAILABLE ("high demand") — are common on preview/pro
    models and worth retrying. Non-retryable errors (4xx other than 429) raise
    immediately.
    """
    last_error = None
    for attempt, delay in enumerate((*_GEMINI_RETRY_DELAYS, None)):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:  # google.genai.errors.APIError + transport errors
            msg = str(e)
            retryable = any(msg.lstrip().startswith(code) for code in _GEMINI_RETRYABLE_STATUS)
            last_error = e
            if delay is None or not retryable:
                raise
            time.sleep(delay)
    raise RuntimeError("Gemini retry loop exhausted without raising") from last_error


def _transcribe_gemini(audio_path: Path, api_key: str, model: str) -> tuple[list[dict], int]:
    """Use Gemini native-audio multimodal transcription with diarization.

    Returns (utterances, audio_duration_ms).
    """
    if not api_key:
        raise ValueError("Gemini API key is required")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    uploaded = client.files.upload(file=str(audio_path))
    while uploaded.state.name == "PROCESSING":
        time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state.name != "ACTIVE":
        raise RuntimeError(f"Gemini file upload failed: state={uploaded.state.name}")

    try:
        response = _generate_with_retry(
            client,
            model=model,
            contents=[uploaded, GEMINI_DIARIZATION_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # Long meetings can exceed the default output budget; full
                # 65k matches Gemini 2.5 Pro's max so we don't truncate JSON.
                max_output_tokens=65536,
            ),
        )
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

    raw = (response.text or "").strip()
    try:
        utterances = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned non-JSON output: {e}; first 500 chars: {raw[:500]}") from e

    if not isinstance(utterances, list) or not all(
        isinstance(u, dict) and "start_ms" in u and "speaker" in u and "text" in u for u in utterances
    ):
        raise RuntimeError(f"Gemini output schema mismatch; first 500 chars: {raw[:500]}")

    duration_ms = max((u["start_ms"] for u in utterances), default=0)
    return utterances, duration_ms


# ---------------------------------------------------------------------------
# Whisper + pyannote.audio provider (local)
# ---------------------------------------------------------------------------


def _transcribe_whisper(
    audio_path: Path,
    hf_token: str,
    model_size: str = "large-v3",
    language: str | None = None,
) -> tuple[list[dict], int]:
    """Use local Whisper for ASR + pyannote.audio for diarization.

    Requires:
      pip install whisperx  (or openai-whisper + pyannote.audio separately)
    Requires HuggingFace token with access granted to:
      https://huggingface.co/pyannote/speaker-diarization-3.1
      https://huggingface.co/pyannote/segmentation-3.0

    `language`: ISO 639-1 code (e.g. "he", "en"). When None, Whisper auto-detects
    from the first 30s — unreliable for non-English; pass it when you know.

    Returns (utterances, audio_duration_ms).
    """
    if not hf_token:
        raise ValueError(
            "HuggingFace token is required for the whisper provider. "
            "Set HF_TOKEN in .env after accepting model terms at "
            "huggingface.co/pyannote/speaker-diarization-3.1"
        )
    try:
        import torch
        import torchaudio
        # Compat shim — torchaudio >=2.3 removed list_audio_backends; whisperx 3.7
        # still calls it. Return a dummy list; whisperx only uses it for logging.
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]
        import whisperx
    except ImportError as e:
        raise RuntimeError(
            "whisper provider requires `whisperx` and `torch`. "
            "Install with: uv pip install whisperx torch"
        ) from e

    # whisperx uses faster-whisper (CTranslate2) which doesn't support MPS.
    # Apple Silicon CPU is slow for Whisper large-v3 (~2-5× realtime on M-series)
    # but it's the only supported device without CUDA.
    device = "cpu"
    compute_type = "int8"

    model = whisperx.load_model(model_size, device, compute_type=compute_type, language=language)
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=8, language=language)

    # Word-level alignment requires a per-language wav2vec2 model. whisperx
    # ships alignment for ~20 languages; for unsupported ones (or load failures)
    # skip alignment — diarization still works on Whisper's segment-level timing.
    try:
        align_model, metadata = whisperx.load_align_model(
            language_code=result["language"], device=device
        )
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device, return_char_alignments=False
        )
    except Exception as e:
        print(f"[whisper] alignment skipped for language={result['language']}: {e}")

    from whisperx.diarize import DiarizationPipeline, assign_word_speakers
    diarize_model = DiarizationPipeline(token=hf_token, device=device)
    diarize_segments = diarize_model(audio)
    result = assign_word_speakers(diarize_segments, result)

    utterances = []
    for segment in result["segments"]:
        speaker = segment.get("speaker", "UNKNOWN")
        if isinstance(speaker, str) and speaker.startswith("SPEAKER_"):
            try:
                idx = int(speaker.split("_")[1])
                speaker = chr(ord("A") + idx)
            except (ValueError, IndexError):
                pass
        utterances.append({
            "start_ms": int(segment["start"] * 1000),
            "speaker": speaker,
            "text": segment["text"].strip(),
        })

    duration_ms = int(len(audio) / 16000 * 1000)  # whisperx loads at 16kHz
    return utterances, duration_ms


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


Provider = Literal["assemblyai", "gemini", "whisper"]

PROVIDER_LABELS = {
    "assemblyai": "AssemblyAI",
    "gemini": "Gemini (native audio)",
    "whisper": "Whisper + pyannote (local)",
}


def transcribe_video(
    video_path: Path,
    *,
    provider: Provider = "assemblyai",
    assemblyai_api_key: str = "",
    gemini_api_key: str = "",
    gemini_model: str = "gemini-2.5-pro",
    hf_token: str = "",
    whisper_model: str = "large-v3",
    speakers_expected: int | None = None,
    normalize_audio: bool = False,
    speech_models: list[str] | None = None,
    language: str | None = None,
) -> dict:
    """Transcribe `video_path`, dispatching to the chosen provider.

    Writes `transcript_<provider>_<YYYYMMDD-HHMMSS>.md` next to the video. The
    timestamped filename makes runs uniquely identifiable; multiple runs of the
    same or different providers coexist without overwriting each other.

    Raises FileNotFoundError if the video doesn't exist, ValueError if the
    chosen provider's credentials are missing, RuntimeError on provider failures.
    """
    video_path = Path(video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = Path(tmp.name)
    try:
        _extract_audio(video_path, audio_path, normalize=normalize_audio)

        if provider == "assemblyai":
            utterances, duration_ms = _transcribe_assemblyai(
                audio_path, assemblyai_api_key, speakers_expected, speech_models
            )
        elif provider == "gemini":
            utterances, duration_ms = _transcribe_gemini(
                audio_path, gemini_api_key, gemini_model
            )
        elif provider == "whisper":
            utterances, duration_ms = _transcribe_whisper(audio_path, hf_token, whisper_model, language)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        transcript_path = video_path.parent / f"transcript_{provider}_{timestamp}.md"
        header = _build_header(video_path.name, PROVIDER_LABELS[provider])
        body = _format_utterances(utterances)
        transcript_path.write_text(header + body)
    finally:
        if audio_path.exists():
            audio_path.unlink()

    return {
        "transcript_path": str(transcript_path),
        "utterance_count": len(utterances),
        "audio_duration_ms": duration_ms,
        "provider": provider,
    }


# ---------------------------------------------------------------------------
# Summary: read existing transcript_*.md files in a folder and produce a
# comparison report. No re-transcription.
# ---------------------------------------------------------------------------


_TRANSCRIPT_FILENAME_RE = re.compile(r"^transcript_(?P<provider>[a-z0-9_]+)_(?P<ts>\d{8}-\d{6})\.md$")
_UTTERANCE_LINE_RE = re.compile(r"^\[(\d+):(\d+)\] Speaker ([A-Z]): (.+)$")
_SUSPICIOUS_GAP_SECONDS = 30


def parse_transcript_file(path: Path) -> dict:
    """Parse a transcript_<provider>_<ts>.md file.

    Returns {provider, timestamp, utterances, header_provider_label}. Ignores
    lines that don't match the utterance format (metadata header etc.).
    Raises ValueError if the filename doesn't match the naming convention.
    """
    match = _TRANSCRIPT_FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(
            f"Filename does not match transcript_<provider>_<YYYYMMDD-HHMMSS>.md: {path.name}"
        )
    provider = match.group("provider")
    timestamp = match.group("ts")

    text = path.read_text()
    header_provider_label = ""
    for line in text.splitlines():
        if line.startswith("Transcription provider:"):
            header_provider_label = line.split(":", 1)[1].strip()
            break

    utterances = []
    for line in text.splitlines():
        m = _UTTERANCE_LINE_RE.match(line)
        if not m:
            continue
        mins, secs, speaker, utt_text = m.groups()
        start_ms = (int(mins) * 60 + int(secs)) * 1000
        utterances.append({"start_ms": start_ms, "speaker": speaker, "text": utt_text})

    return {
        "path": str(path),
        "provider": provider,
        "timestamp": timestamp,
        "header_provider_label": header_provider_label,
        "utterances": utterances,
    }


def compute_transcript_stats(parsed: dict) -> dict:
    """Compute per-provider stats from a parsed transcript."""
    utterances = parsed["utterances"]
    per_speaker: dict[str, list[int]] = defaultdict(list)
    for u in utterances:
        per_speaker[u["speaker"]].append(len(u["text"]))

    suspicious_gaps = []
    for a, b in zip(utterances, utterances[1:]):
        gap_ms = b["start_ms"] - a["start_ms"]
        if gap_ms > _SUSPICIOUS_GAP_SECONDS * 1000:
            suspicious_gaps.append({
                "from_ms": a["start_ms"],
                "to_ms": b["start_ms"],
                "gap_seconds": gap_ms // 1000,
            })

    return {
        "total_utts": len(utterances),
        "distinct_speakers": len(per_speaker),
        "per_speaker": {
            sp: {
                "count": len(lens),
                "longest_chars": max(lens),
                "mean_chars": sum(lens) // len(lens),
            }
            for sp, lens in per_speaker.items()
        },
        "suspicious_gaps": suspicious_gaps,
    }


def _format_timestamp(ms: int) -> str:
    total_seconds = ms // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _render_comparison_markdown(records: list[dict]) -> str:
    """Render the comparison summary markdown from a list of {parsed, stats} dicts."""
    now = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Transcript comparison",
        f"Generated: {now}",
        f"Providers included: {', '.join(sorted(r['parsed']['provider'] for r in records))}",
        "",
        "## Per-provider summary",
        "",
        "| Provider | Timestamp | Header label | Distinct speakers | Total utterances |",
        "|---|---|---|---|---|",
    ]
    for rec in records:
        p = rec["parsed"]
        s = rec["stats"]
        lines.append(
            f"| {p['provider']} | {p['timestamp']} | {p['header_provider_label']} | "
            f"{s['distinct_speakers']} | {s['total_utts']} |"
        )

    speaker_set = sorted({sp for rec in records for sp in rec["stats"]["per_speaker"]})

    lines += ["", "## Longest utterance per speaker (chars)", ""]
    header_row = "| Speaker | " + " | ".join(r["parsed"]["provider"] for r in records) + " |"
    sep_row = "|---|" + "|".join("---" for _ in records) + "|"
    lines += [header_row, sep_row]
    for sp in speaker_set:
        row = [sp]
        for rec in records:
            per_sp = rec["stats"]["per_speaker"].get(sp)
            row.append(str(per_sp["longest_chars"]) if per_sp else "—")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Utterance count per speaker", ""]
    lines += [header_row, sep_row]
    for sp in speaker_set:
        row = [sp]
        for rec in records:
            per_sp = rec["stats"]["per_speaker"].get(sp)
            row.append(str(per_sp["count"]) if per_sp else "—")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", f"## Suspicious gaps (>{_SUSPICIOUS_GAP_SECONDS}s between consecutive utterances)", ""]
    for rec in records:
        provider = rec["parsed"]["provider"]
        gaps = rec["stats"]["suspicious_gaps"]
        if not gaps:
            lines.append(f"- **{provider}**: none")
            continue
        lines.append(f"- **{provider}**:")
        for g in gaps:
            lines.append(
                f"  - [{_format_timestamp(g['from_ms'])}] → [{_format_timestamp(g['to_ms'])}]  —  "
                f"{g['gap_seconds'] // 60}m {g['gap_seconds'] % 60}s gap"
            )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


# USD per minute of audio. Rough estimates; real cost varies by provider tier
# and output length. Override via settings/kwargs if pricing shifts.
PROVIDER_COST_PER_MINUTE = {
    "assemblyai": 0.006,   # AssemblyAI Universal-3-Pro
    "gemini": 0.10,        # Gemini 2.5 Pro audio input + transcript output, upper-bound
    "whisper": 0.0,        # Local compute only
}


def ffprobe_audio_duration_seconds(video_path: Path) -> float:
    """Return the duration of the media file in seconds via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def estimate_compare_costs(video_path: Path, providers: list[str]) -> dict:
    """Return {provider: {'cost_usd': float, 'minutes': float}} for a video."""
    duration_s = ffprobe_audio_duration_seconds(video_path)
    minutes = duration_s / 60.0
    return {
        p: {
            "cost_usd": round(PROVIDER_COST_PER_MINUTE.get(p, 0.0) * minutes, 2),
            "minutes": round(minutes, 1),
        }
        for p in providers
    }


# ---------------------------------------------------------------------------
# Compare: run multiple providers in parallel, write transcripts + summary
# ---------------------------------------------------------------------------


def compare_providers(
    video_path: Path,
    providers: list[str],
    *,
    assemblyai_api_key: str = "",
    gemini_api_key: str = "",
    gemini_model: str = "gemini-2.5-pro",
    hf_token: str = "",
    speakers_expected: int | None = None,
    normalize_audio: bool = False,
) -> dict:
    """Run `providers` in parallel against `video_path`, then summarize.

    Credentials per provider must be passed; missing creds → that provider is
    marked 'skipped' in the result, not an error. Each successful provider
    produces `transcript_<provider>_<ts>.md`; after all finish, calls
    `summarize_transcripts` to produce `transcript_comparison_<ts>.md`.

    Returns: {
        "results": {provider: {"status": "ok|failed|skipped", "path"|"error", "wall_clock_s"}},
        "summary_path": str | None,  # None if nothing succeeded
    }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    video_path = Path(video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    credential_present = {
        "assemblyai": bool(assemblyai_api_key),
        "gemini": bool(gemini_api_key),
        "whisper": bool(hf_token),
    }

    results: dict[str, dict] = {}
    active: list[str] = []
    for p in providers:
        if not credential_present.get(p, True):
            results[p] = {"status": "skipped", "error": "missing credentials", "path": None, "wall_clock_s": 0.0}
        else:
            active.append(p)

    def run_one(provider: str) -> tuple[str, dict]:
        start = time.time()
        try:
            r = transcribe_video(
                video_path,
                provider=provider,  # type: ignore[arg-type]
                assemblyai_api_key=assemblyai_api_key,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
                hf_token=hf_token,
                speakers_expected=speakers_expected,
                normalize_audio=normalize_audio,
            )
            return provider, {
                "status": "ok",
                "path": r["transcript_path"],
                "error": None,
                "wall_clock_s": round(time.time() - start, 1),
            }
        except Exception as e:
            return provider, {
                "status": "failed",
                "path": None,
                "error": str(e),
                "wall_clock_s": round(time.time() - start, 1),
            }

    with ThreadPoolExecutor(max_workers=len(active) or 1) as executor:
        futures = [executor.submit(run_one, p) for p in active]
        for future in as_completed(futures):
            provider, res = future.result()
            results[provider] = res

    any_ok = any(r["status"] == "ok" for r in results.values())
    summary_path = None
    if any_ok:
        try:
            summary = summarize_transcripts(video_path.parent)
            summary_path = summary["output_path"]
        except FileNotFoundError:
            summary_path = None

    return {"results": results, "summary_path": summary_path}


def summarize_transcripts(folder: Path) -> dict:
    """Read all `transcript_<provider>_<ts>.md` files in `folder`, compute stats,
    write `transcript_comparison_<ts>.md`.

    Ignores existing comparison files. Raises FileNotFoundError if no matching
    transcripts are found.
    """
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    transcript_paths = sorted(
        p for p in folder.glob("transcript_*.md")
        if _TRANSCRIPT_FILENAME_RE.match(p.name) and not p.name.startswith("transcript_comparison_")
    )
    if not transcript_paths:
        raise FileNotFoundError(f"No transcript_<provider>_<ts>.md files in {folder}")

    records = []
    for p in transcript_paths:
        parsed = parse_transcript_file(p)
        stats = compute_transcript_stats(parsed)
        records.append({"parsed": parsed, "stats": stats})

    out_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = folder / f"transcript_comparison_{out_ts}.md"
    out_path.write_text(_render_comparison_markdown(records))

    return {
        "output_path": str(out_path),
        "providers": [r["parsed"]["provider"] for r in records],
        "transcript_paths": [r["parsed"]["path"] for r in records],
    }
