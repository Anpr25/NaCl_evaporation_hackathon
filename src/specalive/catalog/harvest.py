"""Machine-harvest every available Modelica library into a searchable catalog.

`omc` can introspect any loaded library: class names, doc comments, restrictions, parameters
with units, and connector components. On this machine that is 6368 classes from MSL alone, for
free, offline, in a couple of minutes.

Why this matters: it converts "write correct Modelica for an unknown domain" -- which a 3B
local model cannot do -- into "pick the right entry from twelve retrieved candidates and fill
its declared parameters" -- which it can. Wrong class paths, invented parameters and mismatched
connector types stop being possible, because the emitter only ever writes what the catalog
verified exists.

Owner: C.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_LIBRARIES = ("Modelica",)

#: Subtrees that are documentation, icons or internals rather than usable components.
SKIP_PATTERNS = (
    r"\.UsersGuide(\.|$)",
    r"\.Examples(\.|$)",
    r"\.Icons(\.|$)",
    r"\.Internal(\.|$)",
    r"\.Obsolete(\.|$)",
    r"\.Validation(\.|$)",
    r"\.Verification(\.|$)",
)

#: Subtrees that contain no instantiable component, only type aliases, functions, constants
#: and records. Probing them costs four omc calls each and everything is discarded afterwards
#: by the restriction filter, so they are cut before the expensive pass rather than after.
#: On MSL this removes about 45% of the candidates.
DEAD_SUBTREES = (
    r"^Modelica\.Units(\.|$)",
    r"^Modelica\.Math(\.|$)",
    r"^Modelica\.Utilities(\.|$)",
    r"^Modelica\.Constants(\.|$)",
    r"^Modelica\.ComplexMath(\.|$)",
    r"\.Types(\.|$)",
    r"\.Functions(\.|$)",
    r"\.Records(\.|$)",
    r"\.Common(\.|$)",
)

#: Probed so inheritance resolves, but never emitted as catalog entries. MSL declares a
#: component's connectors in a partial base class, so dropping these from the probe pass
#: silently strips the ports off everything that inherits them -- which is exactly how
#: Modelica.Fluid.Vessels.OpenTank ended up with an empty port list.
PARENT_ONLY = (
    r"\.BaseClasses(\.|$)",
    r"\.Partial\w*$",
    r"\.\w*Partial\w*(\.|$)",
)

#: Top-level package -> IR domain. Extend when a new library is added to the bench.
DOMAIN_MAP = {
    "Modelica.Electrical": "electrical",
    "Modelica.Magnetic": "magnetic",
    "Modelica.Mechanics.Rotational": "rotational",
    "Modelica.Mechanics.Translational": "translational",
    "Modelica.Mechanics.MultiBody": "multibody",
    "Modelica.Thermal": "thermal",
    "Modelica.Fluid": "fluid",
    "Modelica.Media": "fluid",
    "Modelica.Blocks": "signal",
    "Modelica.StateGraph": "control",
    "Modelica.Clocked": "control",
    "SpecAlive.Vessels": "fluid",
    "SpecAlive.Transport": "fluid",
    "SpecAlive.Sources": "fluid",
}

NL = "\n"


@dataclass
class CatalogParam:
    name: str
    type: str
    unit: str | None
    description: str


@dataclass
class CatalogPort:
    name: str
    type: str
    description: str


@dataclass
class CatalogEntry:
    """One instantiable Modelica class, with everything the emitter needs to use it safely."""

    key: str
    library: str
    domain: str
    restriction: str
    comment: str
    params: list[CatalogParam] = field(default_factory=list)
    ports: list[CatalogPort] = field(default_factory=list)
    #: Extra search terms. Deterministic ones are derived from the path and comment; the team
    #: adds hand-written aliases for the vocabulary a brochure would actually use.
    aliases: list[str] = field(default_factory=list)

    def search_text(self) -> str:
        return " ".join([self.key.replace(".", " "), self.comment, self.domain, *self.aliases]).lower()


# --------------------------------------------------------------------------------- omc driver


def _root_of(f: str | Path) -> str:
    """Top-level package name declared inside a local .mo file."""
    text = Path(f).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*(?:encapsulated\s+)?package\s+(\w+)", text, re.M)
    return m.group(1) if m else Path(f).stem


def _run_omc(
    script: str, omc: str, cwd: Path, timeout: int = 1800, tag: str = "harvest"
) -> str:
    # `tag` keeps parallel workers off each other's script file.
    path = cwd / f"{tag}.mos"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [omc, str(path)], capture_output=True, text=True, cwd=str(cwd), timeout=timeout
    )
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(f"omc failed: {proc.stderr[:800]}")
    return proc.stdout


def _parse_omc_list(text: str) -> list[str]:
    """omc echoes a string list as {A, B, C}."""
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return []
    inner = text[1:-1].strip()
    return [p.strip() for p in inner.split(",") if p.strip()] if inner else []


def _parse_components(text: str) -> list[tuple[str, ...]]:
    """Parse getComponents() output: ``{{type, name, "comment", ..., {}}, {...}}``.

    Needs a depth scanner rather than a regex: each record ends with a nested empty ``{}``,
    so any pattern matching "braces with no braces inside" finds only those empty groups and
    silently returns nothing.
    """
    text = text.strip()
    if not text.startswith("{{"):
        return []
    rows: list[tuple[str, ...]] = []
    depth = 0
    start = -1
    in_string = False
    for i, ch in enumerate(text):
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
            if depth == 2:
                start = i + 1
        elif ch == "}":
            if depth == 2 and start >= 0:
                rows.append(_split_record(text[start:i]))
                start = -1
            depth -= 1
    return [r for r in rows if len(r) >= 3]


def _split_record(body: str) -> tuple[str, ...]:
    """Split one record on commas at depth zero, respecting quotes and nested braces."""
    fields: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []
    for ch in body:
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                continue
            if ch == "," and depth == 0:
                fields.append("".join(current).strip())
                current = []
                continue
        current.append(ch)
    fields.append("".join(current).strip())
    return tuple(f for f in fields)


def _domain_for(key: str) -> str:
    for prefix, dom in DOMAIN_MAP.items():
        if key.startswith(prefix):
            return dom
    return "unknown"


def _parent_only(key: str) -> bool:
    """Needed as an inheritance parent, but not a component anyone should instantiate."""
    return any(re.search(p, key) for p in PARENT_ONLY)


def _skip(key: str) -> bool:
    return any(re.search(p, key) for p in SKIP_PATTERNS) or any(
        re.search(p, key) for p in DEAD_SUBTREES
    )


def _derive_aliases(key: str, comment: str) -> list[str]:
    """Cheap deterministic vocabulary expansion: CamelCase split plus comment words."""
    leaf = key.rsplit(".", 1)[-1]
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]{2,}", leaf)
    out = {leaf.lower(), " ".join(w.lower() for w in words)}
    out |= {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", comment)}
    return sorted(w for w in out if w)


# ------------------------------------------------------------------------------------ harvest
#
# omc scripting quirks that took a while to pin down, recorded so nobody rediscovers them:
#
#   * A call with named arguments nested inside another call returns nothing AND silently
#     aborts the rest of the script. `getClassNames(X, recursive=true)` must be assigned to a
#     variable, never inlined into `stringDelimitList(...)`.
#   * `recursive=true` without `qualified=true` returns leaf names, which are useless.
#   * Every assignment echoes its value to stdout, so the echoed "{A, B, C}" IS the result;
#     printing it again is redundant and doubles an already large output.



def harvest(
    libraries=DEFAULT_LIBRARIES,
    *,
    omc: str = "omc",
    extra_files=(),
    out_path="out/catalog.jsonl",
    restrictions: tuple[str, ...] = ("model", "block", "connector"),
    chunk_size: int = 300,
    workers: int = 3,
    chunk_timeout: int = 900,
    progress=None,
) -> Path:
    """Introspect `libraries` plus any `extra_files` and write a JSONL catalog.

    Run once per machine. Deterministic, offline, no model involved; its output is the ground
    truth the whole Modelica emitter is built on. Full MSL takes a couple of minutes with the
    default chunking and four workers.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    libraries = list(libraries)
    extra_files = [Path(f) for f in extra_files]

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        loads = "".join(f"loadModel({lib});{NL}" for lib in libraries)
        loads += "".join(f'loadFile("{f.resolve().as_posix()}");{NL}' for f in extra_files)
        roots = [*libraries, *[_root_of(f) for f in extra_files]]

        listing = NL.join(
            f"names{i} := getClassNames({r}, recursive=true, qualified=true);"
            for i, r in enumerate(roots)
        )
        names_out = _run_omc(loads + listing, omc, cwd, tag="names")

        candidates: list[str] = []
        for line in names_out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                candidates.extend(n for n in _parse_omc_list(line) if "." in n and not _skip(n))
        candidates = sorted(set(candidates))
        if not candidates:
            raise RuntimeError(
                "omc returned no class names; check the libraries are installed."
                + names_out[:800]
            )

        # Metadata pass, chunked and run in parallel.
        #
        # One omc process per class would take hours. One giant script for all of them is
        # worse than linear: omc parses the whole .mos up front, and 3000 classes is ~17k
        # statements, which is what made the first full-MSL run time out. Chunking keeps each
        # script small and lets several omc processes run at once. Each chunk repeats
        # loadModel, costing a few seconds, which is well worth it.
        chunks = [candidates[i : i + chunk_size] for i in range(0, len(candidates), chunk_size)]
        outputs: list[str] = [""] * len(chunks)
        failures: list[str] = []
        completed = 0

        def _one(n: int, keys: list[str]) -> str:
            # Each worker gets its own directory. omc writes scratch files into its working
            # directory, and several processes sharing one directory collide badly: a chunk
            # that takes 30 s alone did not finish in 30 minutes with four workers in the
            # same folder. Isolating them restores full speed.
            work = cwd / f"w{n}"
            work.mkdir(exist_ok=True)
            return _run_omc(_probe_script(loads, keys), omc, work, chunk_timeout, "probe")

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_one, n, chunk): n for n, chunk in enumerate(chunks)}
            for fut in as_completed(futures):
                n = futures[fut]
                try:
                    outputs[n] = fut.result()
                except Exception as exc:
                    # A partial catalog is far more useful than no catalog, so a bad chunk is
                    # reported and skipped rather than allowed to abort the whole harvest.
                    failures.append(f"chunk {n} ({chunks[n][0]} ...): {exc!r}")
                completed += 1
                if progress:
                    progress(completed, len(chunks))
        if failures:
            print(f"warning: {len(failures)} of {len(chunks)} chunk(s) failed:")
            for f in failures:
                print(f"  {f}")
        meta_out = NL.join(outputs)

    return _write_catalog(_build_entries(meta_out, restrictions), out_path)


