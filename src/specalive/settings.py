"""Environment loading. Imported for its side effect by every entry point.

Why this file exists: `.env` was sitting in the repo root with valid keys in it, the
`python-dotenv` dependency was declared, and nothing ever called `load_dotenv()`. The keys
were set and the application could not see them, so `doctor` reported both cloud tiers down
and the router silently degraded to local-only. Nothing failed loudly; it just quietly did
less than it could.

Loading happens at the entry point rather than at import of `llm.providers`, because
providers read `os.getenv` in their constructor and a module-level side effect buried three
imports deep is hard to reason about.

Owner: D.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Search order for the env file. First hit wins; later files do not override earlier ones.
CANDIDATES = (".env", ".env.local")

#: The repository root (src/specalive/settings.py -> two levels up from the package).
#: Everything the code ships with -- config/*.yaml, modelica/SpecAlive.mo, the benchmark
#: packets -- and the state it keeps between runs -- out/catalog.jsonl,
#: out/binding_memory.json, .specalive_cache/ -- lives here. Resolving those against the
#: current directory instead meant that starting the CLI or the web app one folder up
#: failed in four places at once, and quietly: the catalog read as "not built", the router
#: found no models.yaml and dropped every cloud tier, .env was never found, and
#: modelica/SpecAlive.mo raised FileNotFoundError. Assumes the editable install the README
#: describes (`pip install -e .`), which is the only install this repo supports.
REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(p: str | Path) -> Path:
    """`p` as given if it is absolute or exists from here; otherwise the repo's copy.

    For paths the code itself names (a shipped config file, the catalog, a preset packet).
    A path a user typed still works relative to where they typed it -- it is only when that
    does not exist that the repo is tried -- so this never hides a real file behind the
    repo's, it only finds the repo's when the caller's directory has none.
    """
    p = Path(p)
    if p.is_absolute() or p.exists():
        return p
    return REPO_ROOT / p


_loaded: list[str] = []


def load_env(start: str | Path | None = None, *, override: bool = False) -> list[str]:
    """Load .env from `start` or the nearest ancestor that has one. Returns what was loaded.

    Idempotent, and safe to call when python-dotenv is not installed: a missing dependency
    degrades to "environment variables only" rather than crashing the CLI.
    """
    if _loaded and not override:
        return _loaded

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        return []

    here = Path(start or Path.cwd()).resolve()
    # The repo root last: walking up from the current directory never reaches it when the
    # command was started from a folder ABOVE the repo, and the keys then silently did not
    # load -- every cloud tier reported down with nothing saying why.
    for directory in (here, *here.parents, REPO_ROOT):
        for name in CANDIDATES:
            path = directory / name
            if path.is_file():
                load_dotenv(path, override=override)
                _loaded.append(str(path))
        if _loaded:
            break
    return _loaded


def key_status() -> dict[str, str]:
    """What `doctor` reports. Never returns a key, only whether one is present and its shape.

    Shows the prefix so a wrong-provider paste is obvious: a Groq key starts `gsk_`, and a
    Google one does not.
    """
    out: dict[str, str] = {}
    for var, expected_prefix in (("GROQ_API_KEY", "gsk_"), ("GEMINI_API_KEY", "")):
        raw = os.getenv(var, "").strip()
        if not raw:
            out[var] = "not set"
        elif expected_prefix and not raw.startswith(expected_prefix):
            out[var] = f"set but does not start with '{expected_prefix}' -- wrong provider?"
        else:
            out[var] = f"set ({len(raw)} chars, {raw[:4]}...)"
    return out
