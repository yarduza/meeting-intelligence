# Add `mi` CLI tool with shared services layer

## Context

The three scripts in `scripts/` are invoked by shell path. They mix arg parsing, printing, and business logic in one module, which means a future FastAPI layer can't reuse them cleanly. The Monetera `data-factory` repo already solved this with a Typer+Rich CLI over a pure `src/services/` layer, registered as `mi` via `pyproject.toml`. Adopt the same pattern here (and the same `mi` command name — stands for "meeting intelligence" in this repo, "movement intelligence" there).

## Target layout

```
meeting-intelligence/
├── pyproject.toml              # replaces requirements.txt; entry point mi = "src.cli.main:app"
├── src/
│   ├── cli/
│   │   ├── main.py             # Typer root, mounts 3 commands
│   │   ├── slice_cmd.py
│   │   ├── transcribe_cmd.py
│   │   └── analyze_cmd.py
│   ├── services/               # pure logic, no printing, reusable by CLI + future API
│   │   ├── slicing.py
│   │   ├── transcription.py
│   │   └── visual_analysis.py
│   └── config/
│       └── settings.py         # Pydantic BaseSettings, reads .env
├── SKILL.md                    # edit: scripts/X.py → mi X
├── README.md                   # edit: install command + CLI examples
└── (scripts/, requirements.txt deleted)
```

## Decisions

**Adopting from data-factory:**
- Typer + Rich for CLI; Pydantic `BaseSettings` for config
- `src/cli/` + `src/services/` + `src/config/` split; `pip install -e .` via hatch
- One CLI file per command

**Deliberately simpler:**
- No sub-Typer apps — three single verbs register directly on the root app
- No `MI_` env prefix — vendor keys (`ASSEMBLYAI_API_KEY`, `GEMINI_API_KEY`) stay vendor-standard
- No structlog / Loki — Rich console + stderr for errors
- Python `>=3.12` (matches data-factory; current venv is 3.14, satisfies)

**Service contract:**
- Services return plain dicts or dataclasses
- Services **raise** typed exceptions on failure (`FileNotFoundError`, `ValueError`, `RuntimeError` with a clear message) — never `sys.exit` and never print
- CLI catches, formats the message with Rich, exits non-zero
- A future FastAPI layer catches the same exceptions and maps to HTTP errors
- Progress callback (`on_progress: Callable | None`) on `slicing.slice_video` only — it runs 60+ iterations and the wait is long. Transcription is one blocking poll; visual analysis is 2-3 API calls — status prints from the CLI wrapper are enough for both.

## Execution (order matters)

1. **`pyproject.toml`** — name, `requires-python = ">=3.12"`, deps (typer, rich, pydantic-settings, python-dotenv, requests, google-genai), entry point `mi = "src.cli.main:app"`, hatchling build, `packages = ["src"]`.
2. **`src/` skeleton** — four package dirs with empty `__init__.py` files.
3. **`src/config/settings.py`** — `Settings(BaseSettings)` with three fields (`assemblyai_api_key`, `gemini_api_key`, `gemini_model="gemini-3-pro"`), `env_file=".env"`. Export a module-level `settings = Settings()`.
4. **`src/services/slicing.py`** — port [scripts/slice.py](scripts/slice.py). Keep ffprobe + ffmpeg calls verbatim (with the `h264_videotoolbox` encoder already in place). Function signature: `slice_video(video_path: Path, slice_seconds: int = 60, on_progress: Callable[[int, int], None] | None = None) -> dict`. Returns the manifest. Raises `FileNotFoundError` if the video is missing.
5. **`src/services/transcription.py`** — port [scripts/transcribe.py](scripts/transcribe.py). Signature: `transcribe_video(video_path: Path, api_key: str) -> dict`. Raises `ValueError` if `api_key` is empty, `RuntimeError` on AssemblyAI failures.
6. **`src/services/visual_analysis.py`** — port [scripts/analyze_slices.py](scripts/analyze_slices.py). Signature: `analyze_meeting_folder(folder: Path, api_key: str, model: str) -> dict`. Same exception policy.
7. **`src/cli/slice_cmd.py`, `transcribe_cmd.py`, `analyze_cmd.py`** — each exports one function decorated with Typer arg/option annotations. Wraps the corresponding service call with Rich spinner/panel output. Reads config via `from src.config.settings import settings`. Catches service exceptions, prints the message in red, exits 1.
8. **`src/cli/main.py`** — `app = typer.Typer(name="mi", no_args_is_help=True)` + three `app.command()` registrations.
9. **Update SKILL.md** — grep for `python scripts/` (expect 3 hits in Steps 1-4 of the workflow). Replace each with the corresponding `mi <verb>` invocation.
10. **Update README.md** — replace `pip install -r requirements.txt` with `uv pip install -e .`. Update the "Setup for Layer 2" examples to `mi slice`, `mi transcribe`, `mi analyze`. Add a short "CLI" section listing the three commands.
11. **Delete `scripts/` and `requirements.txt`.** (After SKILL.md and README.md no longer reference them.)
12. **`uv pip install -e .`** and smoke-test `mi --help` plus each `mi <cmd> --help`.

## What we're NOT doing

- Tests (own follow-up; add with `tests/` and `typer.testing.CliRunner`).
- FastAPI layer (own plan; services are already shaped for it).
- `mi prep` convenience combo (add when we feel the friction of running two commands).
- `mi watch` Drive automation (own plan, Phase 2).
- A `.gitignore` for egg-info / build artifacts beyond what's already there (add opportunistically).

## Verification

1. `mi --help` lists three subcommands.
2. `mi slice --help`, `mi transcribe --help`, `mi analyze --help` show typed args.
3. `python -c "from src.services.slicing import slice_video; from src.services.transcription import transcribe_video; from src.services.visual_analysis import analyze_meeting_folder"` — services importable outside the CLI (API-ready).
4. `grep -rn "scripts/" SKILL.md README.md` — zero matches.
5. `ls` at repo root — no `scripts/`, no `requirements.txt`.
6. End-to-end: `mi transcribe "<path to a real video>"` writes `transcript.md` alongside. `mi slice "<same video>"` writes `slices/slice_NNN.mp4`. Same outputs the old scripts produced.
