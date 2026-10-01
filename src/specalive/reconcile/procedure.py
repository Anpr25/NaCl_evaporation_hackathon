"""Read a test procedure for what the run must be: how long, what is done to the system
while it runs, and what has to be true afterwards.

The scenario used to be guessed from stray phrases anywhere in the packet ("a 3000 s
trace"), and on three packets out of four the guess was wrong by one to four orders of
magnitude: the two-tank demo ran 15 s of a 900 s procedure, the ventilation day 75 s of 24
hours. Nothing in it pressed START, so the tank controller sat in IDLE however good the
model was, and nothing checked the procedure's own acceptance criteria, so there was no way
to tell a correct model from a quiet one.

A procedure says all of this, in structure rather than prose, and that structure is what
this module reads:

  * a setup table      -- 'Simulation duration | 900 s', 'Logging interval | 1 s';
  * a command schedule -- a table with a time column and a command column;
  * a source profile   -- '0 A until 0.10 s, ramp to 2.0 A by 0.50 s, hold to 1.0 s';
  * acceptance items   -- a criteria/expected table, 'AC-01 - ...' items, or the 'shall'
                          sentences of an 'Acceptance' section.

Only documents that ARE procedures are read, so a design note's "24-hour" or a datasheet's
"1 s response" cannot set the run.

Owner: B.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ingest.base import Document

#: How a procedure announces itself, in its filename or its opening text.
_PROCEDURE = re.compile(
    r"test procedure|acceptance test|verification procedure|commissioning|validation runbook|"
    r"runbook|acceptance criteri|\b(?:TP|CP|AV|BAT|FAT|SAT)-\d+",
    re.I,
)
_TIME_UNITS = {"s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
               "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
               "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0}
_QUANTITY = re.compile(r"^\s*(?P<n>\d+(?:\.\d+)?)\s*(?P<u>[A-Za-z]+)?\s*$")
_DURATION_KEY = re.compile(
    r"(simulation|run|test|trend|record(?:ing)?|scenario)\s*(duration|length|time\s*span|period|"
    r"stop\s*time)|\bstop\s*time\b|\bduration\b|\bend\s*time\b", re.I)
_INTERVAL_KEY = re.compile(r"log(?:ging)?\s*interval|sampl\w*\s*interval|output\s*interval|"
                           r"logging\s*period|record\w*\s*interval", re.I)
_HOURS_RUN = re.compile(r"\b(?P<n>\d+(?:\.\d+)?)[-\s](?:hour|hr)\b", re.I)
_LOG_EVERY = re.compile(r"\blog\w*\s+(?:at|every)\s+(?P<n>\d+(?:\.\d+)?)\s*s\b", re.I)
_CLOCK_END = re.compile(r"\bthrough\s+(?P<h>\d{1,2}):(?P<m>\d{2})\b", re.I)

_CRITERION_ID = r"(?:AC|ACC|CRIT|TC|CHK)-?\d{1,3}"
_PROSE_ITEM = re.compile(
    rf"\b(?P<id>{_CRITERION_ID})\s*[-–:|]\s*(?P<text>.+?)(?=\s+\b{_CRITERION_ID}\s*[-–:|]|\s+\d+\.\s+[A-Z][a-z]|$)",
    re.S,
)
_AMOUNT = re.compile(
    r"(?P<n>[-+]?\d+(?:\.\d+)?)\s*(?P<u>kA|mA|A|kV|mV|V|kW|W|kN|N|Nm|K|degC|kPa|Pa|bar|rpm|"
    r"m3/s|kg/s|m/s)\b")
_SECONDS = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*s\b")


@dataclass
class RunSettings:
    stop_time: float | None = None
    interval: float | None = None
    basis: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Command:
    time: float
    command: str
    note: str
    source: str


@dataclass
class Profile:
    text: str
    unit: str
    amplitude: float
    offset: float
    start: float
    end: float | None
    hold: float | None
    source: str


@dataclass
class Criterion:
    id: str
    text: str
    context: str
    source: str


# ------------------------------------------------------------------------- discovery

def procedure_docs(docs: list[Document]) -> list[Document]:
    """Documents that ARE procedures -- judged by filename and title only. Review minutes
    and email threads mention procedures constantly; reading their body text for this let a
    design review's "agreed to rerun CP-23" pose as the procedure itself."""
    out = []
    for d in docs:
        if d.source.filename.lower().endswith((".json", ".csv", ".eml", ".mo", ".puml")):
            continue
        if _PROCEDURE.search(f"{d.source.filename} {_title(d)}"):
            out.append(d)
    return out


