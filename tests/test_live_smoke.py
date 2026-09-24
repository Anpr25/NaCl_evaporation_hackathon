"""Opt-in live check: real extraction against the real NaCl packet, through a real model.

Deliberately separate from test_specalive.py so the default `pytest` run never needs a network
call or a key. Calls extract_claims() directly, not the full Pipeline/CLI -- a failure here can
only mean the extraction path is broken, never reconcile/emit/compile/simulate (out of scope).

Run:  export OPENROUTER_API_KEY=...   (or set it in .env)
      pytest -m live -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

from specalive.extract.claims import _quote_ok, extract_claims
from specalive.ingest.registry import load_packet
from specalive.llm.router import Router

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "nacl_evaporation_sysmlv2_full_dataset"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set"),
    pytest.mark.skipif(not PACKET.exists(), reason="NaCl packet not present"),
]


def test_live_extraction_produces_model_claims_with_verbatim_quotes():
    docs = load_packet(PACKET)
    router = Router(mode="cloud")
    claims = extract_claims(docs, router=router)

    model_claims = [c for c in claims if c.extracted_by != "t0_deterministic"]
    assert model_claims, "no model claims were produced -- OpenRouter tiers may be unreachable"

    # Vision-tier claims (whole image or a tile) cite a visible label, not source *text* --
    # there is nothing to check them against. Only text-path claims get the verbatim check here.
    vision_tiers = {"t4_cloud_vision", "t4_openrouter_vision", "t4_local_vision"}
    text_claims = [c for c in model_claims if c.extracted_by not in vision_tiers]
    vision_claims = [c for c in model_claims if c.extracted_by in vision_tiers]

    by_source = {d.source.id: d.full_text() for d in docs}
    for c in text_claims:
        assert _quote_ok(c.quote, by_source.get(c.source_id, "")), (
            f"non-verbatim quote slipped through: {c.quote!r}"
        )

    pid_claims = [c for c in vision_claims if c.source_id == _pid_source_id(docs)]
    assert pid_claims, "the P&ID must produce at least one claim via the vision path"


def _pid_source_id(docs) -> str | None:
    pid = next((d for d in docs if d.source.filename.endswith(".png")), None)
    return pid.source.id if pid else None
