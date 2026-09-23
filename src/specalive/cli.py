"""SpecAlive command line.

    specalive doctor                      check the toolchain on this machine
    specalive harvest                     build the Modelica catalog (once per machine)
    specalive run <packet>                the whole pipeline
    specalive gate <model> <files...>     just the hard gate: does it compile and run
    specalive bench                       every benchmark packet, pass-rate matrix
    specalive serve                       the web app

Owner: D.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .pipeline import Pipeline, PipelineConfig, PipelineEvent

app = typer.Typer(add_completion=False, help="From specs to live engineering models.")
con = Console()

_STATUS_STYLE = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim", "start": "cyan"}


def _print(ev: PipelineEvent) -> None:
    if ev.status == "start":
        con.print(f"[dim]{ev.stage:<9}[/] {ev.message}")
        return
    mark = {"ok": "ok  ", "warn": "warn", "fail": "FAIL", "skip": "skip"}[ev.status]
    con.print(f"[{_STATUS_STYLE[ev.status]}]{mark}[/] [bold]{ev.stage:<9}[/] {ev.message}")


def _router(mode: str):
    if mode == "none":
        return None
    from .llm.router import Router

    try:
        return Router(mode=mode)
    except Exception as exc:
        con.print(f"[yellow]warn[/] router unavailable ({exc}); running deterministic-only")
        return None


# ---------------------------------------------------------------------------------- doctor


@app.command()
def doctor() -> None:
    """Check every external dependency and say plainly what is missing."""
    from .llm.router import Router
    from .verify.omc import describe_environment

    t = Table(title="SpecAlive environment", show_lines=False)
    t.add_column("Component")
    t.add_column("Status")
    t.add_column("Detail", overflow="fold")

    env = describe_environment()
    ok = env.get("omc_version") is not None
    t.add_row(
        "OpenModelica",
        "[green]found[/]" if ok else "[red]MISSING[/]",
        env.get("omc_version") or env.get("error", ""),
    )
    t.add_row("Python", "[green]ok[/]", sys.version.split()[0])

    cat = Path("out/catalog.jsonl")
    n = sum(1 for _ in cat.open(encoding="utf-8")) if cat.exists() else 0
    t.add_row(
        "Modelica catalog",
        "[green]built[/]" if n else "[yellow]not built[/]",
        f"{n} classes" if n else "run `specalive harvest`",
    )

    try:
        r = Router(mode="auto")
        for tier in sorted(r.cfg["tiers"]):
            if r.cfg["tiers"][tier].get("kind") == "deterministic":
                continue
            up = r.is_available(tier)
            model = r.cfg["tiers"][tier].get("model", "")
            t.add_row(
                f"  {tier}",
                "[green]up[/]" if up else "[dim]down[/]",
                f"{model}" + ("" if up else "  (no key, or daemon not running)"),
            )
    except Exception as exc:
        t.add_row("LLM router", "[red]error[/]", str(exc))

    con.print(t)
    if not ok:
        con.print("\n[red]The hard gate cannot pass without OpenModelica.[/] "
                  "Install it, or set SPECALIVE_OMC to the omc executable.")
        raise typer.Exit(1)


# --------------------------------------------------------------------------------- harvest


@app.command()
def harvest(
    libraries: str = typer.Option("Modelica", help="Comma-separated libraries to introspect"),
    include: Optional[str] = typer.Option("modelica/SpecAlive.mo", help="Extra .mo files"),
    out: Path = typer.Option(Path("out/catalog.jsonl")),
) -> None:
    """Introspect the installed Modelica libraries into a searchable catalog.

    Deterministic, offline and free. Run once per machine; the result is what stops the
    generator inventing classes that do not exist.
    """
    from .catalog.harvest import harvest as do_harvest
    from .verify.omc import find_omc

    libs = [x.strip() for x in libraries.split(",") if x.strip()]
    extra = [Path(x.strip()) for x in (include or "").split(",") if x.strip()]
    con.print(f"harvesting {libs} (+{len(extra)} local file(s)) ... this takes a minute")
    path = do_harvest(libs, omc=find_omc(), extra_files=extra, out_path=out)
    n = sum(1 for _ in path.open(encoding="utf-8"))
    con.print(f"[green]ok[/] {n} classes -> {path}")


# ------------------------------------------------------------------------------------- run


@app.command()
def run(
    packet: Path = typer.Argument(..., help="Directory (or single file) of engineering evidence"),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    provider: str = typer.Option("auto", help="auto | local | cloud | replay | none"),
    reference_ir: Optional[Path] = typer.Option(
        None, "--reference-ir", help="Skip extraction and use this IR (fixtures, debugging, demo)"
    ),
    reference_trace: Optional[Path] = typer.Option(
        None, "--reference-trace", help="Supplied result trace to screen and compare against"
    ),
    package: str = typer.Option("GeneratedPlant", help="Generated Modelica package name"),
    model: Optional[str] = typer.Option(None, help="Fully qualified model to simulate"),
    stop_time: Optional[float] = typer.Option(None, "--stop-time"),
    no_sim: bool = typer.Option(False, "--no-sim", help="Compile only; skip simulation"),
    repair: int = typer.Option(6, help="Maximum repair iterations"),
) -> None:
    """Run the whole pipeline: evidence in, SysML + Modelica + results + report out."""
    cfg = PipelineConfig(
        packet=packet,
        out_dir=out,
        reference_ir=reference_ir,
        reference_trace=reference_trace,
        package_name=package,
        model_name=model,
        stop_time=stop_time,
        repair_iterations=repair,
        skip_simulation=no_sim,
    )
    result = Pipeline(cfg, _router(provider)).run(on_event=_print)

    con.print()
    t = Table(title="Artifacts", show_header=False)
    for k, v in result.artifacts.items():
        t.add_row(f"[bold]{k}[/]", v)
    con.print(t)

    if result.scorecard:
        card = result.scorecard
        con.print(
            f"\nacceptance: [{'green' if card.ok else 'yellow'}]{card.summary()}[/]"
        )
        for r in card.results:
            if not r.passed:
                con.print(f"  [red]FAIL[/] {r.check_id}: {r.detail}")

    if not result.ok:
        con.print("\n[red]HARD GATE NOT MET[/] - the Modelica does not compile and run.")
        raise typer.Exit(1)
    con.print("\n[green]HARD GATE MET[/] - the model compiles and simulates.")


# ------------------------------------------------------------------------------------ gate


@app.command()
def gate(
    model: str = typer.Argument(..., help="Fully qualified model name"),
    files: list[Path] = typer.Argument(..., help="Modelica files to load, in order"),
    stop_time: float = typer.Option(1.0, "--stop-time"),
    check_only: bool = typer.Option(False, "--check-only"),
) -> None:
    """Just the hard gate. Fast feedback while hacking on Modelica by hand."""
    from .verify.omc import OmcRunner

    runner = OmcRunner()
    res = runner.check(model, files)
    con.print(f"check    {'[green]ok[/]' if res.ok else '[red]FAIL[/]'}  {res.summary()}")
    for d in res.diagnostics[:8]:
        con.print(f"  [red]{d.kind}[/] {d.locate()}  {d.message}")
    if not res.ok or check_only:
        raise typer.Exit(0 if res.ok else 1)

    sim = runner.simulate(model, files, stop_time=stop_time)
    con.print(f"simulate {'[green]ok[/]' if sim.ok else '[red]FAIL[/]'}  {sim.summary()}")
    for d in sim.diagnostics[:8]:
        con.print(f"  [red]{d.kind}[/] {d.message}")
    if sim.result_file:
        con.print(f"  results -> {sim.result_file}")
    raise typer.Exit(0 if sim.ok else 1)


# ----------------------------------------------------------------------------------- bench


@app.command()
def bench(
    root: Path = typer.Option(Path("benchmarks")),
    provider: str = typer.Option("auto"),
    only: Optional[str] = typer.Option(None, help="Run just this benchmark"),
) -> None:
    """Run every benchmark packet and print the pass-rate matrix.

    This is the evidence that the system is domain-general rather than tuned to one packet.
    """
    import yaml

    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if only and d.name != only:
            continue
        spec_path = d / "expectations.yaml"
        if not spec_path.exists():
            con.print(f"[dim]skip[/] {d.name} (no expectations.yaml)")
            continue
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        packet = d / spec.get("packet", "sources")
        if not packet.exists():
            con.print(f"[yellow]skip[/] {d.name}: packet path {packet} does not exist")
            rows.append([d.name, "-", "-", "-", "packet missing"])
            continue

        con.print(f"\n[bold]{d.name}[/]")
        cfg = PipelineConfig(
            packet=packet,
            out_dir=Path("out") / d.name,
            reference_ir=(d / spec["reference_ir"]) if spec.get("reference_ir") else None,
            reference_trace=(d / spec["reference_trace"]) if spec.get("reference_trace") else None,
            package_name=spec.get("package", "GeneratedPlant"),
            model_name=spec.get("model"),
            stop_time=spec.get("stop_time"),
        )
        res = Pipeline(cfg, _router(provider)).run(on_event=_print)
        card = res.scorecard
        rows.append([
            d.name,
            "yes" if res.gate.get("compiled") else "no",
            "yes" if res.gate.get("simulated") else "no",
            f"{card.passed}/{card.total}" if card else "-",
            spec.get("domain", ""),
        ])

    t = Table(title="Benchmark matrix")
    for c in ("Packet", "Compiles", "Simulates", "Acceptance", "Domain"):
        t.add_column(c)
    for r in rows:
        style = "green" if r[1] == "yes" and r[2] == "yes" else "red"
        t.add_row(f"[{style}]{r[0]}[/]", *[str(x) for x in r[1:]])
    con.print()
    con.print(t)
    if any(r[1] != "yes" or r[2] != "yes" for r in rows):
        raise typer.Exit(1)


# ----------------------------------------------------------------------------------- serve


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    provider: str = typer.Option("auto"),
) -> None:
    """Start the web app."""
    import os

    import uvicorn

    os.environ["SPECALIVE_PROVIDER"] = provider
    con.print(f"SpecAlive on http://{host}:{port}  (provider={provider})")
    uvicorn.run("specalive.web.app:app", host=host, port=port, log_level="warning")


@app.command("ir-diff")
def ir_diff(
    extracted: Path = typer.Argument(..., help="IR produced by the pipeline"),
    reference: Path = typer.Argument(..., help="Hand-built reference IR"),
) -> None:
    """Score an extracted IR against a reference. Turns 'did extraction work' into a number."""
    from .ir.system import SystemModel

    a = SystemModel.model_validate_json(extracted.read_text(encoding="utf-8"))
    b = SystemModel.model_validate_json(reference.read_text(encoding="utf-8"))

    t = Table(title=f"{extracted.name} vs {reference.name}")
    for c in ("Element", "Extracted", "Reference", "Recall", "Missing"):
        t.add_column(c, overflow="fold")
    total_hit = total_ref = 0
    for label, got, want in (
        ("requirements", {r.id for r in a.requirements}, {r.id for r in b.requirements}),
        ("blocks", {x.id for x in a.blocks}, {x.id for x in b.blocks}),
        ("connections", {(c.source, c.target) for c in a.connections},
         {(c.source, c.target) for c in b.connections}),
        ("signals", {s.id for s in a.signals}, {s.id for s in b.signals}),
        ("states", {s.id for sm in a.state_machines for s in sm.states},
         {s.id for sm in b.state_machines for s in sm.states}),
        ("parameters", {p.id for p in a.parameters}, {p.id for p in b.parameters}),
    ):
        hit = len(got & want)
        total_hit += hit
        total_ref += len(want)
        missing = sorted(str(x) for x in (want - got))[:5]
        t.add_row(label, str(len(got)), str(len(want)),
                  f"{100 * hit // max(len(want), 1)}%", ", ".join(missing) or "-")
    con.print(t)
    con.print(f"overall recall: [bold]{100 * total_hit // max(total_ref, 1)}%[/]")


if __name__ == "__main__":
    app()
