"""`mi summarize <folder>` — produce a comparison summary from existing transcripts.

Reads all `transcript_<provider>_<ts>.md` files in the given meeting folder and
writes `transcript_comparison_<ts>.md` with per-provider speaker counts, longest
utterance per speaker, and a suspicious-gaps scan. Free — no provider re-runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def summarize_command(
    folder: Annotated[Path, typer.Argument(help="Meeting folder containing transcript_*.md files")],
) -> None:
    """Summarize existing transcripts in a meeting folder."""
    from src.services.transcription import summarize_transcripts

    try:
        with console.status("Parsing transcripts and rendering comparison...", spinner="dots"):
            result = summarize_transcripts(folder)

        providers = ", ".join(result["providers"])
        console.print(
            f"[green]\u2713[/green] Compared {len(result['providers'])} transcripts "
            f"([cyan]{providers}[/cyan]). Wrote [cyan]{result['output_path']}[/cyan]."
        )
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Summarize failed:[/red] {e}")
        raise typer.Exit(1)