def _title(doc: Document) -> str:
    for b in doc.blocks:
        if b.kind in ("heading", "paragraph") and b.text and b.text.strip():
            return b.text.strip().splitlines()[0][:120]
    return doc.source.filename


def _seconds(cell: str, header_unit: str | None = None) -> float | None:
    m = _QUANTITY.match(cell or "")
    if not m:
        return None
    unit = (m.group("u") or header_unit or "s").lower()
    scale = _TIME_UNITS.get(unit)
    return float(m.group("n")) * scale if scale else None


# ---------------------------------------------------------------------- run settings

def run_settings(docs: list[Document]) -> RunSettings:
    out = RunSettings()
    for d in procedure_docs(docs):
        for b in d.tables():
            for row in b.rows or []:
                cells = [str(c or "").strip() for c in row]
                if len(cells) < 2 or not cells[0]:
                    continue
                key, value = cells[0], cells[1]
                if out.stop_time is None and _DURATION_KEY.search(key):
                    secs = _seconds(value)
                    if secs and secs > 0:
                        out.stop_time = secs
                        out.basis.append(f"'{key} | {value}' in {d.source.filename}")
                        out.sources.append(d.source.id)
                elif out.interval is None and _INTERVAL_KEY.search(key):
                    secs = _seconds(value)
                    if secs and secs > 0:
                        out.interval = secs
                        out.basis.append(f"'{key} | {value}' in {d.source.filename}")
        text = d.full_text()
        if out.stop_time is None:
            if (m := _CLOCK_END.search(text)) and re.search(r"\b00:00\b", text):
                out.stop_time = int(m.group("h")) * 3600.0 + int(m.group("m")) * 60.0
                out.basis.append(f"runs from 00:00 {m.group(0)} ({d.source.filename})")
                out.sources.append(d.source.id)
            elif m := _HOURS_RUN.search(text):
                out.stop_time = float(m.group("n")) * 3600.0
                out.basis.append(f"a {m.group(0)} run ({d.source.filename})")
                out.sources.append(d.source.id)
        if out.interval is None and (m := _LOG_EVERY.search(text)):
            out.interval = float(m.group("n"))
            out.basis.append(f"'{m.group(0)}' ({d.source.filename})")
    return out


# ------------------------------------------------------------------ command schedule

def command_schedule(docs: list[Document]) -> list[Command]:
    """Rows of every table whose header has a time column and a command column."""
    out: list[Command] = []
    for d in procedure_docs(docs):
        for b in d.tables():
            rows = [[str(c or "").strip() for c in r] for r in (b.rows or [])]
            if len(rows) < 2:
                continue
            head = [h.lower() for h in rows[0]]
            t_col = next((j for j, h in enumerate(head) if re.search(r"\btime\b|\bt\s*\(", h)), None)
            c_col = next((j for j, h in enumerate(head)
                          if re.search(r"command|action|event|operator|input|button", h)), None)
            if t_col is None or c_col is None or t_col == c_col:
                continue
            unit = re.search(r"\((s|sec|min|h)\)", head[t_col])
            for r in rows[1:]:
                if max(t_col, c_col) >= len(r):
                    continue
                t = _seconds(r[t_col], unit.group(1) if unit else None)
                word = (re.findall(r"[A-Za-z][\w-]*", r[c_col]) or [""])[0]
                if t is None or not word:
                    continue
                note = " ".join(x for j, x in enumerate(r) if j not in (t_col, c_col) and x)
                out.append(Command(t, word, note, d.source.id))
    return out


def command_table_ids(docs: list[Document]) -> set[int]:
    """id() of every table that is a command schedule, so it is not also read as criteria."""
    ids: set[int] = set()
    for d in procedure_docs(docs):
        for b in d.tables():
            rows = b.rows or []
            if not rows:
                continue
            head = " ".join(str(c or "").lower() for c in rows[0])
            if re.search(r"\btime\b", head) and re.search(r"command|action|event|operator|button", head):
                ids.add(id(b))
    return ids


# -------------------------------------------------------------------- source profile

