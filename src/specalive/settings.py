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
    for directory in (here, *here.parents):
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
