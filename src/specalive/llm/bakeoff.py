"""Measure which local model is actually best on *our* tasks, on *this* machine.

Public leaderboards rank models on general benchmarks. We do not need general ability. We need
two narrow things:

  1. read a paragraph and fill a fixed JSON schema without inventing anything;
  2. pick the right entry out of eight retrieved candidates.

A model that is mediocre on MMLU can be excellent at both, and a bigger model that spills out
of VRAM can be *worse* in wall-clock terms than a smaller one that fits. So we measure rather
than argue. Ground truth is generated from the catalog and from fixed snippets of a real
packet, so this is reproducible and needs no hand-labelling.

Owner: D.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import LLMRequest
from .providers import OllamaProvider

#: Candidates worth trying on a 4 GB card. `size_gb` is the approximate on-disk/VRAM weight
#: footprint at the default Ollama quantisation; the KV cache adds a few hundred MB on top.
CANDIDATES: list[dict[str, Any]] = [
    {"tag": "qwen3:4b", "size_gb": 2.6, "note": "strong instruct + JSON; set /no_think for speed"},
    {"tag": "qwen2.5:3b-instruct-q4_K_M", "size_gb": 1.9, "note": "smallest safe option, lots of headroom"},
    {"tag": "gemma3:4b", "size_gb": 3.3, "note": "multimodal - also reads P&IDs; tight fit"},
    {"tag": "llama3.2:3b", "size_gb": 2.0, "note": "solid baseline"},
    {"tag": "phi4-mini", "size_gb": 2.5, "note": "good at structured output"},
    {"tag": "qwen2.5:7b-instruct-q4_K_M", "size_gb": 4.7, "note": "will NOT fit 4 GB; partial CPU offload"},
]

USABLE_VRAM_GB = 3.7  # 4096 MiB card with the display on the iGPU, minus driver overhead

# --------------------------------------------------------------------------- task 1: extract

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["subject", "predicate", "value", "quote"],
    "properties": {
        "subject": {"type": "string"},
        "predicate": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
        "quote": {"type": "string"},
    },
}

EXTRACT_PROMPT = """\
Extract the single engineering fact stated in the text below.

Rules:
- `quote` must be copied VERBATIM from the text. If you cannot quote it, do not answer.
- Never convert, round or infer a number that is not written down.
- `subject` is the tag or identifier the fact is about.
- Answer JSON only.

TEXT
{text}
"""

#: Real sentences from the NaCl packet, with the value the model must recover. Deliberately
#: includes one that states a superseded value, because reporting what a document *says* --
#: rather than what the model thinks is right -- is exactly the behaviour we need.
EXTRACT_CASES: list[dict[str, str]] = [
    {
        "text": "The controller shall open V8 to transfer B1 liquid to B3 until LIS-301 is at least 0.13 m.",
        "expect_value": "0.13",
        "expect_subject": "V8|LIS-301|B3|B1",
    },
    {
        "text": "The B5 evaporation concentration target shall be 0.180 kg/kg NaCl mass fraction.",
        "expect_value": "0.18",
        "expect_subject": "B5",
    },
    {
        "text": "B5 heating shall be inhibited unless FIS-801 proves condenser cooling-water "
                "flow of at least 0.10 kg/s.",
        "expect_value": "0.1",
        "expect_subject": "B5|FIS-801",
    },
    {
        "text": "The concentrate branch shall cool B7 to 25 degC or below before return pumping.",
        "expect_value": "25",
        "expect_subject": "B7",
    },
    {
        "text": "SP-B7-COOL-OLD | B7 | Cooling complete temperature | 20 | degC | "
                "Legacy Notebook | Superseded",
        "expect_value": "20",
        "expect_subject": "B7|SP-B7-COOL-OLD",
    },
]


def _norm_num(s: Any) -> str:
    try:
        return f"{float(str(s).strip().split()[0].rstrip('%')):g}"
    except (ValueError, IndexError):
        return str(s).strip().lower()


def score_extract(data: Any, case: dict[str, str]) -> tuple[bool, str]:
    """Correct means: right value, right subject, and the quote is genuinely from the text."""
    if not isinstance(data, dict):
        return False, "not an object"
    if _norm_num(data.get("value")) != _norm_num(case["expect_value"]):
        return False, f"value {data.get('value')!r} != {case['expect_value']}"
    subject = str(data.get("subject", "")).upper()
    if not any(alt.upper() in subject for alt in case["expect_subject"].split("|")):
        return False, f"subject {data.get('subject')!r}"
    quote = str(data.get("quote", "")).strip().strip('"')
    if len(quote) < 8 or quote.lower() not in case["text"].lower():
        return False, "quote not verbatim (fabricated)"
    return True, "ok"


# ------------------------------------------------------------------------- task 2: pick

PICK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["choice_index"],
    "properties": {"choice_index": {"type": "integer"}, "reason": {"type": "string"}},
}

PICK_PROMPT = """\
An engineering document describes a component as: "{query}"

Choose the single best Modelica class from these candidates:

{shortlist}

