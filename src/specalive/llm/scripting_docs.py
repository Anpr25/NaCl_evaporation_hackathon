"""Real-time grounding in the OpenModelica Scripting API, for the one LLM task that reads and
writes raw Modelica text (`repair_modelica` in `repair/loop.py`).

That task already has a tool-use round-trip for Modelica *class* signatures: when it is
unsure a connector or parameter exists, it asks (`lookup`) and is shown the harvested
catalog's verified entry rather than guessing (`RepairLoop._signature`). This module answers
the analogous question about the *compiler's own scripting functions* -- `saveTotalModel`,
`getErrorString`, and the rest of
https://build.openmodelica.org/Documentation/OpenModelica.Scripting.html -- which the catalog
(harvested Modelica *library* classes) knows nothing about and the model otherwise has to
recall from training data, with no way to tell a remembered signature from an invented one.

Fetched, not bundled, because the compiler and its docs move: pinning a static copy would go
stale the day OpenModelica adds or changes a function. Every fetch is best-effort and silent
on failure -- a documentation lookup that cannot complete should degrade the model's answer,
never the run. `--provider none` never reaches this module at all (nothing here is on the
deterministic path); a cloud run that cannot reach the network for this one, optional lookup
simply gets no doc text back and proceeds exactly as it did before this module existed.

Owner: C.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The real API, fetched live: https://build.openmodelica.org/Documentation/OpenModelica.Scripting.html
BASE_URL = "https://build.openmodelica.org/Documentation"
from ..settings import REPO_ROOT

DEFAULT_CACHE_DIR = REPO_ROOT / "out" / ".omc_docs_cache"
#: A function name becomes part of a URL and a cache filename; anything else is refused before
#: either happens, model-supplied or not.
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: Keep a prompt from being dominated by one lookup among several.
_MAX_CHARS = 1500


def _unescape(text: str) -> str:
    return (
        text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        .replace("&#39;", "'").replace("&amp;", "&")
    )


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", _unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def _members(html: str, section_id: str) -> list[tuple[str, str, str]]:
    """(type, name, default) for each row of the Inputs/Outputs table, in doc order."""
    sec = re.search(rf'<section id="{section_id}">.*?</section>', html, re.S)
    if not sec:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", sec.group(0), re.S)
    out = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) >= 3:
            out.append((_strip_tags(cells[0]), _strip_tags(cells[1]), _strip_tags(cells[2])))
    return out


def _render(name: str, html: str) -> str | None:
    """A compact, signature-first rendering of one generated doc page.

    The site (https://build.openmodelica.org/Documentation/) is itself machine-generated
    from the compiler's own function declarations, with a stable, simple structure -- a one-
    line summary, an Information section of prose paragraphs, and Inputs/Outputs tables of
    (type, name, default) rows -- so this targets that structure directly rather than
    stripping arbitrary HTML down to unstructured text.
    """
    summary_m = re.search(r'<div class="om-summary">(.*?)</div>', html, re.S)
    if summary_m is None and not _members(html, "inputs"):
        return None  # not a function page this format recognises; say so by returning nothing
    summary = _strip_tags(summary_m.group(1)) if summary_m else ""

    def arg(type_, nm, default):
        return f"{nm}: {type_}" + (f" = {default}" if default else "")

    ins = ", ".join(arg(*m) for m in _members(html, "inputs"))
    outs = ", ".join(arg(*m) for m in _members(html, "outputs"))
    sig = f"{name}({ins})" + (f" -> {outs}" if outs else "")

    info_m = re.search(r'<section id="info">.*?<h2>Information</h2>(.*?)</section>', html, re.S)
    info = _strip_tags(info_m.group(1)) if info_m else ""

    text = f"{sig}\n{summary}" + (f"\n\n{info}" if info else "")
    return text[:_MAX_CHARS]


def _cache_path(name: str, cache_dir: Path) -> Path:
    return cache_dir / f"{name}.txt"


def fetch_function_doc(
    name: str, *, cache_dir: Path = DEFAULT_CACHE_DIR, timeout: float = 5.0
) -> str | None:
    """The OpenModelica Scripting API's own documentation for `name`, or None.

    None means "no doc available" for any reason at all -- not a scripting function, no
    network, a slow or unreachable server, an unexpected page shape -- and every caller must
    treat it exactly like a cache miss: proceed without the grounding, never fail the run
    over it. The one thing this never does is invent a signature; a caller that gets None
    back has learned nothing, not been told something false.
    """
    if not _VALID_NAME.match(name):
        return None
    cached = _cache_path(name, cache_dir)
    try:
        if cached.exists():
            return cached.read_text(encoding="utf-8") or None
    except OSError:
        pass

    try:
        import httpx

        resp = httpx.get(
            f"{BASE_URL}/OpenModelica.Scripting.{name}.html", timeout=timeout, follow_redirects=True
        )
        if resp.status_code != 200:
            return None
        text = _render(name, resp.text)
    except Exception:
        return None
    if not text:
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    except OSError:
        pass  # best-effort cache; a read-only out/ still returns the fetched text
    return text


def render_lookup(names: list[str], *, cache_dir: Path = DEFAULT_CACHE_DIR) -> str:
    """The block to inject into a repair prompt for a round of `doc_lookup` requests.

    Mirrors `RepairLoop._signature`'s wording and shape (ground truth under a clear
    heading, one entry per name, an explicit "not found" for anything that failed) so the
    two tool-use channels read the same way to the model.
    """
    out = []
    for name in names[:4]:
        doc = fetch_function_doc(name, cache_dir=cache_dir)
        out.append(
            f"{name}: NOT FOUND (not an OpenModelica Scripting API function, or the "
            f"documentation could not be fetched right now; do not guess its signature)"
            if doc is None else doc
        )
    return "VERIFIED OPENMODELICA SCRIPTING API DOCUMENTATION (fetched from " + BASE_URL + ")\n" + (
        "\n---\n".join(out)
    )
