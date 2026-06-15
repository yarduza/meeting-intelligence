"""`mi slice <video>` — slice a video into minute-long chunks."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

console = Console()


def slice_command(
    video: Annotated[Path, typer.Argument(help="Path to the video file")],
    slice_seconds: Annotated[int, typer.Option("--slice-seconds", "-s", help="Seconds per slice")] = 60,
) -> None:
    """Slice a video into uniform chunks. Output: <video_parent>/slices/slice_NNN.mp4."""
    from src.services.slicing import slice_video

    try:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Slicing", total=None)

            def on_progress(current: int, total: int) -> None:
                if progress.tasks[task].total is None:
                    progress.update(task, total=total)
                progress.update(task, completed=current)

            manifest = slice_video(video, slice_seconds, on_progress=on_progress)

        out_dir = Path(video).expanduser().resolve().parent / "slices"
        console.print(
            f"[green]\u2713[/green] {manifest['num_slices']} slices in [cyan]{out_dir}[/cyan]"
        )
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Slicing failed:[/red] {e}")
        raise typer.Exit(1)
