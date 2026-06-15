"""Slice a video into uniform chunks (default 60 seconds per slice).

Writes `<video_parent>/slices/slice_NNN.mp4` and `_manifest.json`.
Idempotent: if the slices folder already contains slices, returns the existing manifest.

Slice N covers minute N — `slice_003.mp4` is 03:00–03:59.
To analyze moment MM:SS, use `slice_{MM:03d}.mp4`.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


def ffprobe_duration(video_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def slice_video(
    video_path: Path,
    slice_seconds: int = 60,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Slice `video_path` into `slice_seconds`-long chunks.

    `on_progress(current, total)` is called after each successful slice.
    Returns the manifest dict (existing one if slices already present).
    Raises FileNotFoundError if the video doesn't exist.
    """
    video_path = Path(video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    parent = video_path.parent
    out_dir = parent / "slices"
    manifest_path = out_dir / "_manifest.json"

    if out_dir.exists() and any(out_dir.glob("slice_*.mp4")):
        if manifest_path.exists():
            return json.loads(manifest_path.read_text())
        return {"source": video_path.name, "num_slices": len(list(out_dir.glob("slice_*.mp4")))}

    out_dir.mkdir(parents=True, exist_ok=True)
    total = ffprobe_duration(video_path)
    num = int(total // slice_seconds) + (1 if total % slice_seconds > 0 else 0)

    for i in range(num):
        start = i * slice_seconds
        out_path = out_dir / f"slice_{i:03d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-i", str(video_path),
             "-t", str(slice_seconds),
             "-c:v", "h264_videotoolbox", "-b:v", "2M",
             "-c:a", "aac", "-b:a", "96k",
             str(out_path)],
            check=True, capture_output=True,
        )
        if on_progress is not None:
            on_progress(i + 1, num)

    manifest = {
        "source": video_path.name,
        "duration_seconds": total,
        "slice_seconds": slice_seconds,
        "num_slices": num,
        "sliced_at": datetime.now().isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
