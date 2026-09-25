"""Regression tests. Every one of these encodes a bug that was actually hit, or a trap the
NaCl packet plants. Keep it that way -- a test that never could have failed is dead weight.

Run:  pytest            (fast tests only)
      pytest -m slow    (adds the full compile + simulate gate, ~40 s)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from specalive.emit.sysml import SysMLEmitter, round_trip_check
from specalive.extract.claims import extract_claims, normalise_header, parse_value
from specalive.ingest.base import DocBlock, Document
from specalive.ingest.registry import load_packet
from specalive.ir.evidence import EvidenceClaim, Locator, Source
from specalive.ir.system import SystemModel
from specalive.ir.validate import validate
from specalive.llm.base import LLMError, LLMResponse, Provider
from specalive.llm.providers import PROVIDER_KINDS
from specalive.llm.router import NoTierSucceeded, Router
from specalive.reconcile.precedence import build_supersession_map
from specalive.repair.loop import fix_discrete_loop
from specalive.verify.acceptance import evaluate, screen_reference
from specalive.verify.omc import Diagnostic, crossing_time, parse_diagnostics

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "nacl_evaporation_sysmlv2_full_dataset"
REF_IR = ROOT / "benchmarks" / "nacl_evaporation" / "reference_ir.json"
REF_MO = ROOT / "benchmarks" / "nacl_evaporation" / "reference" / "GeneratedPlant.mo"
LIB_MO = ROOT / "modelica" / "SpecAlive.mo"
TRACE = PACKET / "09_datasets" / "10_batch_run_3000s.csv"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --------------------------------------------------------------------------------- ingest


@pytest.mark.skipif(not PACKET.exists(), reason="NaCl packet not present")
def test_every_file_in_the_packet_parses():
    docs = load_packet(PACKET)
    assert len(docs) == 15
    broken = [(d.source.filename, d.warnings) for d in docs if d.warnings]
    assert not broken, f"adapters produced warnings: {broken}"
    assert all(d.blocks for d in docs), "an adapter produced a document with no blocks"


@pytest.mark.skipif(not PACKET.exists(), reason="NaCl packet not present")
def test_pid_image_is_offered_to_the_vision_tier():
    docs = load_packet(PACKET)
    pid = next(d for d in docs if d.source.filename.endswith(".png"))
    assert pid.images(), "the P&ID must reach the vision tier as bytes"


def test_docx_embedded_image_reaches_the_vision_tier(tmp_path):
    """A diagram pasted into a design note is exactly the evidence the vision tier needs; before
    this, DocxAdapter only read paragraphs and tables and any embedded picture vanished."""
    docx = pytest.importorskip("docx")
    PIL_Image = pytest.importorskip("PIL.Image")

    img_path = tmp_path / "fig.png"
    PIL_Image.new("RGB", (40, 40), color="white").save(img_path)
    doc_path = tmp_path / "note.docx"
    d = docx.Document()
    d.add_paragraph("Design note with an embedded diagram.")
    d.add_picture(str(img_path))
    d.save(str(doc_path))

    from specalive.ingest.adapters import DocxAdapter

    source = Source(id="SRC-01", filename="note.docx", media_type="application/vnd.docx")
    doc = DocxAdapter().parse(doc_path, source)
    assert doc.images(), "an image embedded in a .docx must reach the vision path"
    assert not doc.warnings, doc.warnings


def test_docx_embedded_transparent_image_is_composited_onto_white_not_blackened(tmp_path):
    """convert("RGB") on its own discards alpha instead of compositing it -- a transparent
    background silently became a black rectangle, with no error or warning that the diagram's
    evidence was gone."""
    docx = pytest.importorskip("docx")
    PIL_Image = pytest.importorskip("PIL.Image")

    img_path = tmp_path / "fig.png"
    # Fully transparent background with an opaque red square in the middle -- if alpha is
    # dropped instead of composited, the (0, 0) corner comes out black, not white.
    img = PIL_Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for x in range(10, 30):
        for y in range(10, 30):
            img.putpixel((x, y), (255, 0, 0, 255))
    img.save(img_path)

    doc_path = tmp_path / "note.docx"
    d = docx.Document()
    d.add_paragraph("Design note with a transparent diagram.")
    d.add_picture(str(img_path))
    d.save(str(doc_path))

    from specalive.ingest.adapters import DocxAdapter

    source = Source(id="SRC-01", filename="note.docx", media_type="application/vnd.docx")
    doc = DocxAdapter().parse(doc_path, source)
    full_image = doc.images()[0]
    out_img = PIL_Image.open(io.BytesIO(full_image.image)).convert("RGB")
    assert out_img.getpixel((0, 0)) == (255, 255, 255), (
        "a transparent background must composite to white, not black"
    )
    assert out_img.getpixel((20, 20)) == (255, 0, 0), "the opaque content must be preserved"


def test_chunks_can_be_restricted_to_prose_kinds():
    """The model text path must only ever see prose -- a table/keyvalue/graph/code/image block
    is either already deterministic or belongs to the vision path, never the text model."""
    doc = Document(source=Source(id="SRC-01", filename="x.txt", media_type="text/plain"))
    doc.blocks = [
        DocBlock("heading", "Overview"),
        DocBlock("paragraph", "Free text about the system."),
        DocBlock("table", "a | b", rows=[["a", "b"]]),
        DocBlock("keyvalue", "k = v", data={"path": "k", "value": "v"}),
        DocBlock("graph", "A -> B", rows=[["from", "to"], ["A", "B"]]),
        DocBlock("code", "x = 1;"),
        DocBlock("image", "[fig1]", image=b"not-really-an-image"),
    ]
    text = "\n".join(c for c, _ in doc.chunks(kinds=("heading", "paragraph", "list")))
    assert "Overview" in text and "Free text" in text
    assert "a | b" not in text
    assert "k = v" not in text
    assert "A -> B" not in text
    assert "x = 1" not in text
    assert "[fig1]" not in text


def test_value_parsing():
    assert parse_value("0.18 kg/kg") == (0.18, "kg/kg")
    assert parse_value("20000") == (20000, None)
    assert parse_value("Yes") == (True, None)
    assert parse_value("") == (None, None)
    assert parse_value("open")[0] == "open"


def test_header_synonyms_are_domain_neutral():
    # The same register vocabulary must work whether the plant is chemical or electrical.
    assert normalise_header("Tag") == "id"
    assert normalise_header("Setpoint") == "value"
    assert normalise_header("Superseded By") == "superseded_by"
    assert normalise_header("Control Source") == "ownership"
    assert normalise_header("wholly unrelated column") is None


# --------------------------------------------------------------------------------- traps


@pytest.mark.skipif(not PACKET.exists(), reason="NaCl packet not present")
def test_supersession_direction_is_not_inverted():
    """Trap F1. A register states supersession as 'X is superseded BY Y', which is the
    opposite direction from 'X supersedes Y'. Reading it backwards would make the system
    prefer exactly the legacy values the packet is testing for."""
    claims = extract_claims(load_packet(PACKET))
    sup = build_supersession_map(claims)
    assert "CR-017" in sup, "CR-017 must be recognised as a superseding record"
    assert {"REQ-ROU-001", "REQ-ROU-002"} <= sup["CR-017"]
    # and never the other way round
    assert "REQ-ROU-001" not in sup or "CR-017" not in sup.get("REQ-ROU-001", set())


def test_supersession_map_recognises_predicate_spelling_variants():
    """The direction check used to be an exact-match whitelist on four spellings. A model
    writing 'is_superseded_by', or a register using 'replaced-by', fell through to the *other*
    branch and silently inverted winner and loser -- precisely the F1 trap this packet plants."""
    claims = [
        EvidenceClaim(id="CLM-1", source_id="SRC-01", kind="supersession",
                      subject="REQ-ROU-001", predicate="is_superseded_by", value="CR-017", quote="x"),
        EvidenceClaim(id="CLM-2", source_id="SRC-01", kind="supersession",
                      subject="REQ-ROU-002", predicate="replaced-by", value="CR-017", quote="y"),
    ]
    sup = build_supersession_map(claims)
    assert {"REQ-ROU-001", "REQ-ROU-002"} <= sup["CR-017"]
    assert "REQ-ROU-001" not in sup and "REQ-ROU-002" not in sup


# --------------------------------------------------------------- extract: model path (A1/A2)


class _FakeRouter:
    """Duck-typed stand-in for llm.router.Router -- extract_claims only ever calls .run()."""

    def __init__(self, claims_by_task: dict[str, list[dict]], tier: str = "t_fake", fail_tasks=()):
        self.claims_by_task = claims_by_task
        self.tier = tier
        self.fail_tasks = set(fail_tasks)
        self.calls: list[str] = []

    def run(self, task, prompt, *, schema=None, validator=None, images=None, **_):
        self.calls.append(task)
        if task in self.fail_tasks:
            raise NoTierSucceeded("forced failure for this test")
        data = {"claims": self.claims_by_task.get(task, [])}
        if validator is not None:
            ok, why = validator(data)
            assert ok, why
        return LLMResponse(text="", tier=self.tier, model="fake", data=data)


def _doc(text: str) -> Document:
    doc = Document(source=Source(id="SRC-01", filename="x.txt", media_type="text/plain"))
    doc.blocks = [DocBlock("paragraph", text, Locator(line_start=1))]
    return doc


def test_quote_ok_is_whitespace_insensitive_but_not_forgiving():
    from specalive.extract.claims import _quote_ok

    chunk = "The motor M-1 draws\na rated current of 12 A at 400 V."
    assert _quote_ok("The motor M-1 draws a rated current of 12 A", chunk)  # spans a line join
    assert not _quote_ok("M-1 draws about 12 amps", chunk)  # paraphrase
    assert not _quote_ok("a rated current of 15 A", chunk)  # changed number
    assert not _quote_ok("", chunk)


def test_extract_claims_drops_only_the_fabricated_claim_not_the_whole_response():
    """The rule: reject any *claim* whose quote isn't verbatim -- not the whole batch it arrived
    in. One bad quote among good ones must not cost every other fact in that response."""
    chunk_text = "The motor M-1 draws a rated current of 12 A at 400 V."
    router = _FakeRouter(
        {
            "extract_claim": [
                {"kind": "parameter", "subject": "M-1", "predicate": "rated_current",
                 "value": 12, "unit": "A", "quote": "rated current of 12 A"},
                {"kind": "parameter", "subject": "M-1", "predicate": "rated_current",
                 "value": 15, "unit": "A", "quote": "rated current of 15 A"},  # fabricated
            ]
        }
    )
    doc = _doc(chunk_text)
    claims = extract_claims([doc], router=router)
    assert len(claims) == 1
    assert claims[0].value == 12
    assert claims[0].extracted_by == "t_fake"
    assert any("dropped 1 non-verbatim" in w for w in doc.warnings)


def test_extract_claims_is_not_specific_to_the_nacl_domain():
    """Nothing about the extractor may be load-bearing for one packet: the real evaluation
    packet is a different, unknown domain. A synthetic HVAC-flavoured fact must work exactly
    like a chemical-process one."""
    chunk_text = "Heat exchanger HX-3 has a design duty of 45 kW."
    router = _FakeRouter(
        {
            "extract_claim": [
                {"kind": "parameter", "subject": "HX-3", "predicate": "design_duty",
                 "value": 45, "unit": "kW", "quote": "design duty of 45 kW"},
            ]
        }
    )
    claims = extract_claims([_doc(chunk_text)], router=router)
    assert len(claims) == 1
    assert claims[0].subject == "HX-3" and claims[0].value == 45


def test_extract_claims_vision_loop_sets_bbox_locator_from_the_tile():
    doc = Document(source=Source(id="SRC-01", filename="p&id.png", media_type="image/png"))
    doc.blocks = [DocBlock("image", "[p&id.png tile r0c0]", Locator(bbox=(1, 2, 3, 4)), image=b"fake")]
    router = _FakeRouter(
        {"read_diagram": [{"kind": "component", "subject": "P-101", "predicate": "label",
                            "value": None, "quote": "P-101"}]}
    )
    claims = extract_claims([doc], router=router)
    assert len(claims) == 1
    assert claims[0].locator.bbox == (1, 2, 3, 4)
    assert claims[0].extracted_by == "t_fake"


def test_extract_claims_records_a_tier_failure_and_continues():
    """A chunk or image that never validates on any tier must not abort the whole document --
    it becomes a warning, and every other block still gets a chance."""
    doc = Document(source=Source(id="SRC-01", filename="x.txt", media_type="text/plain"))
    doc.blocks = [
        DocBlock("paragraph", "Pump P-2 runs at 50 Hz.", Locator(line_start=1)),
        DocBlock("image", "[fig1]", Locator(), image=b"fake"),
    ]
    router = _FakeRouter(
        {"read_diagram": [{"kind": "component", "subject": "K-1", "predicate": "label",
                            "value": None, "quote": "K-1"}]},
        fail_tasks={"extract_claim"},
    )
    claims = extract_claims([doc], router=router)
    assert len(claims) == 1 and claims[0].subject == "K-1"
    assert any("extract_claim failed" in w for w in doc.warnings)


def test_extract_claims_survives_a_null_kind_without_losing_the_whole_batch():
    """`{"kind": null}` passes _check_schema (it skips null-valued properties) and then blows up
    EvidenceClaim's Literal field. That crash used to propagate out of extract_claims() entirely,
    discarding every deterministic claim already collected in the same call -- not just the one
    malformed model claim."""
    doc = Document(source=Source(id="SRC-01", filename="x.txt", media_type="text/plain"))
    doc.blocks = [
        DocBlock("table", "id | value\nA-1 | 5", rows=[["id", "value"], ["A-1", "5"]]),
        DocBlock("paragraph", "Pump P-2 runs at 50 Hz.", Locator(line_start=1)),
    ]
    router = _FakeRouter(
        {
            "extract_claim": [
                {"kind": None, "subject": "P-2", "predicate": "frequency", "value": 50,
                 "unit": "Hz", "quote": "P-2 runs at 50 Hz"},
            ]
        }
    )
    claims = extract_claims([doc], router=router)
    det = [c for c in claims if c.extracted_by == "t0_deterministic"]
    assert len(det) == 1 and det[0].subject == "A-1", "the deterministic claim must survive"
    model_claims = [c for c in claims if c.extracted_by != "t0_deterministic"]
    assert len(model_claims) == 1
    assert model_claims[0].kind == "note", "a null kind must fall back to 'note', not crash"


def test_extract_claims_drops_a_claim_with_an_unrecognised_kind_instead_of_crashing():
    """A `kind` the model invented outright (not null, just not one of the 15 allowed values)
    still fails EvidenceClaim's Literal field even with the null-kind fix in place -- this is
    what the broader try/except around construction actually guards against."""
    doc = Document(source=Source(id="SRC-01", filename="x.txt", media_type="text/plain"))
    doc.blocks = [DocBlock("paragraph", "Pump P-2 runs at 50 Hz.", Locator(line_start=1))]
    router = _FakeRouter(
        {
            "extract_claim": [
                {"kind": "widget", "subject": "P-2", "predicate": "frequency", "value": 50,
                 "unit": "Hz", "quote": "P-2 runs at 50 Hz"},
            ]
        }
    )
    claims = extract_claims([doc], router=router)
    assert claims == []
    assert any("malformed claim" in w for w in doc.warnings)


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_reference_ir_resolves_every_trap():
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))

    # F1: B7 cools to 25 degC, not 20
    b7 = next(p for p in m.parameters if p.id == "SP-B7-COOL")
    assert b7.quantity.value == pytest.approx(298.15)
    assert b7.status == "effective"
    assert next(p for p in m.parameters if p.id == "SP-B7-COOL-OLD").status == "superseded"

    # F2: condensate B6 -> B1 via P2; concentrate B7 -> B2 via P1
    ret_a = next(c for c in m.connections if c.id == "C_RET_A_b")
    ret_b = next(c for c in m.connections if c.id == "C_RET_B_b")
    assert ret_a.target.startswith("B1."), "B6 condensate must return to B1"
    assert ret_b.target.startswith("B2."), "B7 concentrate must return to B2"
    assert "P2" in ret_a.series_elements and "V1" in ret_a.series_elements
    assert "P1" in ret_b.series_elements and "V5" in ret_b.series_elements

    # F3: K1 survives as a distinct part
    assert m.block("K1") is not None and not m.block("K1").physical_only

    # F5: exactly 15 automated valve commands, and manual valves are architecture-only
    cmds = [s for s in m.signals if s.role == "actuator" and s.name.startswith("cmd_V")]
    assert len(cmds) == 15
    assert all(m.block(v).physical_only for v in ("V2", "V17", "V29"))

    # F6: both return pumps retained despite the documented convergence defect
    assert m.block("RET_A") and m.block("RET_B")


# ------------------------------------------------------------------------------ validate


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_reference_ir_is_clean():
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))
    r = validate(m)
    assert r.ok, "\n".join(str(f) for f in r.errors)
    assert not r.warnings, "\n".join(str(f) for f in r.warnings)


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_guard_language_builtins_are_known():
    """`in(<state>)` is the guard language's membership predicate, not an unknown symbol."""
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))
    join = next(t for sm in m.state_machines for t in sm.transitions if t.id == "T7")
    assert "in(" in join.guard
    assert not [f for f in validate(m).findings if f.check == "guard-symbols"]