def _probe_script(loads: str, keys: list[str]) -> str:
    """One .mos script covering `keys`.

    No print() for the components or the parents: String() on a list-of-lists returns nothing
    and silently aborts the rest of the script. Each assignment echoes its own value on a line
    starting with "{", and that echo is the data the parser reads.
    """
    probe = [loads]
    for i, key in enumerate(keys):
        probe.append(
            f'print("@@KEY {key}\\n");{NL}'
            f"res{i} := getClassRestriction({key});{NL}"
            f'print("@@RES " + res{i} + "\\n");{NL}'
            f"com{i} := getClassComment({key});{NL}"
            f'print("@@COM " + com{i} + "\\n");{NL}'
            # Authoritative partial flag, straight from the compiler. Name heuristics miss
            # partial classes that are not called Partial* and do not live under BaseClasses
            # -- Modelica.Thermal.HeatTransfer.Interfaces.Element1D is the one that bit us.
            f"par{i} := isPartial({key});{NL}"
            f'print("@@PAR " + String(par{i}) + "\\n");{NL}'
            f"cmp{i} := getComponents({key});{NL}"
            f'print("@@INH\\n");{NL}'
            f"inh{i} := getInheritedClasses({key});"
        )
    return NL.join(probe)


def _build_entries(meta_out: str, restrictions: tuple[str, ...]) -> list[CatalogEntry]:
    # First pass: local components and direct parents, keyed by class.
    raw: dict[str, dict[str, Any]] = {}
    for block in meta_out.split("@@KEY ")[1:]:
        key = block.splitlines()[0].strip()
        own, inherited = block, ""
        if "@@INH" in block:
            own, _, inherited = block.partition("@@INH")
        raw[key] = {
            "restriction": _first(own, "@@RES").strip().strip(chr(34)),
            "comment": _first(own, "@@COM").strip().strip(chr(34)),
            "is_partial": _first(own, "@@PAR").strip().strip(chr(34)) == "true",
            "rows": _parse_components(_components_echo(own)),
            "parents": _parse_omc_list(_first_brace_line(inherited)),
        }

    entries: list[CatalogEntry] = []
    for key, info in raw.items():
        # Emit-time filter only. Partial classes are still probed above, because MSL declares
        # connectors in partial bases and _collect_rows walks the inheritance chain through
        # `raw` to recover them (D24). Filtering them earlier strips ports off their children.
        if info["restriction"] not in restrictions or _parent_only(key) or info["is_partial"]:
            continue
        params: list[CatalogParam] = []
        ports: list[CatalogPort] = []
        # A Modelica component usually declares its connectors in a partial base class, so a
        # class's own getComponents() shows parameters but no ports. Walking the inheritance
        # chain is what makes the port signature trustworthy, and the port signature is the
        # whole reason the emitter cannot produce a mismatched connect().
        for row in _collect_rows(key, raw):
            ctype, cname, cdesc = row[0], row[1], row[2]
            if any(x.name == cname for x in params) or any(x.name == cname for x in ports):
                continue
            if _variability(row) in ("parameter", "constant"):
                params.append(CatalogParam(cname, ctype, _unit_of(ctype), cdesc))
            elif _looks_like_connector(ctype):
                ports.append(CatalogPort(cname, ctype, cdesc))
        entries.append(
            CatalogEntry(
                key=key,
                library=key.split(".")[0],
                domain=_domain_for(key),
                restriction=info["restriction"],
                comment=info["comment"],
                params=params,
                ports=ports,
                aliases=_derive_aliases(key, info["comment"]),
            )
        )
    return entries


