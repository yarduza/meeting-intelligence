"""`mi attribute <transcript>` — re-attribute Speaker A/B/... labels to named attendees via Gemini."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def _parse_known(items: list[str] | None) -> dict[str, str]:
    """Parse `-k LETTER=Name` flags into a {letter: name} dict.

    Raises typer.BadParameter on malformed entries — these are user input errors
    that should fail before any Gemini call.
    """
    result: dict[str, str] = {}
    for raw in items or []:
        if "=" not in raw:
            raise typer.BadParameter(f"--known expects LETTER=Name, got: {raw!r}")
        letter, _, name = raw.partition("=")
        letter = letter.strip()
        name = name.strip()
        if len(letter) != 1 or not letter.isupper():
            raise typer.BadParameter(f"--known letter must be single uppercase A-Z, got: {letter!r}")
        if not name:
            raise typer.BadParameter(f"--known name is empty for letter {letter!r}")
        result[letter] = name
    return result


def attribute_command(
    transcript_path: Annotated[Path, typer.Argument(help="Path to transcript_<provider>_<ts>.md")],
    attendees: Annotated[
        str,
        typer.Option(
            "--attendees", "-a",
            help="Comma-separated attendee names, e.g. 'Yarden Even,Aaron Rinberg,Ben Savir,Nadav'",
        ),
    ],
    known: Annotated[
        list[str] | None,
        typer.Option(
            "--known", "-k",
            help="Lock-ish hint: -k B='Yarden Even'. Repeatable. Treated as strong prior, "
            "not hard lock — the LLM may override if conversational cues conflict.",
        ),
    ] = None,
) -> None:
    """Re-attribute generic speaker labels to named attendees using LLM conversational cues."""
    from src.config.settings import settings
    from src.services.speaker_attribution import attribute_speakers

    if not settings.gemini_api_key:
        console.print("[red]Error:[/red] GEMINI_API_KEY is not set. Add it to .env.")
        raise typer.Exit(1)

    attendee_list = [a.strip() for a in attendees.split(",") if a.strip()]
    if not attendee_list:
        console.print("[red]Error:[/red] --attendees produced an empty list.")
        raise typer.Exit(1)

    known_labels = _parse_known(known)

    try:
        with console.status(
            f"Attributing speakers via Gemini ({settings.gemini_model})...",
            spinner="dots",
        ):
            result = attribute_speakers(
                transcript_path,
                attendee_list,
                gemini_api_key=settings.gemini_api_key,
                gemini_model=settings.gemini_model,
                known_labels=known_labels or None,
            )

        c = result["counts"]
        total = c["high"] + c["medium"] + c["low"]
        console.print(
            f"[green]✓[/green] Attributed {total} utterances "
            f"([green]{c['high']} high[/green], [yellow]{c['medium']} medium[/yellow], "
            f"[red]{c['low']} low[/red]"
            + (f", [red]{c['out_of_roster']} out-of-roster[/red]" if c["out_of_roster"] else "")
            + f"). Wrote [cyan]{result['output_path']}[/cyan]."
        )
        if result["log_path"]:
            console.print(f"Review low-confidence lines: [cyan]{result['log_path']}[/cyan]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Attribution failed:[/red] {e}")
        raise typer.Exit(1)