# --------------------------------------------------------------------------------- sysml


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_sysml_round_trip_loses_nothing():
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))
    text = SysMLEmitter(m).emit()
    assert not round_trip_check(m, text)


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_sysml_declares_no_duplicate_port_defs():
    m = SystemModel.model_validate_json(REF_IR.read_text(encoding="utf-8"))
    names = [
        line.split()[2]
        for line in SysMLEmitter(m).emit().splitlines()
        if line.strip().startswith("port def ")
    ]
    assert len(names) == len(set(names)), f"duplicate port def: {names}"


# -------------------------------------------------------------------------------- repair


def test_deterministic_fix_for_discrete_algebraic_loop():
    """The exact failure this scaffold hit: omc folds output equations back into the state
    reads inside a scan, closing a discrete cycle. Reading state via pre() breaks it."""
    src = """\
block C
  Integer s(start = 0, fixed = true);
  output Boolean y;
algorithm
  when sample(0, 0.1) then
    if s == 0 then
      s := 1;
    end if;
  end when;
equation
  y = (s == 1);
end C;
"""
    diag = Diagnostic(kind="discrete_loop", message="Purely discrete algebraic loops", raw="")
    patched, why = fix_discrete_loop(src, diag)
    assert "pre(s) == 0" in patched
    assert "s := 1;" in patched, "assignments must not be wrapped in pre()"
    assert "pre(pre(" not in patched
    assert "pre" in why


