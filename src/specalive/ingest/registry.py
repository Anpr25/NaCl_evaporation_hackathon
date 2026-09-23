"""Adapter registry and packet loading.

Owner: A.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from ..ir.evidence import Source
from .adapters import (
    CsvAdapter,
    DocxAdapter,
    EmlAdapter,
    ImageAdapter,
    JsonAdapter,
    ModelicaAdapter,
    PdfAdapter,
    PumlAdapter,
    TextAdapter,
    XlsxAdapter,
)
from .base import Adapter, Document, classify_source, make_source

ADAPTERS: tuple[Adapter, ...] = (
    XlsxAdapter(),
    CsvAdapter(),
    JsonAdapter(),
    PumlAdapter(),
    ModelicaAdapter(),
    PdfAdapter(),
    DocxAdapter(),
    EmlAdapter(),
    ImageAdapter(),
    TextAdapter(),
)

#: Files we never treat as evidence.
IGNORE = {".git", "__pycache__", ".DS_Store", "Thumbs.db", ".specalive_cache"}


def adapter_for(path: Path) -> Adapter | None:
    return next((a for a in ADAPTERS if a.can_handle(path)), None)


def discover(root: str | Path) -> list[Path]:
    """Walk a packet directory. Order is stable so SRC ids are stable across runs."""
    root = Path(root)
    if root.is_file():
        return [root]
    out = [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(part in IGNORE for part in p.parts)
    ]
    return out


def load_packet(
    root: str | Path,
    *,
    precedence_config: str | Path = "config/precedence.yaml",
) -> list[Document]:
    """Parse every readable file under `root` into a Document, with heuristic classification.

    Unreadable files are not skipped silently: they come back as a Document carrying a warning,
    so they show up in the report's gap list rather than vanishing.
    """
    hints = {}
    cfg = Path(precedence_config)
    if cfg.exists():
        hints = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}

    docs: list[Document] = []
    for i, path in enumerate(discover(root), 1):
        adapter = adapter_for(path)
        source = make_source(path, i)
        if adapter is None:
            doc = Document(source=source)
            doc.warnings.append(f"no adapter for '{path.suffix}'; file not read")
            docs.append(doc)
            continue
        try:
            doc = adapter.parse(path, source)
        except Exception as exc:
            doc = Document(source=source)
            doc.warnings.append(f"{adapter.name} adapter raised {exc!r}")
        doc.source = classify_source(doc.source, _title_sample(doc), hints)
        docs.append(doc)
    return docs


def _title_sample(doc: Document) -> str:
    """Classify from the title area only, never from the body.

    A register that *mentions* change records is not a change record, and a specification that
    quotes the word "superseded" is not superseded. Whole-file keyword matching gets both of
    those wrong, so only the filename plus the first heading and first paragraph are used.
    Per-claim supersession is handled properly downstream by the reconciler, which reads the
    explicit "superseded by" fields rather than guessing.
    """
    heads = [b.text for b in doc.blocks if b.kind == "heading"][:2]
    first = next((b.text for b in doc.blocks if b.kind in ("paragraph", "keyvalue")), "")
    return "\n".join([*heads, first[:400]])


def packet_summary(docs: Iterable[Document]) -> list[dict[str, object]]:
    """Table shown in the CLI and the report: what we read and how we classified it."""
    return [
        {
            "id": d.source.id,
            "file": d.source.filename,
            "authority": d.source.authority.value,
            "status": d.source.status.value,
            "blocks": len(d.blocks),
            "tables": len(d.tables()),
            "images": len(d.images()),
            "warnings": len(d.warnings),
        }
        for d in docs
    ]