def profiles(docs: list[Document]) -> list[Profile]:
    """Ramp descriptions: an amplitude reached between two times, optionally held."""
    out: list[Profile] = []
    seen: set[str] = set()
    for d in procedure_docs(docs):
        candidates: list[str] = []
        for b in d.tables():
            for row in b.rows or []:
                cells = [str(c or "").strip() for c in row]
                if any("ramp" in c.lower() for c in cells):
                    candidates.append(" ; ".join(cells))
        for sentence in re.split(r"(?<=[.;])\s+", d.full_text()):
            if "ramp" in sentence.lower():
                candidates.append(sentence)
        for text in candidates:
            key = re.sub(r"\s+", " ", text.lower())
            if key in seen:
                continue
            seen.add(key)
            amounts = [(float(m.group("n")), m.group("u")) for m in _AMOUNT.finditer(text)]
            times = [float(m.group("n")) for m in _SECONDS.finditer(text)]
            if not amounts or len(times) < 2:
                continue
            unit = max(amounts, key=lambda a: abs(a[0]))[1]
            values = [v for v, u in amounts if u == unit]
            amp = max(values, key=abs)
            out.append(Profile(
                text=text.strip()[:240], unit=unit, amplitude=amp,
                offset=min(values, key=abs) if len(values) > 1 else 0.0,
                start=times[0], end=times[1], hold=times[2] if len(times) > 2 else None,
                source=d.source.id,
            ))
    return out


# --------------------------------------------------------------- acceptance criteria

def acceptance_criteria(docs: list[Document]) -> list[Criterion]:
    """Every acceptance item a procedure states, with the procedure's title as context."""
    out: list[Criterion] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    skip = command_table_ids(docs)

    def add(cid: str, text: str, context: str, source: str) -> None:
        norm_text = re.sub(r"\W+", " ", text.lower()).strip()
        if not norm_text or norm_text in seen_text or cid in seen_ids:
            return
        seen_ids.add(cid)
        seen_text.add(norm_text)
        out.append(Criterion(cid, text.strip()[:400], context, source))

    for d in procedure_docs(docs):
        title = _title(d)
        prefix = (re.search(r"\b(?:TP|CP|AV|BAT|FAT|SAT)-\d+", f"{d.source.filename} {title}")
                  or re.search(r"\w+", d.source.filename))
        prefix_text = prefix.group(0) if prefix else "PROC"
        acceptance_note = _acceptance_section(d.full_text())

        # 1. Tables whose header speaks of criteria or expected results.
        for b in d.tables():
            if id(b) in skip:
                continue
            rows = [[str(c or "").strip() for c in r] for r in (b.rows or [])]
            if len(rows) < 2:
                continue
            head = " ".join(rows[0]).lower()
            if not re.search(r"criteri|acceptance|expected|pass\b|limit", head):
                continue
            for n, r in enumerate(rows[1:], start=1):
                cells = [c for c in r if c]
                if len(cells) < 2:
                    continue
                if re.fullmatch(_CRITERION_ID, cells[0]):
                    cid, text = cells[0], " ".join(cells[1:])
                else:
                    cid, text = f"{prefix_text}-{n:02d}", f"{cells[0]}: {' '.join(cells[1:])}"
                    if "expected" in head:
                        text = f"{cells[0]} shall be {' '.join(cells[1:])}"
                context = title + (f" | {acceptance_note}" if acceptance_note else "")
                add(cid, text, context, d.source.id)

        # 2. 'AC-01 - ...' items in the prose.
        text = d.full_text()
        for m in _PROSE_ITEM.finditer(text):
            add(m.group("id"), re.sub(r"\s+", " ", m.group("text")), title, d.source.id)

        # 3. The 'shall' sentences of an Acceptance section that numbers nothing.
        if acceptance_note:
            for n, sentence in enumerate(re.split(r"(?<=\.)\s+", acceptance_note), start=1):
                if re.search(r"\bshall\b", sentence):
                    add(f"{prefix_text}-A{n}", sentence, title, d.source.id)
    return out


def _acceptance_section(text: str) -> str:
    """The body of a section headed 'Acceptance' (or 'N. Acceptance'), up to the next heading."""
    m = re.search(r"(?:^|\n|\s)\d*\.?\s*Acceptance(?: criteria)?\s*\n?(?P<body>.+?)(?=\n\s*\d+\.\s+[A-Z]|\Z)",
                  text, re.S)
    if not m:
        return ""
    body = re.sub(r"\s+", " ", m.group("body")).strip()
    # A criteria TABLE under the heading has already been read row by row.
    return "" if re.search(rf"\b{_CRITERION_ID}\b", body) else body[:600]
