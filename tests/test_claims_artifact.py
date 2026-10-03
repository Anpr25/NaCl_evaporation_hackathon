"""The claims-only JSON artifact: the extracted evidence trail, as its own structured file
and schema, independent of the full IR dump."""

from __future__ import annotations

import json
from pathlib import Path

from specalive.ir.evidence import EvidenceClaim, Locator
from specalive.ir.system import SystemModel
from specalive.pipeline import _write_claims


def _claim(**over) -> EvidenceClaim:
    base = dict(id="C1", source_id="SRC-01", kind="parameter", subject="B1",
                predicate="level_max", value=2.5, unit="m",
                locator=Locator(sheet="Params", cell="B4"))
    base.update(over)
    return EvidenceClaim(**base)


def test_claims_json_is_a_flat_array_of_the_extracted_claims(tmp_path: Path):
    model = SystemModel(name="t", claims=[_claim(), _claim(id="C2", subject="B2", value=10)])
    path = _write_claims(tmp_path, model)
    assert path == tmp_path / "claims.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["id"] == "C1" and data[0]["subject"] == "B1"
    assert data[0]["value"] == 2.5 and data[0]["unit"] == "m"
    # The locator survived as a structured object, not flattened into a rendered string --
    # that rendering (Locator.render()) is for human display, not for a machine consumer.
    assert data[0]["locator"]["sheet"] == "Params" and data[0]["locator"]["cell"] == "B4"


def test_claims_schema_validates_the_claims_file(tmp_path: Path):
    model = SystemModel(name="t", claims=[_claim()])
    _write_claims(tmp_path, model)
    schema = json.loads((tmp_path / "claims.schema.json").read_text(encoding="utf-8"))
    assert schema.get("title") == "EvidenceClaim"
    claims = json.loads((tmp_path / "claims.json").read_text(encoding="utf-8"))
    required = set(schema.get("required", []))
    # Every field the schema says is required is present on the claim this run actually wrote.
    assert required <= set(claims[0].keys())


def test_an_empty_claims_list_still_writes_a_valid_empty_array(tmp_path: Path):
    model = SystemModel(name="t")
    path = _write_claims(tmp_path, model)
    assert json.loads(path.read_text(encoding="utf-8")) == []