def _write_catalog(entries: list[CatalogEntry], out_path: Path) -> Path:
    with out_path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
    return out_path


_VARIABILITIES = frozenset({"parameter", "constant", "discrete", "continuous", "unspecified"})


def _variability(row: tuple[str, ...]) -> str:
    for field_value in row[3:]:
        if field_value in _VARIABILITIES:
            return field_value
    return ""


def _looks_like_connector(ctype: str) -> bool:
    return (
        "Interfaces" in ctype
        or ctype.endswith(("Port", "Pin", "Flange", "Frame", "_a", "_b", "Input", "Output"))
    )


def _collect_rows(key: str, raw: dict[str, Any], depth: int = 0) -> list[tuple[str, ...]]:
    """Own components plus inherited ones, nearest declaration first."""
    if depth > 4 or key not in raw:
        return []
    rows = list(raw[key]["rows"])
    for parent in raw[key]["parents"]:
        rows.extend(_collect_rows(parent, raw, depth + 1))
    return rows


def _first_brace_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return line
    return ""


def _components_echo(block: str) -> str:
    """The getComponents() assignment echo: the one line in the block starting with '{{'."""
    for line in block.splitlines():
        if line.startswith("{{"):
            return line
    return ""


def _first(block: str, marker: str) -> str:
    for line in block.splitlines():
        if line.startswith(marker):
            return line[len(marker) :]
    return ""


