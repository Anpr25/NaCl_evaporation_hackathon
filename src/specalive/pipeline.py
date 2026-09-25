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
from .ingest.registry import load_packet, packet_summary
from .ir.system import SystemModel
from .ir.validate import validate
from .ir.assumptions import AssumptionLog
from .ir.fallback import apply_declared_fallbacks
from .repair.loop import RepairLoop
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

        mo_path, tiers = emit_modelica(
            source, cfg.out_dir / f"{cfg.package_name}.mo",
            index=index, router=self.router, package=cfg.package_name,
        )
        self.result.artifacts["Modelica"] = str(mo_path)
        yield self._emit(
            "modelica", "warn" if tiers.get("unbound") else "ok",
            f"{mo_path.name}: " + ", ".join(f"{k}={v}" for k, v in tiers.items() if v),
            tiers=tiers,
        )

        # ---------------------------------------------------------- 7/8. compile + simulate
        scenario = model.scenarios[0] if model.scenarios else None
        model_name = cfg.model_name or (
            f"{cfg.package_name}.{scenario.name}" if scenario else f"{cfg.package_name}.Plant"
        )
        stop_time = cfg.stop_time or (scenario.stop_time if scenario else 1.0)

        # `index` is C-AI-2 / C5: without it the agent cannot ask the catalog for a verified
        # class signature and the catalog-grounded fixers all no-op, silently.
        loop = RepairLoop(runner, self.router, max_iterations=cfg.repair_iterations, index=index)

        yield self._emit("compile", "start", f"omc checkModel({model_name})")
        # C-AI-1: the repair gate now includes build+simulate, not just checkModel. Without
        # the stop time the loop exits the moment `check` is clean and a model that cannot
        # actually run reaches the user unrepaired.
        outcome = loop.run(
            model_name, mo_path, list(cfg.library_files),
            stop_time=None if cfg.skip_simulation else stop_time,
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

        if not outcome.ok:
            yield self._emit("simulate", "skip", "model does not compile")
            return "halt"

        if cfg.skip_simulation:
            yield self._emit("simulate", "skip", "--no-sim requested")
            return "halt"

        yield self._emit("simulate", "start", f"stopTime={stop_time}")
        sim = runner.simulate(
            model_name, [mo_path, *cfg.library_files],
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
        )
        self.result.scorecard = card
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
