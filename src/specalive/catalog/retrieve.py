"""Retrieval over the harvested catalog: BM25 always, embeddings when a local model is up.

The LLM is never asked "what Modelica class models a brine evaporator?". It is asked to choose
among a shortlist that we retrieved and that we know exists. That single inversion is what
makes a 3B model usable for this step.

Owner: C, with D wiring the embedding tier.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .harvest import CatalogEntry, load_catalog

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Hit:
    entry: CatalogEntry
    score: float
    why: str


class BM25:
    """Small, dependency-free BM25. Fast enough for 6k documents and works offline."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [tokenize(d) for d in docs]
        self.len = [len(d) for d in self.docs]
        self.avglen = sum(self.len) / len(self.len) if self.docs else 0.0
        self.tf = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query: str) -> list[float]:
        q = tokenize(query)
        out = [0.0] * len(self.docs)
        for i, tf in enumerate(self.tf):
            dl = self.len[i] or 1
            s = 0.0
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                idf = self.idf.get(term, 0.0)
                s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avglen))
            out[i] = s
        return out


class CatalogIndex:
    """Hybrid index. Embeddings are optional and additive: BM25 alone must still work."""

    def __init__(self, entries: list[CatalogEntry], embedder: Any | None = None) -> None:
        self.entries = entries
        self.bm25 = BM25([e.search_text() for e in entries])
        self.embedder = embedder
        self.vectors: list[list[float]] | None = None

    @classmethod
    def from_file(cls, path: str | Path = "out/catalog.jsonl", embedder: Any | None = None) -> CatalogIndex:
        return cls(load_catalog(path), embedder)

    def build_embeddings(self, cache_path: str | Path = "out/catalog_vectors.json") -> None:
        """One-off, ~6k short strings through nomic-embed-text. Cached to disk."""
        if self.embedder is None:
            return
        cache = Path(cache_path)
        if cache.exists():
            self.vectors = json.loads(cache.read_text(encoding="utf-8"))
            if len(self.vectors) == len(self.entries):
                return
        texts = [f"{e.key}: {e.comment}" for e in self.entries]
        self.vectors = self.embedder.embed(texts)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(self.vectors), encoding="utf-8")

    def search(
        self,
        query: str,
        *,
        k: int = 12,
        domain: str | None = None,
        restriction: tuple[str, ...] | str | None = ("model", "block"),
        library: str | None = None,
    ) -> list[Hit]:
        """Filter hard on structure, rank soft on text. Filters first: they are free and exact.

        `restriction` defaults to models AND blocks: a controller is a block, and defaulting
        to models alone silently hides every one of them from retrieval.
        """
        allowed = (restriction,) if isinstance(restriction, str) else restriction
        idx = [
            i
            for i, e in enumerate(self.entries)
            if (allowed is None or e.restriction in allowed)
            and (domain is None or e.domain == domain or e.domain == "unknown")
            and (library is None or e.library == library)
        ]
        if not idx:
            idx = list(range(len(self.entries)))

        lex = self.bm25.score(query)
        scores = {i: lex[i] for i in idx}

        if self.vectors is not None and self.embedder is not None:
            qv = self.embedder.embed([query])[0]
            for i in idx:
                scores[i] = 0.6 * scores[i] / (1 + abs(scores[i])) + 0.4 * _cosine(qv, self.vectors[i])

        ranked = sorted(idx, key=lambda i: scores[i], reverse=True)[:k]
        return [
            Hit(
                entry=self.entries[i],
                score=round(scores[i], 4),
                why="hybrid" if self.vectors else "bm25",
            )
            for i in ranked
            if scores[i] > 0
        ]

    def get(self, key: str) -> CatalogEntry | None:
        return next((e for e in self.entries if e.key == key), None)

    # ------------------------------------------------------------------ prompt surface
    @staticmethod
    def render_shortlist(hits: list[Hit], max_params: int = 8) -> str:
        """Compact candidate list for the picker prompt. Small models need this tight."""
        lines: list[str] = []
        for i, h in enumerate(hits):
            e = h.entry
            params = ", ".join(
                f"{p.name}{f' [{p.unit}]' if p.unit else ''}" for p in e.params[:max_params]
            )
            ports = ", ".join(f"{p.name}:{p.type.rsplit('.', 1)[-1]}" for p in e.ports)
            lines.append(
                f"{i}. {e.key}\n"
                f"   what: {e.comment or '(no description)'}\n"
                f"   domain: {e.domain}   ports: {ports or '(none)'}\n"
                f"   params: {params or '(none)'}"
            )
        return "\n".join(lines)


PICK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["choice", "confidence", "reason"],
    "properties": {
        # Answer by NAME, never by list position. Measured on the local-model bake-off: with
        # an index answer, a 4B model falls back to "0" whenever it is unsure, and two of its
        # three errors were exactly that. Copying a name out of the list is a different and
        # easier operation, and a name that was never offered is detectable as a
        # hallucination -- an out-of-range index is not always.
        "choice": {
            "type": "string",
            "description": "The full dotted Modelica class name, copied exactly from the "
                           "candidate list. Empty string if none of them fit.",
        },
        "confidence": {"type": "number", "description": "0 to 1"},
        "reason": {"type": "string", "description": "One sentence."},
        "parameter_map": {
            "type": "object",
            "description": "Source parameter name -> candidate parameter name",
        },
    },
}

PICK_PROMPT = """\
A component was extracted from engineering documentation:

  name:        {name}
  stated kind: {kind}
  description: {description}
  parameters:  {parameters}
  ports:       {ports}

Which of these verified Modelica classes models exactly that component?

{shortlist}

The candidates are in no particular order. Compare each description against the component
above.

Rules:
- Copy the class name exactly as written. Do not name a class that is not listed.
- If none of them models this component, answer with an empty choice.
- Map each source parameter onto a candidate parameter name where the meaning matches;
  leave it out if there is no genuine match.
- Answer JSON only:
  {{"choice": "Modelica.Some.Package.ClassName", "confidence": 0.9, "reason": "..."}}
"""


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)