def test_diagnostics_are_classified_and_located():
    raw = (
        "[C:/x/Gen.mo:176:5-176:33:writable] Error: Variable B1.out not found in scope Plant.\n"
    )
    diags = parse_diagnostics(raw)
    assert diags and diags[0].kind == "undeclared"
    assert diags[0].line == 176 and diags[0].file.endswith("Gen.mo")


# --------------------------------------------------------------------------- llm router


class _FakeUnavailable(Provider):
    kind = "fake_unavail"

    def available(self) -> bool:
        return False

    def complete(self, req):  # pragma: no cover - must never be reached
        raise AssertionError(f"{self.name}: an unavailable provider must never be called")


class _FakeAlwaysOk(Provider):
    kind = "fake_ok"

    def available(self) -> bool:
        return True

    def complete(self, req):
        return LLMResponse(text="{}", tier=self.name, model=self.model, data={})


class _FakeFailing(Provider):
    """Available, but every call fails -- used to prove the escalation cap counts real
    attempts, not chain position."""

    kind = "fake_failing"
    log: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, req):
        _FakeFailing.log.append(self.name)
        raise LLMError("boom")


def _write_router_config(tmp_path: Path, tiers: dict) -> Path:
    cfg = {
        "tiers": {"t0_deterministic": {"kind": "deterministic"}, **tiers},
        "routes": {"test_task": list(tiers)},
        "modes": {"auto": {"allow": ["t0_deterministic", *tiers]}},
        "cache": {"enabled": False},
        "limits": {"max_escalations_per_task": 2, "max_retries_same_tier": 1},
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_router_skips_unavailable_tiers_without_spending_the_escalation_cap(tmp_path, monkeypatch):
    """Regression: the cap used to be applied to chain *position*, cutting the chain to
    `max_escalations + 1` entries before unavailable tiers were skipped. Three unavailable tiers
    ahead of a real one used to starve the run before it ever reached the fourth tier -- which is
    exactly where OpenRouter sits behind Ollama/Groq/Gemini in the real config."""
    monkeypatch.setitem(PROVIDER_KINDS, "fake_unavail", _FakeUnavailable)
    monkeypatch.setitem(PROVIDER_KINDS, "fake_ok", _FakeAlwaysOk)
    cfg_path = _write_router_config(
        tmp_path,
        {
            "tA": {"kind": "fake_unavail", "model": "a"},
            "tB": {"kind": "fake_unavail", "model": "b"},
            "tC": {"kind": "fake_unavail", "model": "c"},
            "tD": {"kind": "fake_ok", "model": "d"},
        },
    )
    router = Router(config_path=cfg_path, mode="auto")
    resp = router.run("test_task", "prompt")
    assert resp.tier == "tD"


def test_router_escalation_cap_still_limits_real_attempts(tmp_path, monkeypatch):
    """The cap must still do its job when tiers are actually reachable: with
    max_escalations_per_task=2, at most 3 tiers may ever be called for one task."""
    monkeypatch.setitem(PROVIDER_KINDS, "fake_failing", _FakeFailing)
    _FakeFailing.log = []
    cfg_path = _write_router_config(
        tmp_path,
        {
            "tA": {"kind": "fake_failing", "model": "a"},
            "tB": {"kind": "fake_failing", "model": "b"},
            "tC": {"kind": "fake_failing", "model": "c"},
            "tD": {"kind": "fake_failing", "model": "d"},
        },
    )
    router = Router(config_path=cfg_path, mode="auto")
    with pytest.raises(NoTierSucceeded):
        router.run("test_task", "prompt")
    assert set(_FakeFailing.log) == {"tA", "tB", "tC"}


# ---------------------------------------------------------------------------- acceptance


def test_acceptance_expression_language():
    cols = {"time": [0, 1, 2, 3, 4], "x": [0.0, 0.5, 1.0, 0.5, 0.0]}
    assert evaluate("crosses(x, 0.9, rising)", cols)[0]
    assert evaluate("crosses(x, 0.1, falling)", cols)[0]
    assert not evaluate("crosses(x, 5.0, rising)", cols)[0]
    assert evaluate("always(x >= 0.0)", cols)[0]
    assert not evaluate("always(x >= 0.6)", cols)[0]
    assert evaluate("final(x) <= 0.1", cols)[0]
    assert evaluate("at(x, 2) >= 0.9", cols)[0]


def test_before_handles_nested_calls():
    """A naive split on the first comma breaks before(crosses(a,1), crosses(b,2))."""
    cols = {"time": [0, 1, 2, 3], "a": [0.0, 1.0, 1.0, 1.0], "b": [0.0, 0.0, 0.0, 1.0]}
    ok, detail, _ = evaluate("before(crosses(a, 0.5, rising), crosses(b, 0.5, rising))", cols)
    assert ok, detail
    assert not evaluate("before(crosses(b, 0.5, rising), crosses(a, 0.5, rising))", cols)[0]


@pytest.mark.skipif(not TRACE.exists(), reason="reference trace not present")
def test_reference_trace_fails_the_conservation_screen():
    """The supplied trace creates NaCl during evaporation. Detecting that is the point:
    scoring signal RMSE against it would be scoring against bad data."""
    ok, notes = screen_reference(TRACE)
    assert not ok
    assert any("B5" in n for n in notes)
    # An ordinary drain (B3 empties at constant concentration) must NOT be flagged.
    assert not any(n.startswith("B3:") for n in notes)


def test_crossing_time_interpolates_on_the_sample_after():
    assert crossing_time([0, 1, 2], [0.0, 0.4, 0.9], 0.5) == 2
    assert crossing_time([0, 1, 2], [0.9, 0.4, 0.0], 0.5, rising=False) == 1
    assert crossing_time([0, 1], [0.0, 0.1], 0.5) is None


# ------------------------------------------------------------------------------ the gate


@pytest.mark.slow
@pytest.mark.skipif(not REF_MO.exists(), reason="reference model not present")
def test_hard_gate_reference_model_compiles_and_simulates():
    from specalive.verify.omc import OmcRunner

    runner = OmcRunner(workdir=str(ROOT / "out" / "work"))
    check = runner.check("GeneratedPlant.BAT09", [REF_MO, LIB_MO])
    assert check.ok, check.stdout[-2000:]
    sim = runner.simulate(
        "GeneratedPlant.BAT09", [REF_MO, LIB_MO], stop_time=3000, interval=5, prefix="pytest"
    )
    assert sim.ok, sim.stdout[-2000:]


@pytest.mark.slow
@pytest.mark.skipif(not (REF_IR.exists() and PACKET.exists()), reason="fixtures not present")
def test_full_pipeline_meets_the_gate(tmp_path):
    from specalive.pipeline import Pipeline, PipelineConfig

    cfg = PipelineConfig(packet=PACKET, out_dir=tmp_path, reference_ir=REF_IR, reference_trace=TRACE)
    result = Pipeline(cfg, router=None).run()
    assert result.gate.get("compiled"), [e.line() for e in result.events]
    assert result.gate.get("simulated"), [e.line() for e in result.events]

    card = result.scorecard
    assert card is not None
    # BAT09-04 is expected to fail: OPEN-ISSUE-01, an unreachable guard in the source data.
    failed = {r.check_id for r in card.results if not r.passed}
    assert failed == {"BAT09-04"}, f"unexpected acceptance failures: {failed}"

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["gate"]["compiled"] and report["gate"]["simulated"]
    assert report["reference_consistent"] is False
    assert any(g["id"] == "OPEN-ISSUE-01" for g in report["gaps"])


# --------------------------------------------------------------------------------- catalog


def test_component_record_parsing():
    """Three separate omc quirks bit here, two of them silently. Verbatim omc output."""
    from specalive.catalog.harvest import _parse_components, _variability

    raw = (
        '{{Modelica.Units.SI.Resistance, R, "Resistance at temperature T_ref", "public", '
        'false, false, false, false, "parameter", "none", "unspecified", {}}, '
        '{Modelica.Units.SI.Temperature, T_ref, "Reference temperature", "public", '
        'false, false, false, false, "parameter", "none", "unspecified", {}}, '
        '{Modelica.Units.SI.Resistance, R_actual, "Actual resistance", "public", '
        'false, false, false, false, "unspecified", "none", "unspecified", {}}}'
    )
    rows = _parse_components(raw)
    # A regex for "braces with no braces inside" matches only each record's trailing {},
    # which silently yields nothing. This must find all three records.
    assert len(rows) == 3
    assert rows[0][0] == "Modelica.Units.SI.Resistance" and rows[0][1] == "R"
    assert rows[0][2] == "Resistance at temperature T_ref"
    # Variability is located by value, not by index: the arity has drifted between omc
    # releases and the trailing "{}" collapses to an empty field.
    assert _variability(rows[0]) == "parameter"
    assert _variability(rows[2]) == "unspecified"


def test_component_parsing_tolerates_commas_inside_descriptions():
    from specalive.catalog.harvest import _parse_components

    raw = (
        '{{Real, alpha, "Coefficient (R = R0*(1 + a*(T - T_ref)), see docs", "public", '
        'false, false, false, false, "parameter", "none", "unspecified", {}}}'
    )
    rows = _parse_components(raw)
    assert len(rows) == 1
    assert rows[0][1] == "alpha"
    assert "see docs" in rows[0][2], rows[0]


def test_dead_subtrees_are_filtered_before_probing():
    """Type aliases and function packages cost four omc calls each and are then discarded.
    Cutting them before the expensive pass is what keeps a full MSL harvest tractable."""
    from specalive.catalog.harvest import _skip

    assert _skip("Modelica.Units.SI.Resistance")
    assert _skip("Modelica.Math.Vectors.norm")
    assert _skip("Modelica.Electrical.Analog.Examples.CauerLowPassAnalog")
    # ...but real components must survive
    assert not _skip("Modelica.Electrical.Analog.Basic.Resistor")
    assert not _skip("Modelica.Mechanics.Rotational.Components.Inertia")
    assert not _skip("Modelica.Electrical.Analog.Interfaces.PositivePin")


def test_base_classes_are_probed_but_never_emitted():
    """MSL declares a component's connectors in a partial base class. Skipping base classes
    in the probe pass makes the harvest faster and silently strips the ports off everything
    that inherits them -- Modelica.Fluid.Vessels.OpenTank came back with an empty port list.
    They must be probed for inheritance and filtered only at emit time."""
    from specalive.catalog.harvest import _parent_only, _skip

    base = "Modelica.Fluid.Vessels.BaseClasses.PartialLumpedVessel"
    assert not _skip(base), "base classes must still be probed, or inheritance cannot resolve"
    assert _parent_only(base), "base classes must not appear in the catalog"
    assert not _parent_only("Modelica.Fluid.Vessels.OpenTank")


def test_retrieval_covers_blocks_not_just_models():
    """A controller is a `block`, not a `model`. Defaulting the restriction filter to models
    alone hid every controller in the library from retrieval."""
    from specalive.catalog.harvest import CatalogEntry
    from specalive.catalog.retrieve import CatalogIndex

    entries = [
        CatalogEntry("X.PID", "X", "signal", "block", "PID controller in additive form"),
        CatalogEntry("X.Tank", "X", "fluid", "model", "Open tank with ports"),
    ]
    ix = CatalogIndex(entries)
    hits = ix.search("PID controller", k=5, domain="signal")
    assert hits and hits[0].entry.key == "X.PID"


def test_probe_script_escapes_newlines_for_mos():
    """A real newline inside the marker would split the .mos statement. It must be the
    two-character escape that Modelica expects."""
    from specalive.catalog.harvest import _probe_script

    script = _probe_script("loadModel(Modelica);\n", ["Modelica.Electrical.Analog.Basic.Resistor"])
    assert r'@@KEY Modelica.Electrical.Analog.Basic.Resistor\n' in script
    assert r'@@INH\n' in script
    # getComponents/getInheritedClasses must NOT be wrapped in print(): String() on a
    # list-of-lists returns nothing and aborts the rest of the script.
    assert "print(\"@@CMP" not in script
    assert "cmp0 := getComponents(" in script
    assert "inh0 := getInheritedClasses(" in script


# --------------------------------------------------------------- reference-data screens (D4)


def _csv(tmp_path, name, header, rows):
    import csv as _csv_mod

    p = tmp_path / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = _csv_mod.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return p


def test_screen_rejects_an_impossible_rotational_overshoot(tmp_path):
    """A constant torque into an inertia with linear damping is first order. It cannot
    overshoot, so a trace that does is not a solution of the system it claims to describe."""
    import math as _m

    rows = [[i * 0.05, 12.5 * (1 - _m.exp(-0.5 * i * 0.05) * _m.cos(2.0 * i * 0.05)), 2.0]
            for i in range(400)]
    ok, notes = screen_reference(_csv(tmp_path, "over.csv", ["time", "J2.w", "M1.tau"], rows))
    assert not ok
    assert any("overshoot" in n for n in notes), notes


def test_screen_accepts_a_clean_first_order_spinup(tmp_path):
    import math as _m

    rows = [[i * 0.05, 12.5 * (1 - _m.exp(-(i * 0.05) / 2)), 2.0] for i in range(400)]
    ok, _ = screen_reference(_csv(tmp_path, "ok.csv", ["time", "J2.w", "M1.tau"], rows))
    assert ok


def test_screen_catches_energy_flowing_the_wrong_way(tmp_path):
    rows = [[i * 1.0, 20.0 + i * 0.05, 1] for i in range(60)]
    ok, notes = screen_reference(
        _csv(tmp_path, "warm.csv", ["time", "B6_temp_C", "B6_cooler_cmd"], rows)
    )
    assert not ok
    assert any("wrong way" in n for n in notes), notes


def test_speed_detection_does_not_mistake_a_mass_fraction_for_a_speed(tmp_path):
    """`B5_w_NaCl` is a NaCl mass fraction. An earlier pattern matched `_w_` and reported a
    chemical composition as an impossible rotational overshoot."""
    rows = [[i * 5.0, 0.08 + 0.1 * (i / 100), 0.18 if i > 50 else 0.08] for i in range(101)]
    ok, notes = screen_reference(
        _csv(tmp_path, "conc.csv", ["time", "B5_w_NaCl", "B5_other"], rows)
    )
    assert not any("overshoot" in n for n in notes), notes


@pytest.mark.skipif(not REF_IR.exists(), reason="reference IR not built")
def test_screen_consults_the_ir_for_facts_the_columns_do_not_carry(tmp_path):
    """omc eliminates a constant source torque as a parameter alias, so `M1.tau` never
    appears in the result. Column-name guessing then concludes there is no constant drive
    and skips the screen; the IR knows better."""
    import math as _m

    from specalive.verify.acceptance import _system_facts

    drive_ir = ROOT / "benchmarks" / "drivetrain" / "reference_ir.json"
    if not drive_ir.exists():
        pytest.skip("drivetrain IR not built")
    model = SystemModel.model_validate_json(drive_ir.read_text(encoding="utf-8"))
    assert _system_facts(model)["constant_drive"] is True
    assert _system_facts(None)["constant_drive"] is None

    # No torque column at all, so only the IR can say the drive is constant.
    rows = [[i * 0.05, 12.5 * (1 - _m.exp(-0.5 * i * 0.05) * _m.cos(2.0 * i * 0.05))]
            for i in range(400)]
    path = _csv(tmp_path, "notorque.csv", ["time", "J2.w"], rows)
    ok_with, notes = screen_reference(path, model)
    assert not ok_with, "with the IR, the overshoot must be caught"
    assert any("overshoot" in n for n in notes)


def test_a_trace_with_nothing_screenable_is_not_silently_endorsed(tmp_path):
    rows = [[i, i * 2] for i in range(20)]
    ok, notes = screen_reference(_csv(tmp_path, "opaque.csv", ["time", "some_column"], rows))
    assert ok, "we cannot reject what we cannot check"
    assert any("neither endorsed nor rejected" in n for n in notes), notes
def test_partial_classes_are_excluded_by_the_compiler_not_by_their_name():
    """C7. Name heuristics catch `*.BaseClasses.*` and `Partial*`, but MSL has partial classes
    that match neither -- Modelica.Thermal.HeatTransfer.Interfaces.Element1D is partial, is not
    named Partial*, and does not live under BaseClasses. It reached the catalog and outranked
    ThermalConductor. `isPartial()` from omc makes the filter exact instead of approximate.

    The partial flag must be read at EMIT time only: partial bases are still probed, because
    _collect_rows walks the inheritance chain through them to recover ports (D24)."""
    from specalive.catalog.harvest import _build_entries, _probe_script

    # The probe must ask omc, and must not wrap the answer in a bare String() of a list.
    script = _probe_script("loadModel(Modelica);\n", ["Modelica.Fluid.Vessels.OpenTank"])
    assert "par0 := isPartial(Modelica.Fluid.Vessels.OpenTank);" in script
    assert r'@@PAR " + String(par0)' in script

    # A partial class is probed (its rows are available to children) but never emitted.
    meta = (
        "@@KEY Demo.PartialThing\n"
        '@@RES "model"\n'
        '@@COM "shared base"\n'
        "@@PAR true\n"
        '{{"Modelica.Thermal.HeatTransfer.Interfaces.HeatPort_a","port_a","a port",'
        '"public","false","false","false","false","unspecified","none","unspecified"},{}}\n'
        "@@INH\n"
        "{}\n"
        "@@KEY Demo.RealThing\n"
        '@@RES "model"\n'
        '@@COM "an instantiable component"\n'
        "@@PAR false\n"
        '{{"Modelica.Units.SI.Length","L","length","public","false","false","false","false",'
        '"parameter","none","unspecified"},{}}\n'
        "@@INH\n"
        "{}\n"
    )
    keys = {e.key for e in _build_entries(meta, ("model",))}
    assert "Demo.RealThing" in keys
    assert "Demo.PartialThing" not in keys, "a partial class must not reach the catalog"
