"""Meeting intelligence CLI — `mi` entry point."""
from __future__ import annotations

import typer

from src.cli.analyze_cmd import analyze_command
from src.cli.attribute_cmd import attribute_command
from src.cli.compare_cmd import compare_command
from src.cli.slice_cmd import slice_command
from src.cli.summarize_cmd import summarize_command
from src.cli.transcribe_cmd import transcribe_command

app = typer.Typer(
    name="mi",
    help="Meeting intelligence CLI (slice / transcribe / compare / summarize / analyze / attribute)",
    no_args_is_help=True,
)

app.command(name="slice")(slice_command)
app.command(name="transcribe")(transcribe_command)
app.command(name="compare")(compare_command)
app.command(name="summarize")(summarize_command)
app.command(name="analyze")(analyze_command)
app.command(name="attribute")(attribute_command)


if __name__ == "__main__":
    app()