Answer JSON only, with choice_index set to the number of your choice.
"""


def build_pick_cases(catalog_path: str | Path, n: int = 6) -> list[dict[str, Any]]:
    """Ground truth generated from the catalog itself: the query is a class's own description,
    the correct answer is that class, and the distractors are its nearest neighbours."""
    from ..catalog.retrieve import CatalogIndex

    ix = CatalogIndex.from_file(catalog_path)
    wanted = [
        "Modelica.Mechanics.Rotational.Components.Inertia",
        "Modelica.Electrical.Analog.Basic.Capacitor",
        "Modelica.Thermal.HeatTransfer.Components.ThermalConductor",
        "Modelica.Blocks.Continuous.PID",
        "Modelica.Mechanics.Translational.Components.Damper",
        "Modelica.Electrical.Analog.Basic.Inductor",
    ][:n]

    # The shortlist is shuffled with a fixed seed before it is shown. Without that, the
    # correct answer is always index 0 -- the query is the class's own description, so BM25
    # ranks it first -- and a model could score 100% by always replying "0". A benchmark that
    # a constant answer can win measures nothing.
    rng = random.Random(20260923)

    cases: list[dict[str, Any]] = []
    for key in wanted:
        entry = ix.get(key)
        if entry is None or not entry.comment:
            continue
        hits = ix.search(entry.comment, k=8, domain=entry.domain)
        if not any(h.entry.key == key for h in hits):
            continue  # retrieval did not surface it; not the model's fault, skip
        shuffled = list(hits)
        rng.shuffle(shuffled)
        cases.append(
            {
                "query": entry.comment,
                "shortlist": ix.render_shortlist(shuffled, max_params=4),
                "answer": next(i for i, h in enumerate(shuffled) if h.entry.key == key),
                "key": key,
            }
        )
    return cases


# ------------------------------------------------------------------------------- the runner


@dataclass
class ModelResult:
    tag: str
    installed: bool
    size_gb: float
    fits_vram: bool
    extract_pass: int = 0
    extract_total: int = 0
    pick_pass: int = 0
    pick_total: int = 0
    tokens_per_s: float = 0.0
    mean_latency_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        total = self.extract_total + self.pick_total
        return (self.extract_pass + self.pick_pass) / total if total else 0.0

    def verdict(self) -> str:
        if not self.installed:
            return "not installed"
        if self.errors and not (self.extract_total + self.pick_total):
            return "failed"
        return f"{self.accuracy:.0%}"


def bake_off(
    candidates: list[dict[str, Any]] | None = None,
    *,
    catalog_path: str | Path = "out/catalog.jsonl",
    base_url: str = "http://localhost:11434",
    on_progress=None,
) -> list[ModelResult]:
    """Run every installed candidate over both task sets and return the measurements."""
    candidates = candidates or CANDIDATES
    try:
        pick_cases = build_pick_cases(catalog_path)
    except FileNotFoundError:
        pick_cases = []

    results: list[ModelResult] = []
    for cand in candidates:
        tag = cand["tag"]
        provider = OllamaProvider(
            "bakeoff", {"model": tag, "base_url": base_url, "timeout_s": 180}
        )
        res = ModelResult(
            tag=tag,
            installed=provider.available(),
            size_gb=cand["size_gb"],
            fits_vram=cand["size_gb"] <= USABLE_VRAM_GB,
        )
        if not res.installed:
            results.append(res)
            if on_progress:
                on_progress(res)
            continue

        latencies: list[float] = []
        tok_rates: list[float] = []

        for case in EXTRACT_CASES:
            res.extract_total += 1
            ok, why = _one(provider, EXTRACT_PROMPT.format(text=case["text"]), EXTRACT_SCHEMA,
                           lambda d: score_extract(d, case), latencies, tok_rates, res)
            res.extract_pass += int(ok)
            if not ok and why:
                res.errors.append(f"extract: {why}")

        for case in pick_cases:
            res.pick_total += 1
            prompt = PICK_PROMPT.format(query=case["query"], shortlist=case["shortlist"])
            ok, why = _one(
                provider, prompt, PICK_SCHEMA,
                lambda d: (d.get("choice_index") == case["answer"],
                           f"chose {d.get('choice_index')}, wanted {case['answer']}"),
                latencies, tok_rates, res,
            )
            res.pick_pass += int(ok)
            if not ok and why:
                res.errors.append(f"pick {case['key'].rsplit('.', 1)[-1]}: {why}")

        res.mean_latency_s = sum(latencies) / len(latencies) if latencies else 0.0
        res.tokens_per_s = sum(tok_rates) / len(tok_rates) if tok_rates else 0.0
        results.append(res)
        if on_progress:
            on_progress(res)
    return results


def _one(provider, prompt, schema, scorer, latencies, tok_rates, res) -> tuple[bool, str]:
    import json

    try:
        resp = provider.complete(
            LLMRequest(task="bakeoff", prompt=prompt, schema=schema, max_tokens=512)
        )
    except Exception as exc:
        res.errors.append(f"call failed: {exc!r}"[:120])
        return False, ""
    latencies.append(resp.latency_s)
    if resp.latency_s > 0 and resp.completion_tokens:
        tok_rates.append(resp.completion_tokens / resp.latency_s)
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError:
        return False, "invalid JSON"
    return scorer(data)


def recommend(results: list[ModelResult]) -> str:
    """Pick a winner. Accuracy first, then speed; a model that does not fit VRAM needs to be
    clearly better to be worth the offload penalty."""
    ran = [r for r in results if r.installed and (r.extract_total + r.pick_total)]
    if not ran:
        return "No candidate ran. Install Ollama and pull at least one model."

    def key(r: ModelResult) -> tuple:
        return (round(r.accuracy, 2), r.fits_vram, r.tokens_per_s)

    best = max(ran, key=key)
    others = [r for r in ran if r is not best]
    line = (
        f"Use {best.tag}: {best.accuracy:.0%} on our tasks, "
        f"{best.tokens_per_s:.0f} tok/s, {best.mean_latency_s:.1f}s per call"
        f"{'' if best.fits_vram else ' (does not fit VRAM -- partial CPU offload)'}."
    )
    if others:
        runner = max(others, key=key)
        line += f" Runner-up {runner.tag} at {runner.accuracy:.0%}, {runner.tokens_per_s:.0f} tok/s."
    return line
