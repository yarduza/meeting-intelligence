"""`mi transcribe <video>` — transcribe a video via a selected provider."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def transcribe_command(
    video: Annotated[Path, typer.Argument(help="Path to the video file")],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Transcription provider: assemblyai (fast/cheap) | gemini "
            "(native multimodal, better for merged speakers) | whisper (local, "
            "best diarization, requires HF_TOKEN + whisperx install). Defaults to "
            "DEFAULT_TRANSCRIPTION_PROVIDER in .env (falls back to assemblyai).",
        ),
    ] = None,
    speakers_expected: Annotated[
        int | None,
        typer.Option(
            "--speakers-expected",
            "-s",
            help="Hint diarization with the known number of distinct speakers. "
            "AssemblyAI only (Gemini and Whisper ignore).",
        ),
    ] = None,
    normalize_audio: Annotated[
        bool,
        typer.Option(
            "--normalize-audio",
            "-n",
            help="Apply dynamic loudness normalization + compression during audio extraction. "
            "Helps when one speaker is consistently quieter.",
        ),
    ] = False,
    whisper_model: Annotated[
        str,
        typer.Option(
            "--whisper-model",
            help="Whisper model size (whisper provider only): tiny | base | small | medium | "
            "large-v2 | large-v3. Smaller = faster on CPU, lower text quality.",
        ),
    ] = "large-v3",
    speech_models: Annotated[
        str | None,
        typer.Option(
            "--speech-models",
            help="AssemblyAI speech model(s), comma-separated. Default: universal-3-pro,universal-2 "
            "(primary + Hebrew fallback). Pass 'universal-3-pro' alone for strongest English-only.",
        ),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            "-l",
            help="ISO 639-1 language code (e.g. 'he', 'en'). Whisper only — others "
            "auto-detect. Whisper's auto-detect is unreliable for non-English, so "
            "pass it when you know.",
        ),
    ] = None,
) -> None:
    """Transcribe a video with speaker diarization. Output: <video_parent>/transcript.md."""
    from src.config.settings import settings
    from src.services.transcription import transcribe_video

    resolved_provider = provider or settings.default_transcription_provider
    valid_providers = {"assemblyai", "gemini", "whisper"}
    if resolved_provider not in valid_providers:
        console.print(f"[red]Error:[/red] unknown provider '{resolved_provider}'. Choose: {', '.join(sorted(valid_providers))}.")
        raise typer.Exit(1)
    provider = resolved_provider

    status_msg = {
        "assemblyai": "Extracting audio, uploading to AssemblyAI, and polling until complete...",
        "gemini": "Extracting audio, uploading to Gemini File API, and awaiting diarized JSON...",
        "whisper": "Extracting audio, loading Whisper + pyannote locally, and diarizing...",
    }[provider]

    try:
        with console.status(status_msg, spinner="dots"):
            speech_models_list = None
            if speech_models:
                speech_models_list = [s.strip() for s in speech_models.split(",") if s.strip()]
            result = transcribe_video(
                video,
                provider=provider,  # type: ignore[arg-type]
                assemblyai_api_key=settings.assemblyai_api_key,
                gemini_api_key=settings.gemini_api_key,
                gemini_model=settings.gemini_transcription_model,
                hf_token=settings.hf_token,
                whisper_model=whisper_model,
                speakers_expected=speakers_expected,
                normalize_audio=normalize_audio,
                speech_models=speech_models_list,
                language=language,
            )

        console.print(
            f"[green]\u2713[/green] [{result['provider']}] {result['utterance_count']} utterances "
            f"transcribed in [cyan]{result['transcript_path']}[/cyan]"
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Transcription failed:[/red] {e}")
        raise typer.Exit(1)
