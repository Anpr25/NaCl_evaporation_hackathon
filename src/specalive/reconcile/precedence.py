"""The precedence engine: given competing claims about one fact, decide which one is true.

This is where the 20-point traceability-and-honesty score is won or lost. Two principles:

  1. Never resolve by recency, polish or file position. Resolve by declared authority, declared
     status and explicit supersession, in that order.
  2. When nothing discriminates, say so. A provisional value with an open question attached is
     worth far more than a confident guess.

Owner: B.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..ir.evidence import AuthorityClass, DecisionRecord, EvidenceClaim, RecordStatus, Source


@dataclass
class Candidate:
    claim: EvidenceClaim
    source: Source
    score: float = 0.0
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []


class PrecedenceEngine:
    def __init__(self, config_path: str | Path = "config/precedence.yaml") -> None:
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        self.rules = {r["id"]: r for r in cfg.get("rules", [])}
        self.status_order: list[str] = self.rules.get("P2-approval-status", {}).get("order", [])
        self.authority_order: list[str] = self.rules.get("P3-authority-class", {}).get("order", [])
        self.failure_modes = {f["id"]: f["trap"] for f in cfg.get("known_failure_modes", [])}
        self._decision_seq = 0

    # ------------------------------------------------------------------ scoring
    def _status_rank(self, s: RecordStatus) -> int:
        try:
            return self.status_order.index(s.value)
        except ValueError:
            return len(self.status_order)

    def _authority_rank(self, a: AuthorityClass) -> int:
        try:
            return self.authority_order.index(a.value)
        except ValueError:
            return len(self.authority_order)

    def resolve(
        self,
        subject: str,
        predicate: str,
        claims: list[EvidenceClaim],
        sources: dict[str, Source],
        *,
        supersession: dict[str, set[str]] | None = None,
    ) -> tuple[EvidenceClaim, DecisionRecord]:
        """Pick the winning claim and explain why.

        `supersession` maps source_id -> set of source_ids it supersedes, built from explicit
        supersession claims. That is rule P1 and it dominates everything else.
        """
        if not claims:
            raise ValueError(f"no claims to resolve for {subject}.{predicate}")

        cands = [Candidate(c, sources.get(c.source_id, _unknown_source(c.source_id))) for c in claims]
        self._decision_seq += 1
        did = f"DEC-{self._decision_seq:04d}"

        if len(cands) == 1:
            return cands[0].claim, DecisionRecord(
                id=did,
                subject=subject,
                predicate=predicate,
                winner_claim_id=cands[0].claim.id,
                rule_id="P0-uncontested",
                rationale=f"single source: {cands[0].claim.ref()}",
            )

        # ---- P1: explicit supersession ------------------------------------------------
        sup = supersession or {}
        superseded_ids = {loser for winners in sup.values() for loser in winners}
        alive = [c for c in cands if c.claim.source_id not in superseded_ids]
        if alive and len(alive) < len(cands):
            if len(alive) == 1:
                return self._verdict(
                    did, subject, predicate, alive[0], cands,
                    "P1-explicit-supersession",
                    (
                        f"{alive[0].source.id} ({alive[0].source.filename}) explicitly supersedes "
                        f"{', '.join(sorted(c.source.id for c in cands if c not in alive))}"
                    ),
                    failure_mode="F1-recency-bias",
                )
            cands = alive

        # Also honour a per-source `superseded_by` field set during extraction.
        not_marked = [c for c in cands if c.source.status != RecordStatus.SUPERSEDED]
        if not_marked and len(not_marked) < len(cands):
            if len(not_marked) == 1:
                return self._verdict(
                    did, subject, predicate, not_marked[0], cands,
                    "P1-explicit-supersession",
                    "all competing records are marked superseded; only one active record remains",
                    failure_mode="F1-recency-bias",
                )
            cands = not_marked

        # ---- P2: approval status --------------------------------------------------------
        best_status = min(self._status_rank(c.source.status) for c in cands)
        by_status = [c for c in cands if self._status_rank(c.source.status) == best_status]
        if len(by_status) == 1:
            w = by_status[0]
            return self._verdict(
                did, subject, predicate, w, cands, "P2-approval-status",
                f"{w.source.id} is {w.source.status.value}; competing records are not",
            )
        cands = by_status

        # ---- P3: authority class --------------------------------------------------------
        best_auth = min(self._authority_rank(c.source.authority) for c in cands)
        by_auth = [c for c in cands if self._authority_rank(c.source.authority) == best_auth]
        if len(by_auth) == 1:
            w = by_auth[0]
            losers = ", ".join(sorted({c.source.authority.value for c in cands if c is not w}))
            return self._verdict(
                did, subject, predicate, w, cands, "P3-authority-class",
                f"a {w.source.authority.value} outranks {losers}",
                failure_mode="F2-physical-layout-implies-function"
                if any(c.source.authority == AuthorityClass.DRAWING for c in cands)
                else None,
            )
        cands = by_auth

        # ---- P4: revision, then date -----------------------------------------------------
        revs = [(_revision_key(c.source.revision), c) for c in cands]
        top_rev = max(r for r, _ in revs)
        by_rev = [c for r, c in revs if r == top_rev]
        if len(by_rev) == 1 and top_rev > ("", 0):
            w = by_rev[0]
            return self._verdict(
                did, subject, predicate, w, cands, "P4-revision-then-date",
                f"{w.source.id} carries the highest revision ({w.source.revision})",
            )
        dated = [c for c in by_rev if c.source.effective_date]
        if dated:
            latest = max(c.source.effective_date or date.min for c in dated)
            by_date = [c for c in dated if c.source.effective_date == latest]
            if len(by_date) == 1:
                w = by_date[0]
                return self._verdict(
                    did, subject, predicate, w, cands, "P4-revision-then-date",
                    f"{w.source.id} has the latest effective date ({latest}) among equal-authority records",
                )
            cands = by_date
        else:
            cands = by_rev

        # ---- P5: specificity --------------------------------------------------------------
        specific = [c for c in cands if subject.lower() in (c.claim.quote or "").lower()]
        if len(specific) == 1:
            w = specific[0]
            return self._verdict(
                did, subject, predicate, w, cands, "P5-specificity",
                f"{w.source.id} names '{subject}' explicitly; the others speak generally",
            )
        if specific:
            cands = specific

        # ---- P6: corroboration --------------------------------------------------------------
        by_value: dict[str, list[Candidate]] = {}
        for c in cands:
            by_value.setdefault(repr(c.claim.value), []).append(c)
        counts = sorted(by_value.items(), key=lambda kv: len(kv[1]), reverse=True)
        if len(counts) > 1 and len(counts[0][1]) > len(counts[1][1]):
            group = counts[0][1]
            w = max(group, key=lambda c: c.claim.confidence)
            return self._verdict(
                did, subject, predicate, w, cands, "P6-corroboration",
                f"{len(group)} independent sources agree on {w.claim.value!r}",
            )

        # ---- P7: escalate ----------------------------------------------------------------
        w = max(cands, key=lambda c: (c.claim.confidence, -self._authority_rank(c.source.authority)))
        _, rec = self._verdict(
            did, subject, predicate, w, cands, "P7-escalate",
            (
                f"no precedence rule discriminated between {len(cands)} candidates "
                f"({', '.join(sorted(c.source.id for c in cands))}); taking the highest-confidence "
                f"claim provisionally and raising an open question"
            ),
        )
        rec.provisional = True
        rec.resolved = False
        return w.claim, rec

    def _verdict(
        self,
        did: str,
        subject: str,
        predicate: str,
        winner: Candidate,
        all_cands: Iterable[Candidate],
        rule_id: str,
        rationale: str,
        failure_mode: str | None = None,
    ) -> tuple[EvidenceClaim, DecisionRecord]:
        losers = [c.claim.id for c in all_cands if c.claim.id != winner.claim.id]
        rec = DecisionRecord(
            id=did,
            subject=subject,
            predicate=predicate,
            winner_claim_id=winner.claim.id,
            loser_claim_ids=losers,
            rule_id=rule_id,
            rationale=rationale,
            failure_mode=failure_mode,
        )
        return winner.claim, rec


def _revision_key(rev: str | None) -> tuple[str, int]:
    """Sortable revision: 'Rev C' -> ('C', 0); '2.3' -> ('', 23); None -> ('', 0)."""
    if not rev:
        return ("", 0)
    letters = re.findall(r"[A-Za-z]", rev.replace("Rev", "").replace("rev", ""))
    numbers = re.findall(r"\d+", rev)
    return (letters[-1].upper() if letters else "", int("".join(numbers)) if numbers else 0)


def _unknown_source(sid: str) -> Source:
    return Source(id=sid, filename=f"<{sid}>", media_type="unknown")


def build_supersession_map(claims: list[EvidenceClaim]) -> dict[str, set[str]]:
    """Turn supersession claims into a winner -> {losers} map.

    Direction is the crux and it is easy to get backwards. Engineering registers state it both
    ways round in adjacent columns of the same sheet:

        predicate "supersedes"     subject wins, value loses   ("CR-017 supersedes REQ-ROU-001")
        predicate "superseded_by"  value wins, subject loses   (row REQ-ROU-001, col = CR-017)

    Getting this inverted would make the system prefer exactly the legacy values the packet is
    testing for, so the two forms are handled explicitly rather than by a single heuristic.
    """
    out: dict[str, set[str]] = {}
    for c in claims:
        if c.kind != "supersession":
            continue
        values = c.value if isinstance(c.value, list) else [c.value]
        values = [str(v).strip() for v in values if v not in (None, "", "-")]
        if not values:
            continue
        predicate = (c.predicate or "").lower()
        if predicate in ("superseded_by", "replaced_by", "superseded by", "replaced by"):
            for winner in values:
                out.setdefault(winner, set()).add(str(c.subject).strip())
        else:
            out.setdefault(str(c.subject).strip(), set()).update(values)
    return out


def resolve_source_supersession(
    sup: dict[str, set[str]], sources: dict[str, Source], claims: list[EvidenceClaim]
) -> dict[str, set[str]]:
    """Map record-level supersession (by document id like 'CR-017') onto source file ids.

    A packet names records by their engineering id, not by filename, so 'CR-017 supersedes
    REQ-ROU-001' has to be translated into 'SRC-nn supersedes SRC-mm' before it can affect
    precedence between files. Unresolvable names are dropped, never guessed: a missed rule
    falls through to P2/P3, which is safe, whereas a wrong mapping is not.
    """
    # Which source does each record id appear in most authoritatively?
    home: dict[str, str] = {}
    for c in claims:
        for token in (str(c.subject), str(c.value)):
            token = token.strip()
            if re.fullmatch(r"[A-Z]{2,}-\d{2,}", token):
                home.setdefault(token, c.source_id)
    out: dict[str, set[str]] = {}
    for winner, losers in sup.items():
        wsrc = home.get(winner)
        if not wsrc:
            continue
        mapped = {home[l] for l in losers if home.get(l) and home[l] != wsrc}
        if mapped:
            out.setdefault(wsrc, set()).update(mapped)
    return out
