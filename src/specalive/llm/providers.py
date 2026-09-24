"""Concrete backends: Ollama (local), Groq (free tier), Gemini (free tier), OpenRouter (paid,
multi-model gateway), Replay (cache-only).

Each provider is deliberately thin. Retries, escalation, schema validation and quota bookkeeping
all live in router.py so that behaviour is identical no matter which backend serves a request.

Owner: D.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import httpx

from .base import (
    LLMError,
    LLMRequest,
    LLMResponse,
    Provider,
    ProviderUnavailable,
    QuotaExhausted,
    json_only_system,
)


def _strip_fences(text: str) -> str:
    """Small models wrap JSON in ``` fences no matter how firmly you ask them not to."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


# ------------------------------------------------------------------------------------ Ollama


class OllamaProvider(Provider):
    """Local models via the Ollama daemon.

    On a 4 GB card, qwen2.5:3b-q4_K_M fits entirely in VRAM and is the workhorse. The 7B needs
    ``options.num_gpu`` tuned so the remainder spills to system RAM rather than OOM-ing.
    """

    kind = "ollama"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.timeout = cfg.get("timeout_s", 180)

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=1.5)
            if r.status_code != 200:
                return False
            names = {m["name"].split(":")[0] for m in r.json().get("models", [])}
            return self.model.split(":")[0] in names
        except Exception:
            return False

    def complete(self, req: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": req.prompt,
            "system": req.system or json_only_system(req.schema),
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.max_tokens,
                **self.cfg.get("options", {}),
            },
        }
        # Ollama supports full JSON-Schema constrained decoding; this is the single biggest
        # quality lever for small models and the reason a 3B is usable at all here.
        if req.schema:
            payload["format"] = req.schema
        if req.images:
            payload["images"] = [base64.b64encode(i).decode() for i in req.images]

        t0 = time.time()
        try:
            r = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(f"ollama not reachable at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMError(f"ollama timed out after {self.timeout}s") from exc
        if r.status_code != 200:
            raise LLMError(f"ollama HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        return LLMResponse(
            text=_strip_fences(body.get("response", "")),
            tier=self.name,
            model=self.model,
            prompt_tokens=body.get("prompt_eval_count", 0),
            completion_tokens=body.get("eval_count", 0),
            latency_s=time.time() - t0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": t},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                raise LLMError(f"ollama embeddings HTTP {r.status_code}")
            out.append(r.json()["embedding"])
        return out


# -------------------------------------------------------------------------------------- Groq


class GroqProvider(Provider):
    """Groq free tier: OpenAI-compatible chat completions, very fast, rate limited by RPM/TPM."""

    kind = "groq"
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.api_key = os.getenv(cfg.get("api_key_env", "GROQ_API_KEY"), "")
        self.timeout = cfg.get("timeout_s", 120)

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderUnavailable("GROQ_API_KEY not set")
        messages = [
            {"role": "system", "content": req.system or json_only_system(req.schema)},
            {"role": "user", "content": req.prompt},
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.schema:
            # Groq honours OpenAI json_object mode; the schema itself is carried in the system
            # prompt and enforced by the router's validator.
            payload["response_format"] = {"type": "json_object"}
        if req.stop:
            payload["stop"] = req.stop

        t0 = time.time()
        try:
            r = httpx.post(
                self.ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("groq unreachable (offline?)") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("groq timed out") from exc

        if r.status_code == 429:
            raise QuotaExhausted(f"groq rate limited: {r.text[:200]}")
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"groq auth rejected: {r.status_code}")
        if r.status_code >= 400:
            raise LLMError(f"groq HTTP {r.status_code}: {r.text[:300]}")

        body = r.json()
        usage = body.get("usage", {})
        return LLMResponse(
            text=_strip_fences(body["choices"][0]["message"]["content"] or ""),
            tier=self.name,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_s=time.time() - t0,
        )


# ------------------------------------------------------------------------------------ OpenRouter


class OpenRouterProvider(Provider):
    """OpenRouter: OpenAI-compatible, but proxies many backends -- including vision-capable
    models -- through one endpoint and one key. Useful as a single fallback tier when neither a
    local Ollama daemon nor Groq/Gemini keys are available."""

    kind = "openrouter"
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.api_key = os.getenv(cfg.get("api_key_env", "OPENROUTER_API_KEY"), "")
        self.timeout = cfg.get("timeout_s", 120)

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderUnavailable("OPENROUTER_API_KEY not set")

        content: Any
        if req.images:
            content = [{"type": "text", "text": req.prompt}]
            for img in req.images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64.b64encode(img).decode()}"},
                    }
                )
        else:
            content = req.prompt

        messages = [
            {"role": "system", "content": req.system or json_only_system(req.schema)},
            {"role": "user", "content": content},
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.schema:
            # OpenRouter forwards OpenAI-style response_format when the underlying model
            # supports it; the router's own validator enforces the schema regardless.
            payload["response_format"] = {"type": "json_object"}
        if req.stop:
            payload["stop"] = req.stop

        t0 = time.time()
        try:
            r = httpx.post(
                self.ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("openrouter unreachable (offline?)") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("openrouter timed out") from exc

        if r.status_code == 429:
            raise QuotaExhausted(f"openrouter rate limited: {r.text[:200]}")
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"openrouter auth rejected: {r.status_code}")
        if r.status_code >= 400:
            raise LLMError(f"openrouter HTTP {r.status_code}: {r.text[:300]}")

        body = r.json()
        # OpenRouter can return HTTP 200 with an "error" body instead of "choices" -- e.g. a
        # free model's upstream provider is overloaded. Seen live: {"error": {"code": 503,
        # "message": "Upstream error from Nvidia: Service temporarily overloaded", ...}}.
        # Without this check that becomes an opaque KeyError on "choices" deep in providers.py.
        if "error" in body:
            err = body.get("error") or {}
            code = err.get("code")
            message = err.get("message", "unknown upstream error")
            if code == 429:
                raise QuotaExhausted(f"openrouter upstream rate limit: {message}")
            if code in (401, 403):
                raise ProviderUnavailable(f"openrouter upstream auth rejected: {message}")
            # Overload/5xx and anything else: a plain LLMError lets the router retry this tier
            # (and then escalate) rather than disabling it for the rest of the run, since this
            # is the upstream free model being flaky, not our own quota being spent.
            raise LLMError(f"openrouter upstream error ({code}): {message}")

        try:
            content = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMError(f"openrouter returned no choices: {json.dumps(body)[:300]}") from exc

        usage = body.get("usage", {})
        return LLMResponse(
            text=_strip_fences(content),
            tier=self.name,
            model=body.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_s=time.time() - t0,
        )


# ------------------------------------------------------------------------------------ Gemini


class GeminiProvider(Provider):
    """Google AI Studio free tier. The only cheap tier here with strong vision, so it owns
    diagram reading (P&IDs, schematics, scanned pages)."""

    kind = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.api_key = os.getenv(cfg.get("api_key_env", "GEMINI_API_KEY"), "")
        self.timeout = cfg.get("timeout_s", 180)

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderUnavailable("GEMINI_API_KEY not set")
        parts: list[dict[str, Any]] = [{"text": req.prompt}]
        for img in req.images:
            parts.append(
                {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(img).decode()}}
            )
        gen: dict[str, Any] = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
        if req.schema:
            gen["responseMimeType"] = "application/json"
            gen["responseSchema"] = _to_gemini_schema(req.schema)

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": gen,
            "systemInstruction": {"parts": [{"text": req.system or json_only_system(None)}]},
        }
        t0 = time.time()
        try:
            r = httpx.post(
                f"{self.BASE}/{self.model}:generateContent",
                json=payload,
                headers={"x-goog-api-key": self.api_key},
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("gemini unreachable (offline?)") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("gemini timed out") from exc

        if r.status_code == 429:
            raise QuotaExhausted(f"gemini rate limited: {r.text[:200]}")
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"gemini auth rejected: {r.status_code}")
        if r.status_code >= 400:
            raise LLMError(f"gemini HTTP {r.status_code}: {r.text[:300]}")

        body = r.json()
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"gemini returned no candidate: {json.dumps(body)[:300]}") from exc
        usage = body.get("usageMetadata", {})
        return LLMResponse(
            text=_strip_fences(text),
            tier=self.name,
            model=self.model,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            latency_s=time.time() - t0,
        )


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini's responseSchema is OpenAPI-flavoured and rejects several JSON-Schema keywords."""
    drop = {"$schema", "additionalProperties", "definitions", "$defs", "default", "examples"}
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k in drop:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _to_gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _to_gemini_schema(v)
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------------------------ Replay


class ReplayProvider(Provider):
    """Serves only from the on-disk cache. Never touches a network or a GPU.

    This is what ``--provider replay`` uses on demo day: a pre-warmed cache makes the whole
    pipeline reproduce a known-good run in seconds, with no quota and no daemon to babysit.
    """

    kind = "replay"

    def available(self) -> bool:
        return True

    def complete(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover - router short-circuits
        raise ProviderUnavailable("replay mode: no cache entry for this request")


PROVIDER_KINDS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "ollama_embed": OllamaProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "openrouter": OpenRouterProvider,
    "replay": ReplayProvider,
}


def build_provider(name: str, cfg: dict[str, Any]) -> Provider | None:
    """Instantiate a provider from a config/models.yaml tier block. None for deterministic tiers."""
    kind = cfg.get("kind", "")
    if kind == "deterministic":
        return None
    cls = PROVIDER_KINDS.get(kind)
    if cls is None:
        raise ValueError(f"unknown provider kind '{kind}' for tier '{name}'")
    return cls(name, cfg)
