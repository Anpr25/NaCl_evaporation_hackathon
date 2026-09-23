"""Provider-neutral LLM interface.

Nothing above this layer knows whether an answer came from a 3B model on the local GPU, a free
Groq endpoint, Gemini, or the replay cache. That is the whole point: the pipeline is written
once and the router decides what is cheap enough to serve it.

Owner: D.
"""

from __future__ import annotations

import abc
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class LLMError(RuntimeError):
    """Recoverable provider failure. The router catches this and escalates a tier."""


class QuotaExhausted(LLMError):
    """Free-tier limit hit. The router demotes this tier for the rest of the run."""


class ProviderUnavailable(LLMError):
    """No network, no daemon, no key. Router skips the tier silently."""


@dataclass
class LLMRequest:
    task: str = "generic"
    prompt: str = ""
    system: str | None = None
    #: JSON Schema the response must satisfy. Providers enforce it natively where they can;
    #: the router validates regardless, because native enforcement is not always honoured.
    schema: dict[str, Any] | None = None
    images: list[bytes] = field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int = 2048
    stop: list[str] = field(default_factory=list)

    def cache_key(self, tier: str, model: str) -> str:
        h = hashlib.sha256()
        for part in (tier, model, self.system or "", self.prompt, json.dumps(self.schema, sort_keys=True)):
            h.update(part.encode("utf-8"))
        for img in self.images:
            h.update(hashlib.sha256(img).digest())
        h.update(f"{self.temperature}:{self.max_tokens}".encode())
        return h.hexdigest()


@dataclass
class LLMResponse:
    text: str
    tier: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    cached: bool = False
    #: Parsed JSON when a schema was requested and the text validated.
    data: Any = None

    def as_log_row(self, task: str, escalated_from: str | None = None) -> dict[str, Any]:
        return {
            "ts": time.time(),
            "task": task,
            "tier": self.tier,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_s": round(self.latency_s, 3),
            "cached": self.cached,
            "escalated_from": escalated_from,
        }


class Provider(abc.ABC):
    """One concrete backend. Keep these dumb: no retries, no routing, no validation."""

    kind: str = "abstract"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.cfg = cfg
        self.model: str = cfg.get("model", "")

    @abc.abstractmethod
    def available(self) -> bool:
        """Cheap liveness probe. Must not raise and must not take more than a second."""

    @abc.abstractmethod
    def complete(self, req: LLMRequest) -> LLMResponse:
        """Run one completion. Raise LLMError subclasses on failure; never return garbage."""

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - optional
        raise NotImplementedError(f"{self.name} does not provide embeddings")

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} {self.name}:{self.model}>"


# ------------------------------------------------------------------ prompt-building helpers


def json_only_system(schema: dict[str, Any] | None) -> str:
    """System preamble that keeps small models on the rails.

    Small instruct models drift into prose and markdown fences. Being explicit and boring here
    is worth more than any amount of clever prompting.
    """
    base = (
        "You are a precise engineering-data extraction function. "
        "You output JSON only: no prose, no markdown fences, no commentary. "
        "If a value is not stated in the input, use null. Never invent numbers, tags or units."
    )
    if schema:
        base += "\n\nThe JSON must validate against this schema:\n" + json.dumps(schema, indent=2)
    return base


def load_prompt(name: str) -> str:
    """Load a prompt template from llm/prompts/<name>.md.

    Prompts live on disk, not in code, so the domain person can tune them without touching
    Python and so a diff of a prompt change is readable in review.
    """
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8")
