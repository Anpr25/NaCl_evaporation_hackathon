"""Binding memory: what the catalog has learned from every run it took part in.

The harvested catalog knows what classes EXIST. It cannot know which one is right for "a
well-mixed room volume" or "an on-off valve" -- retrieval approximates that from words, one
part at a time, and the same wrong guess comes back run after run. But every run ends with
hard evidence about its bindings: omc either built and simulated the model with a class in
it, or the class was withdrawn, repaired away or left the model unable to connect. That
evidence was thrown away at the end of each run.

This keeps it. Each binding is filed under a *signature* of the part -- its role, its domain
and the content words of what the register calls it -- so it generalises across packets:
"fluid|off valve" learned on one plant applies to the next plant's on-off valve.

    ok    the class was in a model that compiled and simulated, with something connected to it
    bad   the class was withdrawn (connectors could not mate) or corrected by repair

A suggestion needs `ok` to outweigh `bad` twice over, and a class with two failures and no
success is actively kept out of retrieval for that signature. The memory never introduces a
class the catalog does not contain: every suggestion is re-verified against the current
catalog before use.

It also learns connector families per domain -- which library a magnetic circuit or a
process plant ended up wired in -- and feeds that into the family vote in `emit/families.py`.

The file is plain JSON next to the catalog, machine-local like the catalog itself. Delete it
to forget; pass `--no-learn` to run without reading or writing it.

Owner: C.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..reconcile.entities import humanise, singular

#: Words that carry no identity. A signature built from them would merge unrelated parts.
_STOP = {"the", "and", "for", "with", "from", "into", "of", "to", "in", "on", "at", "by",
         "type", "element", "part", "unit", "item", "device", "equipment", "component",
         "model", "class", "block"}

#: How strongly each failure counts against a success. A class that failed once and worked
#: once is not trustworthy yet.
_BAD_WEIGHT = 2


def signature(role: str, domains: Iterable[str], kind: str, name: str = "") -> str:
    """'fluid|off valve' -- stable across packets, tags, word order and how the part entered
    the IR.

    `role` is accepted and deliberately ignored. Only components and boundaries are ever
    bound, and they bind the same way; keeping the role in the key meant an electric ground
    learned as a 'boundary' on one run was a stranger when the next run inferred the same
    ground from an interface record, and the wrong class won by retrieval instead.
    """
    words = _content_words(kind) or _content_words(name)
    doms = sorted(d for d in domains if d not in ("unknown", "signal", "control")) or         sorted(d for d in domains if d != "unknown") or ["unknown"]
    return f"{doms[0]}|{' '.join(words)}"


def _content_words(text: str) -> list[str]:
    raw = re.findall(r"[a-z]{3,}", humanise(text or "").lower())
    return sorted({singular(w) for w in raw if w not in _STOP})


@dataclass
class BindingMemory:
    path: Path
    #: signature -> class -> {"ok": n, "bad": n, "last": epoch, "packets": [...]}
    bindings: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    #: domain -> connector package -> {"ok": n, "bad": n}
    families: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    #: Counters for this run only, for the report.
    used: int = 0
    learned: int = 0

    # ------------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: str | Path) -> "BindingMemory":
        p = Path(path)
        mem = cls(path=p)
        if p.exists():
            try:
                blob = json.loads(p.read_text(encoding="utf-8"))
                mem.bindings = blob.get("bindings", {})
                mem.families = blob.get("families", {})
            except (OSError, ValueError):
                # A corrupt memory is an empty memory, never a failed run.
                pass
        return mem

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = {
            "version": 1,
            "note": "SpecAlive binding memory. Safe to delete; it is rebuilt from runs.",
            "bindings": self.bindings,
            "families": self.families,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ reading
    @staticmethod
    def _score(stats: dict[str, Any]) -> int:
        return int(stats.get("ok", 0)) - _BAD_WEIGHT * int(stats.get("bad", 0))

    def suggest(self, sig: str, catalog_keys: set[str] | None = None) -> tuple[str, dict[str, Any]] | None:
        """The best-evidenced class for this signature, or None."""
        options = self.bindings.get(sig, {})
        ranked = sorted(
            ((cls, st) for cls, st in options.items()
             if self._score(st) >= 1 and (catalog_keys is None or cls in catalog_keys)),
            key=lambda kv: (-self._score(kv[1]), kv[0]),
        )
        return ranked[0] if ranked else None

    def discredited(self, sig: str) -> set[str]:
        """Classes that have failed for this signature and never once worked."""
        return {cls for cls, st in self.bindings.get(sig, {}).items()
                if int(st.get("bad", 0)) >= 2 and int(st.get("ok", 0)) == 0}

    def family_weight(self, domain: str, package: str) -> float:
        st = self.families.get(domain, {}).get(package)
        if not st:
            return 0.0
        return max(0.0, float(st.get("ok", 0) - _BAD_WEIGHT * st.get("bad", 0)))

    # ------------------------------------------------------------------ writing
    def _bump(self, sig: str, cls: str, key: str, packet: str) -> None:
        st = self.bindings.setdefault(sig, {}).setdefault(cls, {"ok": 0, "bad": 0, "packets": []})
        st[key] = int(st.get(key, 0)) + 1
        st["last"] = int(time.time())
        if packet and packet not in st["packets"]:
            st["packets"] = (st["packets"] + [packet])[-8:]

    def record_success(self, sig: str, cls: str, packet: str) -> None:
        self._bump(sig, cls, "ok", packet)
        self.learned += 1

    def record_failure(self, sig: str, cls: str, packet: str) -> None:
        self._bump(sig, cls, "bad", packet)
        self.learned += 1

    def record_family(self, domain: str, package: str, *, ok: bool) -> None:
        st = self.families.setdefault(domain, {}).setdefault(package, {"ok": 0, "bad": 0})
        st["ok" if ok else "bad"] += 1

    def summary(self) -> str:
        n = sum(len(v) for v in self.bindings.values())
        return f"{n} learned binding(s) across {len(self.bindings)} part signature(s)"
