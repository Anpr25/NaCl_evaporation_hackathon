"""Format adapters. Every one of these is deterministic: no model is used to read a file.

Coverage today: pdf, docx, xlsx, csv, json, eml, md/txt, puml, mo, png/jpg. That is the whole
NaCl packet and most of what a brochure-style handout contains. An image adapter emits the
bytes; the vision tier reads it later, in extract/, not here.

Owner: A. Adding a format means adding a class here and one line in registry.py.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import json
import re
from pathlib import Path

from ..ir.evidence import Locator, Source
from .base import Adapter, DocBlock, Document, render_table


class TextAdapter(Adapter):
    name = "text"
    suffixes = (".txt", ".md", ".log", ".rst")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        buf: list[str] = []
        start = 1
        for i, line in enumerate(lines, 1):
            if line.startswith("#"):
                if buf:
                    doc.blocks.append(_para("\n".join(buf), start, i - 1))
                    buf = []
                doc.blocks.append(
                    DocBlock("heading", line.lstrip("# ").strip(), Locator(line_start=i, line_end=i))
                )
                start = i + 1
            elif not line.strip():
                if buf:
                    doc.blocks.append(_para("\n".join(buf), start, i - 1))
                    buf = []
                start = i + 1
            else:
                buf.append(line)
        if buf:
            doc.blocks.append(_para("\n".join(buf), start, len(lines)))
        return doc


class PdfAdapter(Adapter):
    name = "pdf"
    suffixes = (".pdf",)

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        try:
            import pdfplumber  # richer: gives us real table geometry

            with pdfplumber.open(str(path)) as pdf:
                for pno, page in enumerate(pdf.pages, 1):
                    for table in page.extract_tables() or []:
                        rows = [[(c or "").strip() for c in row] for row in table]
                        doc.blocks.append(
                            DocBlock("table", render_table(rows), Locator(page=pno), rows=rows)
                        )
                    text = page.extract_text() or ""
                    if text.strip():
                        doc.blocks.append(DocBlock("paragraph", text, Locator(page=pno)))
            if doc.blocks:
                return doc
            doc.warnings.append("pdfplumber found no text; the PDF is probably scanned")
        except ImportError:
            doc.warnings.append("pdfplumber not installed, falling back to pypdf")
        except Exception as exc:
            doc.warnings.append(f"pdfplumber failed ({exc}); falling back to pypdf")

        try:
            from pypdf import PdfReader

            for pno, page in enumerate(PdfReader(str(path)).pages, 1):
                text = page.extract_text() or ""
                if text.strip():
                    doc.blocks.append(DocBlock("paragraph", text, Locator(page=pno)))
        except Exception as exc:
            doc.warnings.append(f"pypdf failed: {exc}")

        if not doc.blocks:
            # No extractable text at all: hand the rendered pages to the vision tier.
            doc.warnings.append("no text layer; pages queued for the vision tier")
            doc.blocks.extend(_render_pdf_pages(path, doc))
        return doc


def _render_pdf_pages(path: Path, doc: Document) -> list[DocBlock]:
    """Rasterise for OCR. pypdfium2 is optional; without it we declare the gap honestly."""
    try:
        import pypdfium2  # type: ignore

        out: list[DocBlock] = []
        pdf = pypdfium2.PdfDocument(str(path))
        for pno in range(len(pdf)):
            bitmap = pdf[pno].render(scale=2)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            out.append(DocBlock("image", f"[scanned page {pno + 1}]", Locator(page=pno + 1), image=buf.getvalue()))
        return out
    except ImportError:
        doc.warnings.append("pypdfium2 not installed: scanned pages cannot be rasterised")
        return []


class DocxAdapter(Adapter):
    name = "docx"
    suffixes = (".docx", ".dotx")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        try:
            import docx  # python-docx
        except ImportError:
            doc.warnings.append("python-docx not installed")
            return doc
        d = docx.Document(str(path))
        section = None
        for i, para in enumerate(d.paragraphs, 1):
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower()
            if "heading" in style or "title" in style:
                section = text
                doc.blocks.append(DocBlock("heading", text, Locator(line_start=i, section=text)))
            else:
                doc.blocks.append(DocBlock("paragraph", text, Locator(line_start=i, section=section)))
        for ti, table in enumerate(d.tables, 1):
            rows = [[c.text.strip() for c in row.cells] for row in table.rows]
            doc.blocks.append(
                DocBlock("table", render_table(rows), Locator(section=f"table{ti}"), rows=rows)
            )
        # A diagram pasted into a design note is exactly the kind of evidence the vision tier
        # needs; without this, the doc's prose reaches extraction but any embedded P&ID clone
        # or sketch would silently vanish.
        for ii, rel in enumerate((r for r in d.part.rels.values() if "image" in r.reltype), 1):
            label = f"{path.name} image{ii}"
            try:
                from PIL import Image

                img = Image.open(io.BytesIO(rel.target_part.blob))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                png_bytes = buf.getvalue()
            except Exception as exc:
                doc.warnings.append(f"embedded image {ii} could not be read ({exc}); skipped")
                continue
            blocks, warn = _image_blocks(png_bytes, label, Locator(section=f"image{ii}"))
            doc.blocks.extend(blocks)
            if warn:
                doc.warnings.append(f"tiling skipped for embedded image {ii}: {warn}")
        return doc


class XlsxAdapter(Adapter):
    name = "xlsx"
    suffixes = (".xlsx", ".xlsm", ".xltx")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        try:
            import openpyxl
        except ImportError:
            doc.warnings.append("openpyxl not installed")
            return doc
        wb = openpyxl.load_workbook(str(path), data_only=True)
        for ws in wb:
            rows: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                if any(c is not None for c in row):
                    rows.append(["" if c is None else str(c) for c in row])
            if not rows:
                continue
            # Cell-level locators matter here: a register row is the most citable evidence
            # there is, and the report quotes it as SRC-xx!Sheet!A7.
            doc.blocks.append(
                DocBlock(
                    "table",
                    f"# sheet: {ws.title}\n{render_table(rows, max_rows=500)}",
                    Locator(sheet=ws.title, cell=f"A1:{ws.dimensions.split(':')[-1]}"),
                    rows=rows,
                    data={"sheet": ws.title, "header": rows[0] if rows else []},
                )
            )
        return doc


class CsvAdapter(Adapter):
    name = "csv"
    suffixes = (".csv", ".tsv")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.reader(fh, delimiter=delim))
        if not rows:
            return doc
        header, body = rows[0], rows[1:]
        # A long CSV is time-series data, not prose. Summarise it: the model must never be
        # shown 600 rows, and the verifier reads the file directly anyway.
        doc.blocks.append(
            DocBlock(
                "table",
                render_table([header, *body[:5]], max_rows=6)
                + f"\n... {len(body)} data rows total",
                Locator(line_start=1, line_end=len(rows)),
                rows=[header, *body[:5]],
                data={
                    "role": "timeseries" if len(body) > 50 else "table",
                    "columns": header,
                    "n_rows": len(body),
                    "path": str(path),
                },
            )
        )
        return doc


class JsonAdapter(Adapter):
    name = "json"
    suffixes = (".json", ".yaml", ".yml")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(text) if path.suffix.lower() == ".json" else _yaml(text)
        except Exception as exc:
            doc.warnings.append(f"structured parse failed: {exc}")
            doc.blocks.append(DocBlock("code", text[:20000], Locator()))
            return doc
        for key, value in _flatten(data):
            doc.blocks.append(
                DocBlock("keyvalue", f"{key} = {value}", Locator(section=key), data={"path": key, "value": value})
            )
        return doc


def _yaml(text: str):
    import yaml

    return yaml.safe_load(text)


def _flatten(obj, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


class EmlAdapter(Adapter):
    name = "eml"
    suffixes = (".eml", ".msg")

    def parse(self, path: Path, source: Source) -> Document:
        doc = Document(source=source)
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        # A thread is several records with different dates and authority, not one document.
        # Splitting it lets the reconciler weigh a later approval above an earlier opinion.
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        header = f"From: {msg.get('From')}\nDate: {msg.get('Date')}\nSubject: {msg.get('Subject')}"
        doc.blocks.append(DocBlock("heading", header, Locator(section="message-1")))
        parts = re.split(r"\n-{2,}\s*(?:Original message|Follow-up|Forwarded).*?-{2,}\n", text, flags=re.I)
        for i, part in enumerate(parts, 1):
            if part.strip():
                doc.blocks.append(DocBlock("paragraph", part.strip(), Locator(section=f"message-{i}")))
        return doc


class PumlAdapter(Adapter):
    name = "puml"
    suffixes = (".puml", ".plantuml", ".iuml")

    def parse(self, path: Path, source: Source) -> Document:
        """PlantUML is a graph in text form: extract the edges exactly, never by model."""
        doc = Document(source=source)
        edges: list[list[str]] = [["from", "to", "label", "style"]]
        nodes: list[str] = []
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if m := re.match(r"(?:component|class|node|rectangle)\s+\"?(\w[\w ]*)\"?", s):
                nodes.append(m.group(1))
            elif m := re.match(r"(\w+)\s*([.\-]{1,2}\w*[.\->]*>)\s*(\w+)\s*(?::\s*(.*))?$", s):
                edges.append([m.group(1), m.group(3), (m.group(4) or "").strip(), m.group(2)])
            elif s.startswith("note"):
                doc.blocks.append(DocBlock("paragraph", s, Locator(line_start=i)))
        doc.blocks.append(
            DocBlock("graph", render_table(edges), Locator(), rows=edges, data={"nodes": nodes})
        )
        return doc


class ModelicaAdapter(Adapter):
    name = "modelica"
    suffixes = (".mo", ".mos")

    def parse(self, path: Path, source: Source) -> Document:
        """Existing models are evidence about topology and parameters, and often about traps.

        Declarations and their inline comments are extracted exactly. Comments matter: legacy
        files are where 'STALE', 'superseded' and 'do not use' markers live.
        """
        doc = Document(source=source)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        decls: list[list[str]] = [["type", "name", "modifiers", "comment", "line"]]
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if m := re.match(r"([\w.]+)\s+(\w+)\s*(\([^;]*\))?\s*(?:\"([^\"]*)\")?\s*;", s):
                decls.append([m.group(1), m.group(2), (m.group(3) or "").strip(), m.group(4) or "", str(i)])
            if "//" in line:
                comment = line.split("//", 1)[1].strip()
                if comment:
                    doc.blocks.append(DocBlock("paragraph", f"// {comment}", Locator(line_start=i)))
        doc.blocks.append(DocBlock("table", render_table(decls), Locator(), rows=decls))
        doc.blocks.append(DocBlock("code", "\n".join(lines)[:20000], Locator(line_start=1, line_end=len(lines))))
        return doc


def _image_blocks(data: bytes, label: str, base_locator: Locator) -> tuple[list[DocBlock], str | None]:
    """Full image plus (if large) overlapping 2x2 tiles, as image DocBlocks.

    Shared by ImageAdapter (standalone image files) and DocxAdapter (images embedded in a Word
    doc): a P&ID at full page scale loses small tag bubbles; overlapping tiles recover them
    without a bigger model. Returns (blocks, warning) rather than writing to doc.warnings
    directly, since this has no Document of its own to write to.
    """
    blocks = [DocBlock("image", f"[{label}]", base_locator, image=data)]
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w * h > 1_400_000:
            cols, rows_n, ov = 2, 2, 0.12
            for r in range(rows_n):
                for c in range(cols):
                    x0 = max(0, int(c * w / cols - ov * w))
                    y0 = max(0, int(r * h / rows_n - ov * h))
                    x1 = min(w, int((c + 1) * w / cols + ov * w))
                    y1 = min(h, int((r + 1) * h / rows_n + ov * h))
                    buf = io.BytesIO()
                    img.crop((x0, y0, x1, y1)).save(buf, format="PNG")
                    blocks.append(
                        DocBlock(
                            "image",
                            f"[{label} tile r{r}c{c}]",
                            Locator(bbox=(x0, y0, x1, y1), section=base_locator.section),
                            image=buf.getvalue(),
                        )
                    )
    except Exception as exc:
        return blocks, str(exc)
    return blocks, None


class ImageAdapter(Adapter):
    name = "image"
    suffixes = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")

    def parse(self, path: Path, source: Source) -> Document:
        """Emit bytes only. Interpretation happens in extract/, on the vision tier."""
        doc = Document(source=source)
        blocks, warn = _image_blocks(path.read_bytes(), path.name, Locator())
        doc.blocks.extend(blocks)
        if warn:
            doc.warnings.append(f"tiling skipped: {warn}")
        return doc


def _para(text: str, start: int, end: int) -> DocBlock:
    return DocBlock("paragraph", text, Locator(line_start=start, line_end=end))
