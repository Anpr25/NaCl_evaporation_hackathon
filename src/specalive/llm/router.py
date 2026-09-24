"""Tiered model router: cheapest capable tier first, validate, escalate only on failure.

The contract every caller gets:

  * the answer is schema-valid, or you get an exception -- never unvalidated text;
  * identical inputs give identical outputs (content-hash cache);
  * a dead network, a missing key or an exhausted quota degrades instead of failing;
  * every call is logged with tier, tokens, latency and why it escalated.

That log is the evidence for the AI-architecture story: it shows, per run, how much work the
free/local tiers actually did.

Owner: D.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .base import LLMError, LLMRequest, LLMResponse, Provider, ProviderUnavailable, QuotaExhausted
from .providers import build_provider

Validator = Callable[[Any], tuple[bool, str]]


class NoTierSucceeded(LLMError):
    """Every allowed tier failed. Callers must fall back deterministically or declare a gap."""


@dataclass
class DiskCache:
    """Content-addressed response cache. Survives runs; commit it to ship a replayable demo."""

    dir: Path
    enabled: bool = True
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> LLMResponse | None:
        if not self.enabled:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            self.misses += 1
            return None
        self.hits += 1
        t0 = time.time()
        blob = json.loads(path.read_text(encoding="utf-8"))
        # Report what the cache hit actually cost, not what the original call cost. Replaying
        # the old figure inflates every "time spent on model calls" number in the report, and
        # that number is evidence we quote.
        original = blob.pop("latency_s", 0.0)
        resp = LLMResponse(**blob, cached=True, latency_s=round(time.time() - t0, 4))
        resp.original_latency_s = original
        return resp

    def put(self, key: str, resp: LLMResponse) -> None:
        if not self.enabled:
            return
        blob = {
            "text": resp.text,
            "tier": resp.tier,
            "model": resp.model,
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "latency_s": resp.latency_s,
            "data": resp.data,
        }
        (self.dir / f"{key}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")


@dataclass
class QuotaTracker:
    """Best-effort free-tier bookkeeping so we back off before the provider does it for us."""

    limits: dict[str, dict[str, int]] = field(default_factory=dict)
    calls: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    tokens: dict[str, list[tuple[float, int]]] = field(default_factory=lambda: defaultdict(list))
    disabled: set[str] = field(default_factory=set)

    def allows(self, tier: str) -> bool:
        if tier in self.disabled:
            return False
        lim = self.limits.get(tier)
        if not lim:
            return True
        now = time.time()
        recent_min = [t for t in self.calls[tier] if now - t < 60]
        recent_day = [t for t in self.calls[tier] if now - t < 86400]
        if "rpm" in lim and len(recent_min) >= lim["rpm"]:
            return False
        if "rpd" in lim and len(recent_day) >= lim["rpd"]:
            return False
        if "tpm" in lim:
            used = sum(n for t, n in self.tokens[tier] if now - t < 60)
            if used >= lim["tpm"]:
                return False
        return True

    def record(self, tier: str, total_tokens: int) -> None:
        now = time.time()
        self.calls[tier].append(now)
        self.tokens[tier].append((now, total_tokens))

    def disable(self, tier: str) -> None:
        self.disabled.add(tier)


class Router:
    """Owns tier selection, caching, validation and escalation."""

    def __init__(
        self,
        config_path: str | Path = "config/models.yaml",
        mode: str = "auto",
        cache_dir: str | Path | None = None,
    ) -> None:
        self.cfg: dict[str, Any] = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.mode = mode
        modes = self.cfg.get("modes", {})
        if mode not in modes:
            raise ValueError(f"unknown provider mode '{mode}'; choose from {sorted(modes)}")
        self.allowed: set[str] = set(modes[mode]["allow"])
        self.replay_only: bool = bool(modes[mode].get("replay_only"))

        cache_cfg = self.cfg.get("cache", {})
        self.cache = DiskCache(
            dir=Path(cache_dir or cache_cfg.get("dir", ".specalive_cache")),
            enabled=bool(cache_cfg.get("enabled", True)),
        )
        limits = {
            name: t["quota"] for name, t in self.cfg["tiers"].items() if isinstance(t, dict) and "quota" in t
        }
        self.quota = QuotaTracker(limits=limits)
        self.limits = self.cfg.get("limits", {})
        self.log: list[dict[str, Any]] = []
        self._providers: dict[str, Provider | None] = {}
        self._availability: dict[str, bool] = {}

    # ------------------------------------------------------------------ tier plumbing
    def provider(self, tier: str) -> Provider | None:
        if tier not in self._providers:
            self._providers[tier] = build_provider(tier, self.cfg["tiers"][tier])
        return self._providers[tier]

    def is_available(self, tier: str) -> bool:
        """Probed once per run; a dead Ollama daemon must not cost a second on every call."""
        if tier not in self._availability:
            p = self.provider(tier)
            self._availability[tier] = True if p is None else p.available()
        return self._availability[tier]

    def chain_for(self, task: str) -> list[str]:
        chain = self.cfg["routes"].get(task)
        if chain is None:
            raise KeyError(f"no route configured for task '{task}'; add it to config/models.yaml")
        return [t for t in chain if t in self.allowed and t != "t0_deterministic"]

    # ------------------------------------------------------------------ the one public call
    def run(
        self,
        task: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        system: str | None = None,
        images: list[bytes] | None = None,
        validator: Validator | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Execute `task`, escalating tiers until the output validates.

        `validator` runs *after* JSON-schema parsing and is where domain rules belong, e.g.
        "every tag in the answer must exist in the catalog". A tier that produces plausible
        but wrong output is worse than one that fails loudly, so validate aggressively.
        """
        chain = self.chain_for(task)
        if not chain:
            raise NoTierSucceeded(f"task '{task}' has no usable tier in mode '{self.mode}'")

        max_esc = int(self.limits.get("max_escalations_per_task", 2))
        retries = int(self.limits.get("max_retries_same_tier", 1))
        errors: list[str] = []
        previous_tier: str | None = None

        for depth, tier in enumerate(chain[: max_esc + 1]):
            req = LLMRequest(
                task=task,
                prompt=prompt,
                system=system,
                schema=schema,
                images=images or [],
                temperature=temperature,
                max_tokens=max_tokens or self.cfg["tiers"][tier].get("max_tokens", 2048),
            )
            key = req.cache_key(tier, self.cfg["tiers"][tier].get("model", ""))

            cached = self.cache.get(key)
            if cached is not None:
                self.log.append(cached.as_log_row(task, previous_tier))
                return cached
            if self.replay_only:
                errors.append(f"{tier}: replay mode and no cache entry")
                previous_tier = tier
                continue
            if not self.is_available(tier):
                errors.append(f"{tier}: unavailable")
                previous_tier = tier
                continue
            if not self.quota.allows(tier):
                errors.append(f"{tier}: quota exhausted")
                previous_tier = tier
                continue

            provider = self.provider(tier)
            assert provider is not None
            feedback = ""
            for attempt in range(retries + 1):
                try:
                    resp = provider.complete(
                        LLMRequest(**{**req.__dict__, "prompt": req.prompt + feedback})
                    )
                except QuotaExhausted as exc:
                    self.quota.disable(tier)
                    errors.append(f"{tier}: {exc}")
                    break
                except ProviderUnavailable as exc:
                    self._availability[tier] = False
                    errors.append(f"{tier}: {exc}")
                    break
                except LLMError as exc:
                    errors.append(f"{tier} attempt {attempt}: {exc}")
                    continue

                self.quota.record(tier, resp.prompt_tokens + resp.completion_tokens)
                ok, why = self._validate(resp, schema, validator)
                if ok:
                    self.cache.put(key, resp)
                    self.log.append(resp.as_log_row(task, previous_tier if depth else None))
                    return resp

                errors.append(f"{tier} attempt {attempt}: {why}")
                feedback = (
                    "\n\nYour previous answer was rejected. Reason: "
                    f"{why}\nReturn corrected JSON only."
                )
            previous_tier = tier

        raise NoTierSucceeded(f"task '{task}' failed on every tier:\n  - " + "\n  - ".join(errors))

    # ------------------------------------------------------------------ validation
    @staticmethod
    def _validate(
        resp: LLMResponse, schema: dict[str, Any] | None, validator: Validator | None
    ) -> tuple[bool, str]:
        if schema is not None:
            try:
                resp.data = json.loads(resp.text)
            except json.JSONDecodeError as exc:
                return False, f"output is not valid JSON ({exc})"
            ok, why = _check_schema(resp.data, schema)
            if not ok:
                return False, why
        if validator is not None:
            return validator(resp.data if schema else resp.text)
        return True, ""

    # ------------------------------------------------------------------ reporting
    def stats(self) -> dict[str, Any]:
        by_tier: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "tokens": 0, "latency_s": 0.0, "cached": 0}
        )
        for row in self.log:
            b = by_tier[row["tier"]]
            b["calls"] += 1
            b["tokens"] += row["prompt_tokens"] + row["completion_tokens"]
            b["latency_s"] = round(b["latency_s"] + row["latency_s"], 2)
            b["cached"] += int(row["cached"])
        return {
            "mode": self.mode,
            "total_calls": len(self.log),
            "cache_hits": self.cache.hits,
            "cache_misses": self.cache.misses,
            "escalations": sum(1 for r in self.log if r.get("escalated_from")),
            "by_tier": dict(by_tier),
        }


def _check_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, str]:
    """Dependency-free structural check.

    Deliberately not a full JSON-Schema implementation: it covers type, required, enum, array
    items and nested objects, which is all our schemas use. Swap in `jsonschema` if the schemas
    grow, but do not let that become a required dependency for the offline demo.
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(data, dict):
            return False, f"expected object, got {type(data).__name__}"
        for key in schema.get("required", []):
            if key not in data:
                return False, f"missing required key '{key}'"
        for key, sub in schema.get("properties", {}).items():
            if key in data and data[key] is not None:
                ok, why = _check_schema(data[key], sub)
                if not ok:
                    return False, f"{key}: {why}"
        return True, ""
    if expected == "array":
        if not isinstance(data, list):
            return False, f"expected array, got {type(data).__name__}"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(data):
                ok, why = _check_schema(item, item_schema)
                if not ok:
                    return False, f"[{i}]: {why}"
        return True, ""
    if "enum" in schema:
        return (data in schema["enum"], f"'{data}' not in {schema['enum']}")
    prims: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected in prims and not isinstance(data, prims[expected]):
        return False, f"expected {expected}, got {type(data).__name__}"
    return True, ""
