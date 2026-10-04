"""The orchestrator: packet in, SysML + Modelica + results + report out.

Every stage emits a PipelineEvent, so the CLI, the web app and the bench all watch the same
run through the same interface and there is exactly one definition of what the pipeline does.

Stages are individually resumable from their on-disk artifact, which matters more than it
sounds: it means someone debugging the Modelica emitter never has to re-run extraction, and a
demo can start from a known-good IR if ingestion misbehaves.

Owner: D, with every stage owned by its workstream.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from .catalog.retrieve import CatalogIndex
from .emit.modelica import emit_modelica
from .emit.sysml import emit_sysml, round_trip_check
from .ingest.base import Document
from .ingest.registry import load_packet, packet_summary
from .ir.evidence import EvidenceClaim
from .ir.system import SystemModel
from .ir.validate import validate
from .ir.assumptions import AssumptionLog
from .ir.fallback import apply_declared_fallbacks
from .repair.loop import RepairLoop
from .repair.structural import plan_structural_repair
from .repair.writeback import apply_ir_edits
from .verify.acceptance import Scorecard, score
from .verify.diagnose import Diagnosis, diagnose, record
from .verify.omc import OmcRunner, describe_environment, liveness, read_result
from .verify.report import build_report

Stage = Literal[
    "ingest", "extract", "reconcile", "validate", "sysml", "modelica", "compile", "simulate",
    "verify", "report",
]
STAGES: tuple[Stage, ...] = (
    "ingest", "extract", "reconcile", "validate", "sysml", "modelica", "compile", "simulate",
    "verify", "report",
)


@dataclass
class PipelineEvent:
    stage: Stage
    status: Literal["start", "ok", "warn", "fail", "skip"]
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def line(self) -> str:
        mark = {"start": "...", "ok": " ok", "warn": "  !", "fail": "  x", "skip": "  -"}[self.status]
        return f"[{mark}] {self.stage:<9} {self.message}"


@dataclass
class PipelineConfig:
    packet: Path
    out_dir: Path = Path("out")
    library_files: list[Path] = field(default_factory=lambda: [Path("modelica/SpecAlive.mo")])
    catalog: Path = Path("out/catalog.jsonl")
    reference_ir: Path | None = None
    reference_trace: Path | None = None
    package_name: str = "GeneratedPlant"
    model_name: str | None = None
    stop_time: float | None = None
    repair_iterations: int = 6
    skip_simulation: bool = False
    #: C-08. Re-read the SysML we just emitted and build the Modelica from *that*, so the
    #: derivation the briefing's top band asks for is the actual code path rather than an
    #: argument about a shared source. Off by default until the bench is green on it:
    #: standing rule 6, the gate is sacred.
    from_sysml: bool = False
    #: Where the binding memory lives (catalog/memory.py). None runs without it: nothing is
    #: read from earlier runs and nothing this run learns is kept. The CLI turns it on by
    #: default, next to the catalog; tests and library callers opt in.
    memory_path: Path | None = None
    #: Normalised-RMSE pass/fail bound for an auto-matched reference-trace signal comparison
    #: (`verify/acceptance.py:build_signal_map`/`compare_signals`). Only ever applied to a
    #: pair the matcher found with no ambiguity, and only once the trace itself has passed
    #: `screen_reference` -- so loosening this does not let a bad reference trace through,
    #: it only changes how closely a *trusted* one must be tracked.
    reference_tolerance: float = 0.1
    #: Flatten the generated plant and every library class it uses (`modelica/SpecAlive.mo`,
    #: the Modelica Standard Library) into one self-contained file via omc's own
    #: `saveTotalModel`, so the one Modelica artifact a reader gets is the only file the
    #: model needs -- no companion library file, no separate `loadModel(Modelica)`. On by
    #: default; the compile/repair/simulate stages fall back to the original multi-file
    #: load (and say so) if consolidation itself fails for any reason.
    consolidate: bool = True


#: A pass is only repeated when it added a declared fallback, and each blocked transition is
#: backed up at most once, so this terminates on its own. It needs room to run because
#: fallbacks are applied one step per region per pass -- fixing a cascade in one go measures
#: downstream steps against a trace where their predecessor was still deadlocked. The cap is
#: here so a bug cannot turn that into an unbounded loop of omc invocations.
MAX_BUILD_PASSES = 6


@dataclass
class PipelineResult:
    model: SystemModel | None = None
    events: list[PipelineEvent] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    scorecard: Scorecard | None = None
    #: Why each red check is red. Populated after scoring; read by the report.
    diagnoses: list[Diagnosis] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.gate.get("compiled")) and bool(self.gate.get("simulated"))

    @property
    def verdict(self) -> tuple[str, str]:
        """(level, reason). Levels, worst first:

          NOT_MET     it does not compile and simulate;
          INERT       it simulates and nothing happens;
          INCOMPLETE  it runs, but parts or connections the evidence states are not in it;
          UNVERIFIED  complete and live, but its acceptance checks fail or none could be run;
          MET         complete, live, and every checkable acceptance check passes.

        "Compiles and simulates" used to be the whole gate, and a model could pass it with
        its leakage branch, its sensor and its header pruned away. Each level here is a
        claim the run can actually back.
        """
        if not self.ok:
            return "NOT_MET", "the Modelica does not compile and simulate"
        if self.gate.get("live") is False:
            return "INERT", str(self.gate.get("liveness", "nothing moves in the run"))
        s = self.gate.get("structure") or {}
        if s and (s["parts_emitted"] < s["parts_total"]
                  or s["connections_written"] < s["connections_total"]):
            return "INCOMPLETE", (
                f"{s['parts_emitted']}/{s['parts_total']} evidenced parts and "
                f"{s['connections_written']}/{s['connections_total']} evidenced connections "
                f"are in the model")
        card = self.scorecard
        if card is None or card.total == 0:
            return "UNVERIFIED", "no acceptance check could be run against the result"
        if card.passed < card.total:
            return "UNVERIFIED", f"{card.total - card.passed} of {card.total} checkable acceptance checks fail"
        rest = getattr(card, "unchecked", 0)
        return "MET", (f"complete, live, and all {card.total} checkable acceptance checks pass"
                       + (f" ({rest} more could not be checked)" if rest else ""))


#: Written once, the first time a run writes claims.json: the shape never varies between
#: runs, so re-deriving it from `model.claims` each time (and for every build pass) would be
#: pure waste. Kept module-level, not per-Pipeline-instance, because schema generation has
#: nothing to do with any one run's state.
_CLAIMS_SCHEMA = EvidenceClaim.model_json_schema()


def _write_claims(out_dir: Path, model: SystemModel) -> Path:
    """The extracted claims as their own structured JSON artifact, schema included.

    Claims already live inside `ir.json` (as `SystemModel.claims`), but a reader who wants
    just the evidence trail -- what was asserted, from where, with what confidence, before
    any conflict was resolved -- had to pull it out of the full IR dump themselves. This is
    that array on its own, plus the JSON Schema it validates against (`claims.schema.json`),
    so a consumer (a reviewer's script, a second tool) can check its shape without reading
    EvidenceClaim's Python definition.
    """
    path = out_dir / "claims.json"
    path.write_text(
        json.dumps([c.model_dump(mode="json") for c in model.claims], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "claims.schema.json").write_text(
        json.dumps(_CLAIMS_SCHEMA, indent=2), encoding="utf-8"
    )
    return path


class Pipeline:
    def __init__(self, cfg: PipelineConfig, router: Any | None = None) -> None:
        self.cfg = cfg
        #: Check ids whose contradiction an earlier pass already proved, so a later pass does
        #: not re-diagnose them from a trace that no longer shows it.
        self._contradicted: set[str] = set()
        #: Catalog fixes already folded into the IR, so a pass cannot re-apply one and
        #: retry forever on a correction that has already landed.
        self._written_back: set[str] = set()
        self._pass = 1
        self.router = router
        self.memory = None
        if cfg.memory_path is not None:
            from .catalog.memory import BindingMemory

            self.memory = BindingMemory.load(cfg.memory_path)
        self.result = PipelineResult()
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ event plumbing
    def _emit(self, stage: Stage, status: str, message: str = "", **data: Any) -> PipelineEvent:
        # Stamp wall-clock elapsed on every event. The UI needs it to show a stage actually
        # taking time rather than a list that redraws instantly and looks fake.
        ev = PipelineEvent(stage, status, message, data)  # type: ignore[arg-type]
        ev.elapsed_s = round(time.time() - getattr(self, "_t0", time.time()), 2)
        self.result.events.append(ev)
        return ev

    def run(self, on_event: Callable[[PipelineEvent], None] | None = None) -> PipelineResult:
        for ev in self.stream():
            if on_event:
                on_event(ev)
        return self.result

    # ------------------------------------------------------------------ the pipeline
    def stream(self) -> Iterator[PipelineEvent]:
        cfg = self.cfg
        t0 = self._t0 = time.time()

        # ---------------------------------------------------------- 1. ingest
        yield self._emit("ingest", "start", f"reading {cfg.packet}")
        docs = load_packet(cfg.packet)
        summary = packet_summary(docs)
        unread = [s for s in summary if s["warnings"]]
        (cfg.out_dir / "packet.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        yield self._emit(
            "ingest",
            "warn" if unread else "ok",
            f"{len(docs)} sources, {sum(s['blocks'] for s in summary)} blocks"
            + (f", {len(unread)} with warnings" if unread else ""),
            summary=summary,
        )

        # ---------------------------------------------------------- 2/3. extract + reconcile
        # A reference IR short-circuits both stages. This is how B, C and D work in parallel on
        # day one without waiting for A's extractor, and how the demo stays reproducible.
        if cfg.reference_ir and cfg.reference_ir.exists():
            model = SystemModel.model_validate_json(cfg.reference_ir.read_text(encoding="utf-8"))
            # Keep the real source list even when the IR is supplied: the report must show
            # what was actually read from disk, not what a fixture happens to record.
            if not model.sources:
                model.sources = [d.source for d in docs]
            yield self._emit("extract", "skip", f"using reference IR {cfg.reference_ir.name}")
            yield self._emit("reconcile", "skip", "using reference IR")
        else:
            yield self._emit("extract", "start", "lifting claims from documents")
            from .extract.claims import extract_claims

            claims = extract_claims(docs, router=self.router)
            claims.extend((yield from self._extract_skeleton(docs, claims)))
            det = sum(1 for c in claims if c.extracted_by == "t0_deterministic")
            yield self._emit(
                "extract", "ok",
                f"{len(claims)} claims ({100 * det // max(len(claims), 1)}% deterministic)",
            )

            yield self._emit("reconcile", "start", "resolving conflicts")
            from .reconcile.builder import build_model

            model = build_model(docs, claims)
            contested = sum(1 for d in model.decisions if d.loser_claim_ids)
            provisional = sum(1 for d in model.decisions if d.provisional)
            yield self._emit(
                "reconcile",
                "warn" if provisional else "ok",
                f"{contested} conflicts resolved, {provisional} left provisional",
            )

        self.result.model = model
        (cfg.out_dir / "ir.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
        self.result.artifacts["IR"] = str(cfg.out_dir / "ir.json")
        self.result.artifacts["Claims"] = str(_write_claims(cfg.out_dir, model))

        # ---------------------------------------------------------- 4. validate
        yield self._emit("validate", "start", "static checks on the extracted model")
        report = validate(model)
        for gap in report.as_gaps():
            if not any(g.detail == gap.detail for g in model.gaps):
                model.gaps.append(gap)
        self._validation = report
        yield self._emit(
            "validate",
            "fail" if report.errors else ("warn" if report.warnings else "ok"),
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
            findings=[str(f) for f in report.findings],
        )
        if report.errors:
            # Errors here mean the IR is not emittable. Stop: generating from a broken IR just
            # moves the failure somewhere less legible.
            yield self._emit("sysml", "skip", "blocked by validation errors")
            return

        # ---------------------------------------------------------- 5-9. build and verify
        # SysML is emitted inside the pass, not here: see `_emit_sysml`.
        #
        # A pass repeats only when it learned something the IR did not already know: a guard
        # proved unreachable (a declared fallback is added, SA-05) or a catalog-tier repair
        # corrected a binding. Both are recorded so they cannot be re-derived, so this
        # terminates on its own; MAX_BUILD_PASSES is there in case a bug says otherwise.
        runner = OmcRunner(workdir=str(cfg.out_dir / "work"))
        for attempt in range(1, MAX_BUILD_PASSES + 1):
            self._pass = attempt
            verdict = yield from self._build_and_verify(model, runner, t0)
            if verdict != "retry":
                break

        yield from self._finish(t0, runner)

    # ------------------------------------------------------------------ memory
    def _learn(self, model: SystemModel, *, outcome: Any | None, simulated: bool,
               live: bool = False) -> None:
        """Write back what omc just proved about this pass's bindings.

        Called twice per pass: once after the repair loop, to record the classes it had to
        correct and the ones the safety nets withdrew, and once after a successful
        simulation, to record every binding that made it into a running model with
        something attached. Only omc's verdict counts as evidence -- a binding that was
        merely chosen teaches nothing.
        """
        mem = self.memory
        if mem is None:
            return
        from .emit.modelica import block_signature

        packet = self.cfg.packet.name
        emission = getattr(self, "_emission", {})
        if not simulated:
            for sig, cls in emission.get("withdrawn", []):
                if cls:
                    mem.record_failure(sig, cls, packet)
            for edit in (outcome.ir_edits if outcome is not None else []):
                blk = model.block(edit.block) if edit.kind == "class" and edit.block else None
                # A connector-family correction is about the pairing, not the class on its
                # own, so it is not held against the class. A class the catalog does not
                # contain, or a mistyped one, is.
                if (edit.detail or "").startswith("connector package"):
                    continue
                if blk is not None and edit.old:
                    mem.record_failure(block_signature(blk), edit.old, packet)
        else:
            strength = emission.get("strength", {})
            emitted = set(emission.get("emitted", []))
            wired = {ref for c in model.connections
                     if {c.source.split(".", 1)[0], c.target.split(".", 1)[0]} <= emitted
                     for ref in (c.source, c.target)}
            for bid in emission.get("emitted", []):
                blk = model.block(bid)
                if blk is None or not blk.modelica_class:
                    continue
                # A class that could not host a port the evidence wires to it simulated only
                # because the emitter dropped that wire. The IAQ sensor bound to a trace
                # source ran -- with the control loop open -- and was remembered as a
                # success, so the next run repeated it. That is a failure of the class for
                # this kind of part, whatever omc said about the whole.
                if any(not p.name and f"{blk.id}.{p.id}" in wired for p in blk.ports):
                    mem.record_failure(block_signature(blk), blk.modelica_class, packet)
                    continue
                # A guess that merely compiled proves little -- a voltage ramp compiles in
                # place of a current ramp. It earns credit only from a run that did
                # something; declared and decisive bindings earn it from any clean build.
                if strength.get(bid) == "weak" and not live:
                    continue
                mem.record_success(block_signature(blk), blk.modelica_class, packet)
                if blk.connector_family:
                    for d in blk.domains:
                        if d != "unknown":
                            mem.record_family(d, blk.connector_family, ok=True)
        try:
            mem.save()
        except OSError:
            pass  # a read-only checkout still runs; it just does not learn

    # ------------------------------------------------------------------ extraction
    def _extract_skeleton(
        self, docs: list[Document], claims: list[Any]
    ) -> Iterator[PipelineEvent]:
        """One long-context read of the whole packet, to catch what no single span states.

        Runs after the deterministic and per-span passes, never instead of them, and is
        told which tags they already found so it spends its attention on the gaps. With no
        router (`--provider none`) there is nothing to run and the pipeline is unchanged.

        Yields events and *returns* the extra claims, so the caller writes
        `claims.extend((yield from ...))`.
        """
        if self.router is None:
            return []
        from .extract.skeleton import extract_skeleton

        det = [c for c in claims if c.extracted_by == "t0_deterministic"]
        known = sorted({str(c.subject).strip() for c in det})[:400]
        # Subjects a register already types. The whole-packet read is told not to restate
        # what these are -- only to supply the Modelica class they lack, and to name the
        # parts no table mentions at all.
        described = sorted({
            str(c.subject).strip() for c in det
            if str(c.predicate).lower().replace(" ", "") in
            ("type", "kind", "class", "modelclass", "role", "name")
        })
        index = None
        if self.cfg.catalog.exists():
            try:
                index = CatalogIndex.from_file(self.cfg.catalog)
            except Exception:
                index = None
        extra, notes = extract_skeleton(
            docs, self.router, known_tags=known, described=described, index=index
        )
        for note in notes:
            yield self._emit("extract", "ok" if extra else "warn", note)
        return extra

    # ------------------------------------------------------------------ SysML
    def _emit_sysml(self, model: SystemModel, note: str) -> Iterator[PipelineEvent]:
        """Write the architecture artefact from the current IR.

        Called at the top of every build pass rather than once per run, because the IR is no
        longer fixed after validation: a declared fallback (SA-05) adds a transition, and a
        catalog-tier repair corrects a binding. Both change what the plant *is*, so both have
        to reach the SysML before the Modelica is derived from it -- otherwise the two
        deliverables describe different plants and, under --from-sysml, the correction never
        reaches the code at all.
        """
        yield self._emit("sysml", "start", note)
        path = emit_sysml(model, self.cfg.out_dir / f"{model.name}.sysml")
        losses = round_trip_check(model, path.read_text(encoding="utf-8"))
        self.result.artifacts["SysML v2"] = str(path)
        yield self._emit(
            "sysml", "warn" if losses else "ok",
            f"{path.name}" + (f", {len(losses)} element(s) lost in round-trip" if losses
                              else ", round-trip clean"),
            losses=losses,
        )

    @staticmethod
    def _structural_diagnostic(outcome: Any) -> str:
        """What to tell structural repair the compiler said.

        Prefer the loop's own refusal, because it is the more informative sentence: it already
        names the unbound blocks and the equation deficit. Fall back to the raw diagnostics
        when the run failed some other way, so this stage still gets the real error rather
        than a summary of why there isn't one.
        """
        last = outcome.steps[-1] if outcome.steps else None
        if last is not None and last.method == "declared":
            return last.description
        if outcome.final is not None and outcome.final.diagnostics:
            return "\n".join(d.raw for d in outcome.final.diagnostics[:3])
        return "the model did not compile"

    def _build_and_verify(
        self, model: SystemModel, runner: OmcRunner, t0: float
    ) -> Iterator[PipelineEvent]:
        """Emit, compile, simulate, score -- the part of the run that can be worth repeating.

        Returns "done", "halt" (nothing more can be learned this run) or "retry" (a declared
        fallback was added and the model should be built again). The caller reports either
        way: a run that halts still owes the reader a report saying why.
        """
        cfg = self.cfg

        # ---------------------------------------------------------- 5. SysML
        yield from self._emit_sysml(
            model,
            "emitting SysML v2" if self._pass == 1 else
            f"pass {self._pass}: re-emitting SysML from the corrected IR",
        )

        # ---------------------------------------------------------- 6. Modelica
        yield self._emit("modelica", "start", "binding components and emitting Modelica")
        index = None
        if cfg.catalog.exists():
            try:
                index = CatalogIndex.from_file(cfg.catalog)
            except Exception as exc:
                yield self._emit("modelica", "warn", f"catalog unavailable: {exc}")
        source = model
        if cfg.from_sysml:
            # C-08: everything below this line comes from the emitted SysML text, not the IR.
            # `SimulationProfile` carries the handful of fields SysML does not express --
            # scan period, solver settings, and (D-2, a defect) the global setpoints that
            # transition guards reference but nothing declares.
            from .emit.sysml_read import SimulationProfile, read_sysml, to_system_model

            # Read the path from the artifact record, not from a local. The multi-pass build
            # re-emits the SysML between passes, so the right file is whichever was written
            # most recently -- and once the build loop moved into its own method, the local
            # that used to hold it stopped being in scope here at all.
            emitted = self.result.artifacts.get("SysML v2")
            try:
                if not emitted:
                    raise ValueError("no SysML has been emitted yet")
                parsed = read_sysml(Path(emitted).read_text(encoding="utf-8"))
                source = to_system_model(
                    parsed, SimulationProfile.from_ir(model), index=index, name=model.name
                )
                yield self._emit(
                    "modelica", "ok",
                    f"derived from SysML: {len(parsed.parts)} parts, "
                    f"{len(parsed.interfaces)} interfaces, {len(parsed.transitions)} transitions",
                    from_sysml=True,
                )
            except (ValueError, OSError) as exc:
                # A construct the reader does not know would silently drop an element, so
                # fall back to the IR rather than emit a quietly incomplete model.
                source = model
                yield self._emit("modelica", "warn", f"SysML path unusable, using IR: {exc}")

        emission: dict[str, Any] = {}
        mo_path, tiers = emit_modelica(
            source, cfg.out_dir / f"{cfg.package_name}.mo",
            index=index, router=self.router, package=cfg.package_name,
            memory=self.memory, report=emission,
        )
        self._emission = emission
        for note in emission.get("families", []):
            yield self._emit("modelica", "ok", note)
        if self.memory is not None and emission.get("memory_used"):
            yield self._emit("modelica", "ok",
                             f"{emission['memory_used']} binding(s) from earlier runs "
                             f"({self.memory.summary()})")
        self.result.artifacts["Modelica"] = str(mo_path)
        yield self._emit(
            "modelica", "warn" if tiers.get("unbound") else "ok",
            f"{mo_path.name}: " + ", ".join(f"{k}={v}" for k, v in tiers.items() if v),
            tiers=tiers,
        )
        real = emission.get("realised") or {}
        if real:
            self.result.gate["structure"] = real
            complete = (real["parts_emitted"] == real["parts_total"]
                        and real["connections_written"] == real["connections_total"])
            yield self._emit(
                "modelica", "ok" if complete else "warn",
                f"evidence in the model: {real['parts_emitted']}/{real['parts_total']} parts, "
                f"{real['connections_written']}/{real['connections_total']} connections"
                + (f", {real['inputs_assumed']} input(s) assumed" if real["inputs_assumed"] else ""),
                structure=real,
            )
            for miss in real["connections_missing"][:6]:
                yield self._emit("modelica", "warn", f"  not in the model: {miss['connection']} -- {miss['why']}")

        # ---------------------------------------------------------- 7/8. compile + simulate
        scenario = model.scenarios[0] if model.scenarios else None
        model_name = cfg.model_name or (
            f"{cfg.package_name}.{scenario.name}" if scenario else f"{cfg.package_name}.Plant"
        )
        stop_time = cfg.stop_time or (scenario.stop_time if scenario else 1.0)
        # Everything from here on compiles, repairs and simulates `mo_path` against
        # `support_files` and `libraries`. Consolidation below may replace all three with
        # the flattened single-file equivalent (no support files, no stdlib load); nothing
        # downstream needs to know which happened.
        support_files: list[Path] = list(cfg.library_files)
        libraries: tuple[str, ...] = ("Modelica",)

        if cfg.consolidate:
            total = runner.save_total(
                model_name, [mo_path, *support_files], mo_path, timeout=max(180, cfg.repair_iterations * 60)
            )
            if total.ok and total.path is not None and total.class_name is not None:
                mo_path, model_name = total.path, total.class_name
                support_files, libraries = [], ()
                yield self._emit(
                    "modelica", "ok",
                    f"consolidated into one self-contained file ({mo_path.name}, "
                    f"class {model_name}): no companion library file needed",
                )
            else:
                # Never silent: a reader who later finds two files next to each other
                # deserves to know this was tried and did not work, not left to guess.
                yield self._emit(
                    "modelica", "warn",
                    f"could not consolidate into a single file ({total.reason or 'see log'}); "
                    f"continuing with {mo_path.name} alongside {', '.join(f.name for f in support_files)}",
                )

        # `index` is C-AI-2 / C5: without it the agent cannot ask the catalog for a verified
        # class signature and the catalog-grounded fixers all no-op, silently.
        loop = RepairLoop(runner, self.router, max_iterations=cfg.repair_iterations, index=index)

        yield self._emit("compile", "start", f"omc checkModel({model_name})")
        # C-AI-1: the repair gate now includes build+simulate, not just checkModel. Without
        # the stop time the loop exits the moment `check` is clean and a model that cannot
        # actually run reaches the user unrepaired.
        outcome = loop.run(
            model_name, mo_path, support_files,
            stop_time=None if cfg.skip_simulation else stop_time,
            libraries=libraries,
        )
        # Accumulate across passes. A successful write-back means the NEXT pass needs no
        # repair at all, so keeping only the last pass's steps would report "0 fixes" for a
        # run whose model only compiles because of them.
        self._repair_steps = getattr(self, "_repair_steps", []) + outcome.steps
        self.result.gate["compiled"] = outcome.ok
        self.result.gate["repair"] = outcome.summary()
        yield self._emit(
            "compile", "ok" if outcome.ok else "fail", outcome.summary(),
            steps=[s.__dict__ for s in outcome.steps],
        )

        # A catalog-tier fix corrected a binding decision, and binding decisions belong to
        # the IR. Patching only the .mo made the repair last exactly until the next emission
        # and left the SysML describing the uncorrected plant. Fold it upstream, then rebuild
        # from there -- which is also the only way the fix reaches the code under
        # --from-sysml, since that path reads the SysML and never sees our .mo edits.
        self._learn(model, outcome=outcome, simulated=False)
        fresh = [e for e in outcome.ir_edits if str(e) not in self._written_back]
        if fresh:
            landed = apply_ir_edits(model, fresh)
            self._written_back.update(str(e) for e in fresh)
            if landed:
                yield self._emit(
                    "compile", "warn",
                    f"{len(landed)} catalog fix(es) written back to the IR "
                    f"({'; '.join(landed)}); re-deriving SysML and Modelica from the "
                    f"corrected model",
                    writeback=landed,
                )
                return "retry"
            # Nothing matched an IR element -- the .mo is still fixed, so this is a
            # traceability gap, not a failure. Say so rather than retrying for no reason.
            yield self._emit(
                "compile", "warn",
                f"{len(fresh)} catalog fix(es) could not be traced back to an IR element; "
                f"the Modelica is repaired but the SysML will not show the correction",
            )

        # The repair loop can only edit the file the compiler pointed at. When it reports that
        # no edit could have worked -- a block never bound, so the equations it owes simply do
        # not exist -- the defect is in the IR, and refusing to act on it would leave the .mo,
        # the SysML and the IR all describing a plant that cannot run. Correct the IR instead
        # and rebuild from it; under --from-sysml that is the only path by which the fix
        # reaches the code at all.
        if not outcome.ok:
            plan = plan_structural_repair(
                model,
                self._structural_diagnostic(outcome),
                index=index,
                router=self.router,
            )
            # A gap declared on an earlier pass goes stale the moment that block binds, and a
            # stale blocking gap in the report is worse than none: it describes a defect the
            # run went on to fix. Re-derive them rather than accumulate.
            bound_now = {b.id for b in model.blocks if b.modelica_class}
            model.gaps = [
                g for g in model.gaps
                if not (g.id.startswith("GAP-STRUCT-") and g.subject in bound_now)
            ]
            for gap in plan.gaps:
                if not any(g.id == gap.id for g in model.gaps):
                    model.gaps.append(gap)
            fresh_s = [e for e in plan.edits if str(e) not in self._written_back]
            if fresh_s:
                landed_s = apply_ir_edits(model, fresh_s)
                self._written_back.update(str(e) for e in fresh_s)
                if landed_s:
                    yield self._emit(
                        "compile", "warn",
                        f"structural repair ({plan.method}) corrected the IR: "
                        f"{'; '.join(landed_s)}; re-deriving SysML and Modelica from the "
                        f"corrected model",
                        writeback=landed_s,
                        structural=plan.notes,
                    )
                    return "retry"
            if plan.notes:
                yield self._emit(
                    "compile", "warn",
                    "structural repair found nothing it could correct: " + "; ".join(plan.notes[:3]),
                    structural=plan.notes,
                )

            yield self._emit("simulate", "skip", "model does not compile")
            return "halt"

        if cfg.skip_simulation:
            yield self._emit("simulate", "skip", "--no-sim requested")
            return "halt"

        yield self._emit("simulate", "start", f"stopTime={stop_time}")
        sim = runner.simulate(
            model_name, [mo_path, *support_files],
            libraries=libraries,
            stop_time=stop_time,
            interval=(scenario.interval if scenario else None),
            tolerance=(scenario.tolerance if scenario else 1e-6),
            solver=(scenario.solver if scenario else "dassl"),
            prefix=cfg.package_name.lower(),
        )
        self.result.gate["simulated"] = sim.ok
        if sim.result_file:
            dest = cfg.out_dir / "results.csv"
            shutil.copyfile(sim.result_file, dest)
            self.result.artifacts["Results"] = str(dest)
        yield self._emit(
            "simulate", "ok" if sim.ok else "fail",
            sim.summary() + (f" -> {sim.result_file.name}" if sim.result_file else ""),
        )
        if not sim.ok:
            return "halt"

        # C10. "It simulated" is not "it worked". A model whose states never move, or whose
        # sequential controller never leaves Initial, has integrated a system in which
        # nothing happens -- and it would otherwise print HARD GATE MET above 0/10.
        live = liveness(cfg.out_dir / "results.csv", model)
        self.result.gate["live"] = live.ok
        self._learn(model, outcome=None, simulated=True, live=live.ok)
        self.result.gate["liveness"] = live.summary()
        yield self._emit(
            "simulate", "ok" if live.ok else "warn", live.summary(), live=live.ok,
        )

        # ---------------------------------------------------------- 9. verify
        yield self._emit("verify", "start", "scoring acceptance criteria")
        card = score(
            model, cfg.out_dir / "results.csv",
            reference_csv=cfg.reference_trace,
            signal_map=None,
            reference_tolerance=cfg.reference_tolerance,
            router=self.router,
            memory=self.memory,
        )
        self.result.scorecard = card
        for note in card.notes:
            yield self._emit("verify", "ok", note)
        if self.memory is not None:
            try:
                self.memory.save()
            except OSError:
                pass
        for r in card.results:
            for rid in r.requirement_ids:
                req = model.requirement(rid)
                if req and r.passed and r.check_id not in req.verified_by:
                    req.verified_by.append(r.check_id)

        # A failed check is a symptom. Say which ones are the disease: a setpoint the plant
        # provably cannot reach is a contradiction in the customer's own evidence and the
        # brief requires it to be flagged, while the checks downstream of it are noise.
        diag_log = AssumptionLog()
        diagnoses = diagnose(model, card, read_result(cfg.out_dir / "results.csv"))
        # Drop the previous pass's knock-on notes -- they describe a model we no longer ship
        # -- but keep every proved contradiction, which is the finding and is not re-derivable
        # from the final trace once a fallback lets the step exit early.
        model.gaps = [
            g for g in model.gaps
            if not (g.id.startswith("GAP-GUARD-") and g.severity != "blocking")
        ]
        # Plan the fallbacks before recording anything: a verdict on a step downstream of a
        # deadlock we are about to remove is not evidence, and recording it would lock in a
        # contradiction that the next pass disproves.
        plan = apply_declared_fallbacks(model, diagnoses, diag_log)
        model.gaps.extend(
            record(model, diagnoses, diag_log,
                   already_known=self._contradicted | plan.deferred, pass_no=self._pass)
        )
        self._contradicted.update(
            d.check_id for d in diagnoses
            if d.verdict == "unreachable" and d.check_id not in plan.deferred
        )
        self.result.diagnoses = diagnoses

        yield self._emit(
            "verify", "ok" if card.ok else "warn", card.summary(),
            failed=[r.check_id for r in card.results if not r.passed],
        )
        blocking = [d for d in diagnoses if d.verdict == "unreachable"]
        if blocking:
            yield self._emit(
                "verify", "warn",
                f"{len(blocking)} setpoint(s) unreachable under the packet's own parameters "
                f"-- flagged, not retuned",
                failed=[d.check_id for d in blocking],
            )

        # A step whose guard is provably unreachable deadlocks the sequence, so one defect in
        # the customer's specification costs us every step after it. SA-05 keeps their guard
        # exactly as written and adds a marked fallback beside it. The contradiction stays
        # flagged and the setpoint stays untouched; what changes is how much of the sequence
        # we can actually exercise and show. See ir/fallback.py.
        fallbacks = plan.added
        diag_log.attach(model)
        if fallbacks:
            yield self._emit(
                "verify", "warn",
                f"{len(fallbacks)} step(s) cannot exit under the packet's own numbers; "
                f"adding a declared fallback (SA-05) and re-running the model",
                failed=[f.fallback_for or f.id for f in fallbacks],
            )
            return "retry"
        return "done"

    # ------------------------------------------------------------------ report
    def _finish(self, t0: float, runner: OmcRunner) -> Iterator[PipelineEvent]:
        cfg = self.cfg
        yield self._emit("report", "start", "building the judge packet")
        model = self.result.model
        assert model is not None
        (cfg.out_dir / "ir.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
        _write_claims(cfg.out_dir, model)
        path = build_report(
            model,
            out_dir=cfg.out_dir,
            gate=self.result.gate,
            scorecard=self.result.scorecard,
            results_csv=(cfg.out_dir / "results.csv"),
            router_stats=self.router.stats() if self.router else None,
            repair_steps=getattr(self, "_repair_steps", None),
            validation=getattr(self, "_validation", None),
            environment={
                **describe_environment(runner.omc),
                "elapsed_s": round(time.time() - t0, 1),
                "packet": str(cfg.packet),
            },
            artifacts=self.result.artifacts,
        )
        self.result.artifacts["Report"] = str(path)
        yield self._emit("report", "ok", str(path), elapsed_s=round(time.time() - t0, 1))