_UNIT_RE = re.compile(r"Modelica\.Units\.SI\.(\w+)")
#: Minimal SI type -> unit map, used only for unit-consistency warnings. An incomplete map
#: degrades to "unknown unit", never to a wrong one.
_SI_UNITS = {
    "Length": "m", "Height": "m", "Distance": "m", "Area": "m2", "Volume": "m3", "Mass": "kg",
    "MassFlowRate": "kg/s", "VolumeFlowRate": "m3/s", "Density": "kg/m3",
    "Temperature": "K", "TemperatureDifference": "K", "Pressure": "Pa", "AbsolutePressure": "Pa",
    "HeatFlowRate": "W", "Power": "W", "Energy": "J", "SpecificEnthalpy": "J/kg",
    "SpecificHeatCapacity": "J/(kg.K)", "ThermalConductance": "W/K", "HeatCapacity": "J/K",
    "ThermalResistance": "K/W",
    "Time": "s", "Frequency": "Hz", "Angle": "rad", "AngularVelocity": "rad/s",
    "AngularAcceleration": "rad/s2", "Torque": "N.m", "Force": "N",
    "Inertia": "kg.m2", "MomentOfInertia": "kg.m2", "RotationalSpringConstant": "N.m/rad",
    "RotationalDampingConstant": "N.m.s/rad", "TranslationalSpringConstant": "N/m",
    "Voltage": "V", "Current": "A", "Resistance": "Ohm", "Conductance": "S",
    "Capacitance": "F", "Inductance": "H", "Charge": "C",
    "MassFraction": "kg/kg", "Velocity": "m/s", "Acceleration": "m/s2", "Efficiency": "1",
}


def _unit_of(modelica_type: str) -> str | None:
    m = _UNIT_RE.search(modelica_type)
    return _SI_UNITS.get(m.group(1)) if m else None


def load_catalog(path: str | Path = "out/catalog.jsonl") -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"catalog not found at {p}. Run `specalive harvest` once on this machine."
        )
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw: dict[str, Any] = json.loads(line)
        raw["params"] = [CatalogParam(**x) for x in raw.get("params", [])]
        raw["ports"] = [CatalogPort(**x) for x in raw.get("ports", [])]
        entries.append(CatalogEntry(**raw))
    return entries
