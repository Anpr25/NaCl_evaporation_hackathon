"""The declared standard-assumption register, and the helper that cites it.

The brief permits the system to fill a hole "with a stated assumption", and permits physics
"derivable from the input or from a declared standard assumption". Both clauses turn on the
word *declared*: an assumption invented at the moment it is needed, to excuse whatever the
code just did, is not a declared assumption -- it is a rationalisation with better manners.

So the conventions live in config/assumptions.yaml, written before the code that uses them,
and this module is the only way to spend one. `assume()` rejects a basis that is not in the
register, but accepts basis=None explicitly -- an unfounded inference is allowed, because
forbidding it would just push people back to inventing values silently. It is counted instead:
`assumptions_unfounded` appears in coverage() and the report prints it whether or not it is
flattering.

Owner: D.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .evidence import Assumption, Question

DEFAULT_REGISTER = "config/assumptions.yaml"

_cache: dict[str, dict[str, dict[str, Any]]] = {}


def _candidate_paths(path: str | Path) -> list[Path]:
    """Look in the cwd first, then beside the installed package.

    The CLI runs from the repo root, the tests run from anywhere, and the web app runs from
    wherever uvicorn was started. All three need to find the same register.
    """
    p = Path(path)
    if p.is_absolute():
        return [p]
    here = Path(__file__).resolve()
    return [r / p for r in [Path.cwd(), *here.parents[:4]]]


def load_register(path: str | Path = DEFAULT_REGISTER) -> dict[str, dict[str, Any]]:
    """Return {assumption_id: entry}.

    A missing register is not fatal: it means no basis is available, every inference comes out
    unfounded, and the report says so loudly. That is the right failure -- degrade to visible
    guessing, never to silent guessing.
    """
    key = str(path)
    if key in _cache:
        return _cache[key]
    entries: dict[str, dict[str, Any]] = {}
    for candidate in _candidate_paths(path):
        if not candidate.is_file():
            continue
        doc = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        for entry in doc.get("assumptions", []) or []:
            if entry.get("id"):
                entries[entry["id"]] = entry
        break
    _cache[key] = entries
    return entries


def clear_cache() -> None:  # pragma: no cover - test hook
    _cache.clear()


class AssumptionLog:
    """Collects assumptions and questions during a run and hands out stable ids.

    One of these is threaded through completion and emission so every inference lands in the
    same numbered list, and an assumption that has a matching question carries its id.
    """

    def __init__(self, register_path: str | Path = DEFAULT_REGISTER) -> None:
        self.register = load_register(register_path)
        self.assumptions: list[Assumption] = []
        self.questions: list[Question] = []

    # ------------------------------------------------------------------ recording
    def assume(
        self,
        subject: str,
        statement: str,
        *,
        basis: str | None,
        what_was_missing: str,
        value: Any = None,
        unit: str | None = None,
        impact_if_wrong: str | None = None,
        question_id: str | None = None,
    ) -> Assumption:
        """Record an inference. `basis` is a register id, or None for an unfounded one.

        An id that is not in the register raises. It would otherwise produce an assumption
        that looks declared and is not, which is the exact failure the register prevents.
        """
        if basis is not None and basis not in self.register:
            raise KeyError(
                f"assumption basis {basis!r} is not in the register; add it to "
                f"{DEFAULT_REGISTER} before using it, or pass basis=None to record it "
                f"as unfounded"
            )
        entry = self.register.get(basis or "", {})
        record = Assumption(
            id=f"ASM-{len(self.assumptions) + 1:02d}",
            subject=subject,
            statement=statement,
            value=value,
            unit=unit,
            basis=basis,
            basis_text=(entry.get("title") if entry else None),
            what_was_missing=what_was_missing,
            impact_if_wrong=impact_if_wrong or (entry.get("challenge") if entry else None),
            question_id=question_id,
        )
        self.assumptions.append(record)
        return record

    def ask(
        self,
        subject: str,
        question: str,
        *,
        why_it_matters: str,
        blocking: bool = False,
        searched: list[str] | None = None,
        interim: str | None = None,
    ) -> Question:
        record = Question(
            id=f"Q-{len(self.questions) + 1:02d}",
            subject=subject,
            question=question,
            why_it_matters=why_it_matters,
            blocking=blocking,
            searched=searched or [],
            interim=interim,
        )
        self.questions.append(record)
        return record

    def assume_and_ask(
        self,
        *,
        subject: str,
        statement: str,
        basis: str | None,
        what_was_missing: str,
        question: str,
        why_it_matters: str,
        value: Any = None,
        unit: str | None = None,
        searched: list[str] | None = None,
        blocking: bool = False,
    ) -> tuple[Assumption, Question]:
        """The common case: proceed on an assumption AND ask so it can be replaced.

        The brief says "either ... or", but doing both is strictly better than either: the
        model runs, and the customer still gets the question that makes the guess unnecessary.
        """
        q = self.ask(
            subject,
            question,
            why_it_matters=why_it_matters,
            blocking=blocking,
            searched=searched,
            interim=f"Proceeding on {statement}",
        )
        a = self.assume(
            subject,
            statement,
            basis=basis,
            what_was_missing=what_was_missing,
            value=value,
            unit=unit,
            question_id=q.id,
        )
        return a, q

    # ------------------------------------------------------------------ output
    def attach(self, model: Any) -> None:
        """Merge into the IR, renumbering to continue the model's existing sequence.

        Every log numbers from 1, and a run uses more than one -- emission keeps its own, and
        so does post-simulation diagnosis. Merging by id alone silently dropped the second
        log's records as duplicates, which lost two blocking questions about a contradiction
        the run had just proved. Renumber instead, and carry the assumption -> question
        back-references across with the new ids.
        """
        renamed: dict[str, str] = {}
        next_q = len(model.questions)
        for q in self.questions:
            next_q += 1
            new_id = f"Q-{next_q:02d}"
            renamed[q.id] = new_id
            q.id = new_id
            model.questions.append(q)

        next_a = len(model.assumptions)
        for a in self.assumptions:
            next_a += 1
            a.id = f"ASM-{next_a:02d}"
            if a.question_id:
                a.question_id = renamed.get(a.question_id, a.question_id)
            model.assumptions.append(a)

    @property
    def unfounded(self) -> list[Assumption]:
        return [a for a in self.assumptions if not a.basis]
