"""Evidence and decision records.

This is the traceability substrate. Every value that reaches the SysML or Modelica output must
be reachable back to one of these records, and every conflict must be explained by one of these
decisions. Owner: B, consumed by A (produces claims) and D (renders them).

FROZEN CONTRACT -- coordinate any change across all four workstreams.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AuthorityClass(str, Enum):
    """How much weight a kind of document carries. See config/precedence.yaml rule P3."""

    CHANGE_RECORD = "change_record"
    APPROVED_REVIEW = "approved_review"
    INTERFACE_CONTROL = "interface_control"
    SPECIFICATION = "specification"
    DATASHEET = "datasheet"
    REGISTER = "register"
    TEST_PROCEDURE = "test_procedure"
    DRAWING = "drawing"
    LEGACY_MODEL = "legacy_model"
    TEST_RESULT = "test_result"
    CORRESPONDENCE = "correspondence"
    INFORMAL_NOTE = "informal_note"
    UNKNOWN = "unknown"


class RecordStatus(str, Enum):
    APPROVED = "approved"
    DRAFT = "draft"
    LEGACY = "legacy"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class Locator(BaseModel):
    """Where inside a source a claim came from. At least one field must be set.

    Rendered as a human string like ``SRC-02!Requirements!A4`` or ``SRC-01#p2:L17``.
    """

    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="x0,y0,x1,y1 in page or image coordinates, for diagrams"
    )
    section: str | None = None

    def render(self) -> str:
        bits: list[str] = []
        if self.sheet:
            bits.append(self.sheet)
        if self.cell:
            bits.append(self.cell)
        if self.page is not None:
            bits.append(f"p{self.page}")
        if self.section:
            bits.append(self.section)
        if self.line_start is not None:
            span = f"L{self.line_start}"
            if self.line_end and self.line_end != self.line_start:
                span += f"-{self.line_end}"
            bits.append(span)
        return "!".join(bits) if bits else "whole-document"


class Source(BaseModel):
    """One input file in the evidence packet."""

    id: str = Field(description="Stable short id, e.g. SRC-04")
    filename: str
    media_type: str
    authority: AuthorityClass = AuthorityClass.UNKNOWN
    status: RecordStatus = RecordStatus.UNKNOWN
    revision: str | None = None
    effective_date: date | None = None
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    sha256: str | None = None
    notes: str | None = None

    #: How the authority/status were determined: "declared" (the document says so),
    #: "heuristic" (matched config/precedence.yaml hints) or "model" (an LLM classified it).
    classification_basis: Literal["declared", "heuristic", "model"] = "heuristic"


ClaimKind = Literal[
    "requirement",
    "parameter",
    "component",
    "port",
    "connection",
    "signal",
    "state",
    "transition",
    "interlock",
    "scenario",
    "acceptance_check",
    "ownership",
    "supersession",
    "domain_hint",
    "note",
]


class EvidenceClaim(BaseModel):
    """A single typed assertion lifted out of one place in one source.

    Claims are deliberately small and flat. The reconciler, not the extractor, decides what is
    true; the extractor only reports what a document says and where it says it.
    """

    id: str
    source_id: str
    locator: Locator = Field(default_factory=Locator)
    kind: ClaimKind
    subject: str = Field(description="Tag or name the claim is about, e.g. 'B5' or 'SP-B7-COOL'")
    predicate: str = Field(description="Attribute asserted, e.g. 'cooling_target' or 'connects_to'")
    value: Any = Field(description="Asserted value, already unit-normalised where possible")
    unit: str | None = None
    quote: str = Field(default="", description="Verbatim snippet supporting the claim")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    #: Which tier produced it, e.g. "t0_deterministic" or "t1_local_small". Deterministic
    #: claims should dominate; a high LLM share is a smell worth showing in the report.
    extracted_by: str = "t0_deterministic"

    def ref(self) -> str:
        return f"{self.source_id}!{self.locator.render()}"


class DecisionRecord(BaseModel):
    """Why one claim beat the others. The core artefact of the honesty score."""

    id: str
    subject: str
    predicate: str
    winner_claim_id: str
    loser_claim_ids: list[str] = Field(default_factory=list)
    rule_id: str = Field(description="Which precedence rule discriminated, e.g. 'P1-explicit-supersession'")
    rationale: str = Field(description="One or two sentences a reviewing engineer would accept")
    resolved: bool = True
    provisional: bool = Field(
        default=False, description="True when no rule discriminated and a value was assumed"
    )
    failure_mode: str | None = Field(
        default=None, description="Known trap this decision avoided, e.g. 'F2-physical-layout-implies-function'"
    )

    def render(self) -> str:
        verdict = "PROVISIONAL" if self.provisional else "resolved"
        return f"[{verdict}] {self.subject}.{self.predicate} via {self.rule_id}: {self.rationale}"


class Gap(BaseModel):
    """Something we could not do, said out loud. Never let these be silent."""

    id: str
    kind: Literal[
        "unextracted",        # evidence existed but we could not read it
        "unresolved_conflict",
        "unmapped_component",  # no catalog entry, no template
        "unimplemented_requirement",
        "unreachable_guard",
        "inconsistent_reference_data",
        "deviation",           # we deliberately did something other than what was specified
    ]
    subject: str
    detail: str
    requirement_ids: list[str] = Field(default_factory=list)
    severity: Literal["info", "warn", "blocking"] = "warn"
    workaround: str | None = None


class Assumption(BaseModel):
    """Something the evidence did not say, that we filled in and said so.

    The brief is explicit: missing information must be "inferred with a stated assumption,
    or surfaced as a question", and never silently invented. An Assumption is the first of
    those two, and it is a separate record from a Gap on purpose -- a gap is something we
    could not do, an assumption is something we *did* on our own authority, and a reviewer
    needs to find those without reading past twenty warnings.

    `basis` is the important field. An assumption that cites a named standard convention is
    defensible engineering; one that cites nothing is a guess wearing a label.
    """

    id: str
    subject: str = Field(description="IR element the assumption was applied to")
    statement: str = Field(description="What we assumed, in one sentence a reviewer can judge")
    value: Any = None
    unit: str | None = None
    #: Id from config/assumptions.yaml, or None when nothing standard covered it.
    basis: str | None = None
    basis_text: str | None = None
    what_was_missing: str = Field(description="The fact the evidence never stated")
    impact_if_wrong: str | None = Field(
        default=None, description="What a reviewer should re-check if they disagree"
    )
    #: The question we would ask to make this unnecessary. Links assumption to question.
    question_id: str | None = None


class Question(BaseModel):
    """Something we could not settle and are asking the customer, rather than guessing.

    The second half of the brief's rule. A question is not a failure: on an incomplete
    packet it is often the correct output, and a system that asks three sharp questions is
    worth more than one that silently invents three numbers.
    """

    id: str
    subject: str
    question: str = Field(description="Phrased so a process engineer could answer it directly")
    why_it_matters: str
    #: True when nothing downstream can be trusted until this is answered.
    blocking: bool = False
    #: Where we looked before asking, so the reader knows this is not laziness.
    searched: list[str] = Field(default_factory=list)
    #: What we did in the meantime, if anything.
    interim: str | None = None
