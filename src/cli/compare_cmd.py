"""`mi compare <video>` — run all enabled providers in parallel + summarize.

Runs AssemblyAI + Gemini + Whisper against the same video (parallel where
possible), then produces a comparison summary. Providers with missing
credentials are skipped (not an error). Shows a pre-run cost estimate and
requires confirmation (unless --yes).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def compare_command(
    video: Annotated[Path, typer.Argument(help="Path to the video file")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the cost-confirmation prompt."),
    ] = False,
    providers: Annotated[
        str,
        typer.Option(
            "--providers",
            help="Comma-separated list of providers to run. Default: all three.",
        ),
    ] = "assemblyai,gemini,whisper",
    speakers_expected: Annotated[
        int | None,
        typer.Option(
            "--speakers-expected",
            "-s",
            help="AssemblyAI hint for number of distinct speakers. Ignored by gemini/whisper.",
        ),
    ] = None,
    normalize_audio: Annotated[
        bool,
        typer.Option(
            "--normalize-audio",
            "-n",
            help="Apply dynamic loudness normalization during audio extraction.",
        ),
    ] = False,
) -> None:
    """Run all three providers in parallel + produce comparison summary."""
    from src.config.settings import settings
    from src.services.transcription import (
        compare_providers,
        estimate_compare_costs,
    )

    provider_list = [p.strip() for p in providers.split(",") if p.strip()]
    valid = {"assemblyai", "gemini", "whisper"}
    invalid = [p for p in provider_list if p not in valid]
    if invalid:
        console.print(f"[red]Error:[/red] unknown provider(s): {', '.join(invalid)}")
        raise typer.Exit(1)

    # Cost estimation + confirmation
    try:
        estimates = estimate_compare_costs(video, provider_list)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    total = sum(e["cost_usd"] for e in estimates.values())
    minutes = next(iter(estimates.values()))["minutes"] if estimates else 0

    table = Table(title=f"Estimated cost for {minutes:.1f} min of audio")
    table.add_column("Provider")
    table.add_column("Est. cost (USD)", justify="right")
    for p in provider_list:
        e = estimates[p]
        table.add_row(p, f"${e['cost_usd']:.2f}")
    table.add_row("[bold]Total[/bold]", f"[bold]${total:.2f}[/bold]")
    console.print(table)

    if total > 0 and not yes:
        if not typer.confirm("Proceed with comparison run?"):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    # Run
    with console.status("Running providers in parallel...", spinner="dots"):
        result = compare_providers(
            video,
            provider_list,
            assemblyai_api_key=settings.assemblyai_api_key,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_transcription_model,
            hf_token=settings.hf_token,
            speakers_expected=speakers_expected,
            normalize_audio=normalize_audio,
        )

    # Report
    result_table = Table(title="Per-provider result")
    result_table.add_column("Provider")
    result_table.add_column("Status")
    result_table.add_column("Wall-clock")
    result_table.add_column("Output / Error")
    for p in provider_list:
        r = result["results"].get(p, {})
        status = r.get("status", "?")
        color = {"ok": "green", "failed": "red", "skipped": "yellow"}.get(status, "white")
        wall = f"{r.get('wall_clock_s', 0):.1f}s"
        detail = r.get("path") or r.get("error") or "—"
        result_table.add_row(p, f"[{color}]{status}[/{color}]", wall, str(detail)[:80])
    console.print(result_table)

    if result["summary_path"]:
        console.print(f"[green]\u2713[/green] Comparison summary: [cyan]{result['summary_path']}[/cyan]")
    else:
        console.print("[yellow]No successful runs \u2014 no summary written.[/yellow]")
