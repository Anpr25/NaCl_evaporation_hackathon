"""Router failure paths — D2.

The router's whole value is what it does when things go wrong: a model returns garbage, a free
quota runs out, the network dies, the cache is cold in replay mode. None of that is exercised
by a happy-path run, and an untested fallback is not a fallback.

Every test here injects a fake provider, so the suite is fast, offline and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from specalive.llm.base import LLMRequest, LLMResponse, Provider, ProviderUnavailable, QuotaExhausted
from specalive.llm.router import NoTierSucceeded, Router

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["value"],
    "properties": {"value": {"type": "string"}},
}


class FakeProvider(Provider):
    """Replays a scripted sequence of outcomes. A str is returned as the response text;
    an Exception instance is raised."""

    kind = "fake"

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        super().__init__(name, cfg)
        self.script: list[Any] = list(cfg.get("script", []))
        self.calls = 0

    def available(self) -> bool:
        return bool(self.cfg.get("up", True))

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        item = self.script.pop(0) if self.script else '{"value": "default"}'
        if isinstance(item, Exception):
            raise item
        return LLMResponse(
            text=item, tier=self.name, model=self.model,
            prompt_tokens=10, completion_tokens=5, latency_s=0.01,
        )


@pytest.fixture
def make_router(tmp_path, monkeypatch):
    """Build a Router over a two-tier config whose providers are scripted fakes."""

    def _make(tier_a: dict[str, Any], tier_b: dict[str, Any], mode: str = "auto"):
        # Scripts are passed to the builder out of band: they may contain Exception objects,
        # which yaml.safe_dump cannot serialise.
        scripts = {
            "tier_a": list(tier_a.pop("script", [])),
            "tier_b": list(tier_b.pop("script", [])),
        }
        cfg = {
            "tiers": {
                "t0_deterministic": {"kind": "deterministic"},
                "tier_a": {"kind": "fake", "model": "a", **tier_a},
                "tier_b": {"kind": "fake", "model": "b", **tier_b},
            },
            "routes": {"task": ["t0_deterministic", "tier_a", "tier_b"]},
            "modes": {
                "auto": {"allow": ["t0_deterministic", "tier_a", "tier_b"]},
                "replay": {"allow": ["t0_deterministic", "tier_a"], "replay_only": True},
            },
            "cache": {"enabled": True, "dir": str(tmp_path / "cache")},
            "limits": {"max_escalations_per_task": 2, "max_retries_same_tier": 1},
        }
        path = tmp_path / "models.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

        built: dict[str, FakeProvider] = {}

        def fake_build(name: str, c: dict[str, Any]):
            if c.get("kind") == "deterministic":
                return None
            built[name] = FakeProvider(name, {**c, "script": scripts.get(name, [])})
            return built[name]

        monkeypatch.setattr("specalive.llm.router.build_provider", fake_build)
        return Router(config_path=path, mode=mode), built

    return _make


# --------------------------------------------------------------------------- happy path


def test_first_tier_serves_when_it_works(make_router):
    router, built = make_router({"script": ['{"value": "ok"}']}, {})
    resp = router.run("task", "p", schema=SCHEMA)
    assert resp.data == {"value": "ok"}
    assert resp.tier == "tier_a"
    assert "tier_b" not in built or built["tier_b"].calls == 0


def test_deterministic_tier_is_never_dispatched_to_a_provider(make_router):
    """t0 means 'do it in code'. The router must skip it, not try to call it."""
    router, _ = make_router({"script": ['{"value": "ok"}']}, {})
    assert "t0_deterministic" not in router.chain_for("task")


# ------------------------------------------------------------------ invalid output


def test_invalid_json_is_retried_then_escalated(make_router):
    router, built = make_router(
        {"script": ["not json at all", "still not json"]},
        {"script": ['{"value": "rescued"}']},
    )
    resp = router.run("task", "p", schema=SCHEMA)
    assert resp.data == {"value": "rescued"}
    assert resp.tier == "tier_b"
    assert built["tier_a"].calls == 2, "should retry once on the same tier before escalating"


def test_schema_violation_escalates(make_router):
    """Valid JSON, wrong shape. This is the failure mode that matters: it looks fine."""
    router, _ = make_router(
        {"script": ['{"wrong_key": 1}', '{"wrong_key": 2}']},
        {"script": ['{"value": "good"}']},
    )
    assert router.run("task", "p", schema=SCHEMA).tier == "tier_b"


def test_custom_validator_escalates(make_router):
    """Schema-valid but domain-invalid -- e.g. a class name that is not in the catalog."""
    router, _ = make_router(
        {"script": ['{"value": "hallucinated"}', '{"value": "hallucinated"}']},
        {"script": ['{"value": "real"}']},
    )

    def only_real(data: Any) -> tuple[bool, str]:
        return data["value"] == "real", "not in the allowed set"

    assert router.run("task", "p", schema=SCHEMA, validator=only_real).data["value"] == "real"


def test_retry_feedback_tells_the_model_what_was_wrong(make_router):
    """The second attempt must carry the rejection reason, or it just repeats itself."""
    seen: list[str] = []

    router, built = make_router({"script": ["garbage", '{"value": "fixed"}']}, {})
    # Providers are constructed lazily, so force tier_a into existence before spying on it.
    router.provider("tier_a")
    original = built["tier_a"].complete

    def spy(req: LLMRequest) -> LLMResponse:
        seen.append(req.prompt)
        return original(req)

    built["tier_a"].complete = spy  # type: ignore[method-assign]
    router.run("task", "p", schema=SCHEMA)
    assert len(seen) == 2
    assert "rejected" in seen[1].lower(), seen[1]


# ------------------------------------------------------------------ availability


def test_unavailable_tier_is_skipped(make_router):
    """No Ollama daemon, no API key. Skip silently, do not fail."""
    router, built = make_router({"up": False}, {"script": ['{"value": "b"}']})
    assert router.run("task", "p", schema=SCHEMA).tier == "tier_b"
    assert built["tier_a"].calls == 0


def test_offline_mid_call_escalates(make_router):
    """The daemon was up at probe time and died before the call."""
    router, _ = make_router(
        {"script": [ProviderUnavailable("connection refused")]},
        {"script": ['{"value": "b"}']},
    )
    assert router.run("task", "p", schema=SCHEMA).tier == "tier_b"


# ------------------------------------------------------------------ quota


def test_quota_exhausted_disables_the_tier_for_the_rest_of_the_run(make_router):
    """A 429 must take the tier out of rotation, not be retried until the provider bans us."""
    router, built = make_router(
        {"script": [QuotaExhausted("429"), '{"value": "never reached"}']},
        {"script": ['{"value": "b1"}', '{"value": "b2"}']},
    )
    assert router.run("task", "p1", schema=SCHEMA).tier == "tier_b"
    assert router.run("task", "p2", schema=SCHEMA).tier == "tier_b"
    assert built["tier_a"].calls == 1, "tier_a must not be called again after a 429"


def test_declared_rate_limit_is_respected_before_the_provider_enforces_it(make_router, tmp_path):
    router, built = make_router({"script": ['{"value": "x"}'] * 5}, {"script": ['{"value": "b"}'] * 5})
    router.quota.limits["tier_a"] = {"rpm": 2}
    tiers = [router.run("task", f"p{i}", schema=SCHEMA).tier for i in range(4)]
    assert tiers[:2] == ["tier_a", "tier_a"]
    assert tiers[2:] == ["tier_b", "tier_b"], "should back off once rpm is reached"


# ------------------------------------------------------------------ cache and replay


def test_identical_request_is_served_from_cache(make_router):
    router, built = make_router({"script": ['{"value": "once"}']}, {})
    first = router.run("task", "same", schema=SCHEMA)
    second = router.run("task", "same", schema=SCHEMA)
    assert not first.cached and second.cached
    assert built["tier_a"].calls == 1
    assert second.data == {"value": "once"}


def test_cache_hit_reports_its_own_latency_not_the_original(make_router):
    """Replaying the original figure inflates every 'time spent on models' number we quote."""
    router, _ = make_router({"script": ['{"value": "x"}']}, {})
    router.run("task", "same", schema=SCHEMA)
    hit = router.run("task", "same", schema=SCHEMA)
    assert hit.cached
    assert hit.latency_s < 0.5
    assert hit.original_latency_s == pytest.approx(0.01, abs=0.05)


def test_cache_key_separates_different_prompts(make_router):
    router, built = make_router({"script": ['{"value": "1"}', '{"value": "2"}']}, {})
    assert router.run("task", "a", schema=SCHEMA).data["value"] == "1"
    assert router.run("task", "b", schema=SCHEMA).data["value"] == "2"
    assert built["tier_a"].calls == 2


def test_replay_mode_serves_the_cache_and_never_calls_a_provider(make_router):
    """Demo-day mode: a warmed cache reproduces the run with no daemon and no network."""
    warm, built = make_router({"script": ['{"value": "warmed"}']}, {})
    warm.run("task", "demo", schema=SCHEMA)
    assert built["tier_a"].calls == 1

    replay, built2 = make_router({"script": []}, {}, mode="replay")
    replay.cache.dir = warm.cache.dir
    resp = replay.run("task", "demo", schema=SCHEMA)
    assert resp.cached and resp.data == {"value": "warmed"}
    # Stronger than "called zero times": in replay mode the provider is never even
    # constructed, so there is nothing that could accidentally reach the network.
    assert "tier_a" not in built2


def test_replay_mode_fails_loudly_on_a_cold_cache(make_router):
    """Better to stop than to quietly make a live call during a demo."""
    replay, built = make_router({"script": ['{"value": "live"}']}, {}, mode="replay")
    with pytest.raises(NoTierSucceeded):
        replay.run("task", "never seen before", schema=SCHEMA)
    assert "tier_a" not in built, "replay mode must not construct a live provider at all"


# ------------------------------------------------------------------ giving up


def test_every_tier_failing_raises_with_all_the_reasons(make_router):
    router, _ = make_router(
        {"script": [ProviderUnavailable("no daemon")]},
        {"script": [QuotaExhausted("429")]},
    )
    with pytest.raises(NoTierSucceeded) as exc:
        router.run("task", "p", schema=SCHEMA)
    message = str(exc.value)
    assert "no daemon" in message and "429" in message, message


def test_unknown_task_is_a_config_error_not_a_silent_default(make_router):
    router, _ = make_router({}, {})
    with pytest.raises(KeyError):
        router.run("no_such_task", "p", schema=SCHEMA)


# ------------------------------------------------------------------ the evidence log


def test_stats_record_what_each_tier_actually_did(make_router):
    router, _ = make_router(
        {"script": ["garbage", "garbage"]}, {"script": ['{"value": "b"}']}
    )
    router.run("task", "p", schema=SCHEMA)
    stats = router.stats()
    assert stats["by_tier"]["tier_b"]["calls"] == 1
    assert stats["escalations"] == 1, "the escalation must be visible in the report"
    assert stats["by_tier"]["tier_b"]["tokens"] == 15


def test_real_config_is_loadable_and_every_route_names_known_tiers():
    """Guards against a typo in config/models.yaml that would only surface at runtime."""
    cfg = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
    tiers = set(cfg["tiers"])
    for task, chain in cfg["routes"].items():
        for tier in chain:
            assert tier in tiers, f"route '{task}' names unknown tier '{tier}'"
    for mode, spec in cfg["modes"].items():
        for tier in spec["allow"]:
            assert tier in tiers, f"mode '{mode}' allows unknown tier '{tier}'"


# ------------------------------------------------------------------ model fallback


def test_stale_model_name_falls_through_to_the_next(monkeypatch):
    """A hosted catalogue churns faster than our config. `llama-3.3-70b-versatile` was in
    config/models.yaml and 404s on a current key; that must cost one request, not the tier."""
    from specalive.llm.base import ModelUnavailable
    from specalive.llm.providers import _try_models

    class P(Provider):
        kind = "x"

        def available(self) -> bool:
            return True

        def complete(self, req):  # pragma: no cover - not used
            raise NotImplementedError

    prov = P("tier", {"model": "retired-model", "fallback_models": ["current-model"]})
    tried: list[str] = []

    def call(model: str, req: LLMRequest) -> LLMResponse:
        tried.append(model)
        if model == "retired-model":
            raise ModelUnavailable("404")
        return LLMResponse(text="{}", tier="tier", model=model)

    resp = _try_models(prov, LLMRequest(prompt="p"), call)
    assert tried == ["retired-model", "current-model"]
    assert resp.model == "current-model"
    assert prov.resolved_model == "current-model", "the winner must be remembered"


def test_overloaded_model_falls_through_rather_than_failing_the_tier():
    """503 is the most likely free-tier failure. Observed live: gemini-flash-latest was
    overloaded and the run only succeeded because it walked down to gemini-3.5-flash."""
    from specalive.llm.base import ModelUnavailable
    from specalive.llm.providers import _try_models

    class P(Provider):
        kind = "x"

        def available(self) -> bool:
            return True

        def complete(self, req):  # pragma: no cover
            raise NotImplementedError

    prov = P("tier", {"model": "busy-a", "fallback_models": ["busy-b", "free-c"]})

    def call(model: str, req: LLMRequest) -> LLMResponse:
        if model != "free-c":
            raise ModelUnavailable(f"{model} is overloaded (HTTP 503)")
        return LLMResponse(text="{}", tier="tier", model=model)

    assert _try_models(prov, LLMRequest(prompt="p"), call).model == "free-c"


def test_a_remembered_model_is_preferred_but_not_relied_on():
    """A model that answered a minute ago can be overloaded now, so the remembered name is
    tried first and the rest of the list is still available behind it."""
    from specalive.llm.base import ModelUnavailable
    from specalive.llm.providers import _try_models

    class P(Provider):
        kind = "x"

        def available(self) -> bool:
            return True

        def complete(self, req):  # pragma: no cover
            raise NotImplementedError

    prov = P("tier", {"model": "a", "fallback_models": ["b"]})
    prov.resolved_model = "b"
    order: list[str] = []

    def call(model: str, req: LLMRequest) -> LLMResponse:
        order.append(model)
        if model == "b":
            raise ModelUnavailable("now overloaded")
        return LLMResponse(text="{}", tier="tier", model=model)

    assert _try_models(prov, LLMRequest(prompt="p"), call).model == "a"
    assert order == ["b", "a"], "remembered model first, then the rest"


def test_all_models_gone_reports_the_tier_unavailable():
    from specalive.llm.base import ModelUnavailable
    from specalive.llm.providers import _try_models

    class P(Provider):
        kind = "x"

        def available(self) -> bool:
            return True

        def complete(self, req):  # pragma: no cover
            raise NotImplementedError

    prov = P("tier", {"model": "a", "fallback_models": ["b"]})

    def call(model: str, req: LLMRequest) -> LLMResponse:
        raise ModelUnavailable(f"{model} gone")

    with pytest.raises(ProviderUnavailable) as exc:
        _try_models(prov, LLMRequest(prompt="p"), call)
    assert "a gone" in str(exc.value) and "b gone" in str(exc.value)
