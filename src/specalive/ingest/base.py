"""Normalise any input file into a common Document shape.

One rule governs this layer: **structure first**. Anything a parser can read exactly -- a
spreadsheet cell, a CSV column, a JSON key, a PlantUML edge, a Modelica declaration -- must be
read by a parser and never by a model. On the NaCl packet that alone covers most of the
evidence, which is why the pipeline runs on a 3B.

An adapter's job is to produce Blocks with accurate Locators. It does not interpret. The
extractor turns blocks into typed claims; the reconciler decides what is true.

Owner: A.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from ..ir.evidence import AuthorityClass, Locator, RecordStatus, Source

BlockKind = Literal["heading", "paragraph", "table", "list", "code", "image", "keyvalue", "graph"]


@dataclass
class DocBlock:
    """One addressable chunk of a document."""

    kind: BlockKind
    text: str = ""
    locator: Locator = field(default_factory=Locator)
    #: Tables carry rows here as well as a flattened `text` rendering, so downstream code can
    #: use whichever form it needs without re-parsing.
    rows: list[list[str]] | None = None
    data: dict[str, Any] | None = None
    image: bytes | None = None

    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


@dataclass
class Document:
    source: Source
    blocks: list[DocBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def tables(self) -> list[DocBlock]:
        return [b for b in self.blocks if b.kind == "table"]

    def text_blocks(self) -> list[DocBlock]:
        return [b for b in self.blocks if b.kind in ("paragraph", "heading", "list", "keyvalue")]

    def images(self) -> list[DocBlock]:
        return [b for b in self.blocks if b.kind == "image" and b.image]

    def full_text(self, limit: int | None = None) -> str:
        out = "\n\n".join(b.text for b in self.blocks if b.text)
        return out[:limit] if limit else out

    def chunks(
        self,
        max_chars: int = 6000,
        overlap: int = 400,
        kinds: tuple[str, ...] | None = None,
    ) -> Iterable[tuple[str, Locator]]:
        """Chunk for model consumption, preserving the locator of the first block in each chunk.

        Chunks never straddle a table: tables go through whole, because half a table is worse
        than no table and small models will confidently misread a split one.

        `kinds`, when given, restricts which block kinds are chunked at all -- e.g. the model
        extraction path only wants prose (`heading`/`paragraph`/`list`), never a table (already
        deterministic), a keyvalue/graph block (also deterministic), an image placeholder, or a
        raw code dump. A block is excluded because of *what it is*, not because its text happens
        to match something already extracted.
        """
        buf: list[str] = []
        anchor: Locator | None = None
        size = 0
        for b in self.blocks:
            if not b.text:
                continue
            if kinds is not None and b.kind not in kinds:
                continue
            if b.kind == "table" and buf:
                yield "\n".join(buf), anchor or b.locator
                buf, size, anchor = [], 0, None
            if size + len(b.text) > max_chars and buf:
                yield "\n".join(buf), anchor or b.locator
                tail = "\n".join(buf)[-overlap:]
                buf, size, anchor = ([tail] if overlap else []), len(tail), b.locator
            if anchor is None:
                anchor = b.locator
            buf.append(b.text)
            size += len(b.text)
            if b.kind == "table":
                yield "\n".join(buf), anchor
                buf, size, anchor = [], 0, None
        if buf:
            yield "\n".join(buf), anchor or Locator()


class Adapter:
    """Base class for format adapters. Register concrete ones in registry.py."""

    #: File suffixes this adapter claims, lower case with the dot.
    suffixes: tuple[str, ...] = ()
    name: str = "base"

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def parse(self, path: Path, source: Source) -> Document:  # pragma: no cover - abstract
        raise NotImplementedError


def make_source(path: Path, index: int) -> Source:
    """Build the Source record, including the authority/status heuristics from precedence.yaml."""
    raw = path.read_bytes()
    media, _ = mimetypes.guess_type(path.name)
    return Source(
        id=f"SRC-{index:02d}",
        filename=path.name,
        media_type=media or f"application/{path.suffix.lstrip('.') or 'octet-stream'}",
        sha256=hashlib.sha256(raw).hexdigest(),
        authority=AuthorityClass.UNKNOWN,
        status=RecordStatus.UNKNOWN,
    )


def classify_source(source: Source, sample_text: str, hints: dict[str, Any]) -> Source:
    """Apply config/precedence.yaml authority_hints and status_hints.

    Heuristic only, and marked as such: a later `supersession` claim extracted from the text
    itself always beats this, and the reconciler records which basis it used.
    """
    haystack = f"{source.filename}\n{sample_text[:4000]}".lower()
    for cls, needles in (hints.get("authority_hints") or {}).items():
        if any(str(n).lower() in haystack for n in needles):
            source.authority = AuthorityClass(cls)
            break
    for status, needles in (hints.get("status_hints") or {}).items():
        if any(str(n).lower() in haystack for n in needles):
            source.status = RecordStatus(status)
            break
    source.classification_basis = "heuristic"
    return source


def render_table(rows: list[list[str]], max_rows: int = 200) -> str:
    """Pipe-delimited rendering. Small models parse this far more reliably than CSV or HTML."""
    out = []
    for r in rows[:max_rows]:
        out.append(" | ".join((c or "").strip() for c in r))
    if len(rows) > max_rows:
        out.append(f"... ({len(rows) - max_rows} more rows)")
    return "\n".join(out)


AdapterFactory = Callable[[], Adapter]
