"""Claims -> a single validated SystemModel, with a DecisionRecord for every contested fact.

Shape of the job:

  1. group claims by (subject, predicate)             -- one group = one fact
  2. run every multi-claim group through the precedence engine
  3. assemble the surviving facts into IR elements
  4. attach provenance everywhere, and a Gap wherever something did not survive

Step 2 is done and is the part that carries the marks. Step 3 is mechanical assembly and is
scaffolded below with the grouping already in place.

Owner: B.  STATUS: precedence wiring complete; element assembly marked TODO per element type.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..ingest.base import Document
from ..ir.evidence import DecisionRecord, EvidenceClaim, Gap, Source
from ..ir.system import (
    AcceptanceCheck,
    Block,
    Connection,
    Parameter,
    Provenance,
    Quantity,
    Requirement,
    Scenario,
    Signal,
    StateMachine,
    SystemModel,
)
from .precedence import PrecedenceEngine, build_supersession_map, resolve_source_supersession


def group_claims(claims: list[EvidenceClaim]) -> dict[tuple[str, str], list[EvidenceClaim]]:
    """One group per fact. Subject matching is case-insensitive and whitespace-insensitive,
    because the same tag is written 'B5', 'b5' and 'B-5' across a real packet."""
    groups: dict[tuple[str, str], list[EvidenceClaim]] = defaultdict(list)
    for c in claims:
        key = (_norm(c.subject), _norm(c.predicate))
        groups[key].append(c)
    return dict(groups)


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def resolve_all(
    claims: list[EvidenceClaim],
    sources: dict[str, Source],
    engine: PrecedenceEngine,
) -> tuple[dict[tuple[str, str], EvidenceClaim], list[DecisionRecord]]:
    """Resolve every fact. Returns the winning claim per fact plus the full decision log."""
    record_sup = build_supersession_map(claims)
    source_sup = resolve_source_supersession(record_sup, sources, claims)

    winners: dict[tuple[str, str], EvidenceClaim] = {}
    decisions: list[DecisionRecord] = []
    for key, group in group_claims(claims).items():
        # Distinct values only: five sources agreeing is not a conflict, it is corroboration.
        distinct = {repr(c.value) for c in group}
        if len(distinct) == 1:
            winners[key] = max(group, key=lambda c: c.confidence)
            continue
        winner, decision = engine.resolve(
            group[0].subject, group[0].predicate, group, sources, supersession=source_sup
        )
        winners[key] = winner
        decisions.append(decision)
    return winners, decisions


def build_model(
    docs: list[Document],
    claims: list[EvidenceClaim],
    *,
    name: str | None = None,
    precedence_config: str | Path = "config/precedence.yaml",
) -> SystemModel:
    """Assemble the IR. See the TODOs: each is one workstream-B task, independently testable."""
    sources = {d.source.id: d.source for d in docs}
    engine = PrecedenceEngine(precedence_config)
    winners, decisions = resolve_all(claims, sources, engine)

    model = SystemModel(
        name=name or _infer_name(docs),
        description=None,
        sources=list(sources.values()),
        claims=claims,
        decisions=decisions,
    )

    model.requirements = _build_requirements(winners, claims)

    # TODO(B1) blocks:     group winners by subject where kind == "component"; infer domains
    #                      from the medium/port vocabulary; build Port objects from "port" and
    #                      "connection" claims. Mark physical_only when an ownership claim says
    #                      the item is manual/local, and abstracted_into when a legacy-model
    #                      claim merges it. Test: 10 blocks incl. K1 for the NaCl fixture.
    # TODO(B2) connections: from kind == "connection" claims; collapse series elements by
    #                      walking the from/to chain and recording the intermediates in
    #                      Connection.series_elements. Test: RET_A carries {P2,V20,V24,V25,V1,V3}.
    # TODO(B3) signals:    from kind == "signal" plus the instrument register; set owner from
    #                      ownership claims so manual devices never become controller outputs.
    # TODO(B4) fsm:        from kind == "state"/"transition"; regions from the region column;
    #                      forks/joins from a split/join marker. Test: 3 regions, 14 states.
    # TODO(B5) scenario:   from kind == "scenario"/"acceptance_check" in the test procedure.
    #
    # Until those land, `--reference-ir` supplies a hand-built IR so the rest of the pipeline
    # is exercised end to end. Do not delete that path: it is also the extraction eval oracle.

    model.parameters = _build_parameters(winners, claims)
    model.gaps.extend(_unassembled_gaps(winners, model))
    return model


# ------------------------------------------------------------------------------- assembly


def _build_requirements(
    winners: dict[tuple[str, str], EvidenceClaim], claims: list[EvidenceClaim]
) -> list[Requirement]:
    by_subject: dict[str, dict[str, EvidenceClaim]] = defaultdict(dict)
    for (subject, predicate), claim in winners.items():
        by_subject[subject][predicate] = claim

    out: list[Requirement] = []
    for subject, facts in sorted(by_subject.items()):
        text_claim = facts.get("requirement")
        if text_claim is None:
            continue
        status_raw = str(facts["status"].value).lower() if "status" in facts else "active"
        superseded_by = facts.get("supersededby") or facts.get("superseded_by")
        out.append(
            Requirement(
                id=str(text_claim.subject),
                text=str(text_claim.value),
                category=str(facts["kind"].value) if "kind" in facts else None,
                priority=_priority(facts),
                status="superseded" if "supersed" in status_raw else "active",
                superseded_by=str(superseded_by.value) if superseded_by else None,
                authority=str(facts["authority"].value) if "authority" in facts else None,
                verification_method=str(facts["verification"].value) if "verification" in facts else None,
                provenance=Provenance(claim_ids=[c.id for c in facts.values()]),
            )
        )
    return out


def _build_parameters(
    winners: dict[tuple[str, str], EvidenceClaim], claims: list[EvidenceClaim]
) -> list[Parameter]:
    by_subject: dict[str, dict[str, EvidenceClaim]] = defaultdict(dict)
    for (subject, predicate), claim in winners.items():
        by_subject[subject][predicate] = claim

    out: list[Parameter] = []
    for subject, facts in sorted(by_subject.items()):
        value_claim = facts.get("value")
        if value_claim is None or not isinstance(value_claim.value, (int, float)):
            continue
        unit = value_claim.unit or (str(facts["unit"].value) if "unit" in facts else None)
        status_raw = str(facts["status"].value).lower() if "status" in facts else "effective"
        out.append(
            Parameter(
                id=str(value_claim.subject),
                name=str(facts["name"].value) if "name" in facts else str(value_claim.subject),
                quantity=Quantity(value=value_claim.value, unit=unit),
                description=str(facts["name"].value) if "name" in facts else None,
                status="superseded" if "supersed" in status_raw else "effective",
                provenance=Provenance(claim_ids=[c.id for c in facts.values()]),
            )
        )
    return out


def _unassembled_gaps(winners: dict[tuple[str, str], EvidenceClaim], model: SystemModel) -> list[Gap]:
    """Say out loud which claim kinds we lifted but did not yet turn into IR elements."""
    assembled = {"requirement", "parameter", "note", "supersession"}
    unused: dict[str, int] = defaultdict(int)
    for claim in winners.values():
        if claim.kind not in assembled:
            unused[claim.kind] += 1
    return [
        Gap(
            id=f"GAP-ASM-{i:02d}",
            kind="unextracted",
            subject=kind,
            detail=(
                f"{count} resolved '{kind}' claim(s) were extracted but the IR assembler does "
                f"not yet build that element type; supply --reference-ir or implement the TODO "
                f"in reconcile/builder.py"
            ),
            severity="warn",
        )
        for i, (kind, count) in enumerate(sorted(unused.items()), 1)
    ]


def _priority(facts: dict[str, EvidenceClaim]) -> str:
    raw = str(facts["priority"].value).lower() if "priority" in facts else ""
    for p in ("must", "should", "may"):
        if p in raw:
            return p
    return "unknown"


def _infer_name(docs: list[Document]) -> str:
    for d in docs:
        for b in d.blocks:
            if b.kind == "heading" and len(b.text) > 8:
                return b.text[:60]
    return "ExtractedSystem"
