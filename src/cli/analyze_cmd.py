"""`mi analyze <meeting-folder>` — Gemini visual analysis on pending candidates."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def analyze_command(
    meeting_folder: Annotated[Path, typer.Argument(help="Per-meeting folder with candidates.json + slices/")],
) -> None:
    """Run Gemini visual analysis on pending candidates. Output: <folder>/visual_analysis.md."""
    from src.config.settings import settings
    from src.services.visual_analysis import analyze_meeting_folder

    if not settings.gemini_api_key:
        console.print(
            "[red]Error:[/red] GEMINI_API_KEY is not set. "
            "Add it to .env or export it in your shell."
        )
        raise typer.Exit(1)

    try:
        with console.status(
            f"Running Gemini ({settings.gemini_model}) on pending candidates...",
            spinner="dots",
        ):
            counts = analyze_meeting_folder(
                meeting_folder, settings.gemini_api_key, settings.gemini_model
            )

        if counts["processed"] == 0 and counts["errors"] == 0 and counts["skipped_missing_slice"] == 0:
            console.print("[yellow]No pending candidates. Nothing to do.[/yellow]")
        else:
            parts = [f"[green]{counts['processed']} processed[/green]"]
            if counts["errors"]:
                parts.append(f"[red]{counts['errors']} errors[/red]")
            if counts["skipped_missing_slice"]:
                parts.append(f"[yellow]{counts['skipped_missing_slice']} missing slices[/yellow]")
            console.print(
                f"[green]\u2713[/green] {', '.join(parts)}. "
                f"See [cyan]{meeting_folder}/visual_analysis.md[/cyan]."
            )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Analysis failed:[/red] {e}")
        raise typer.Exit(1)
