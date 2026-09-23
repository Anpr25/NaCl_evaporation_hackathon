"""FastAPI front end: upload a packet, watch the pipeline, inspect the artifacts.

The CLI and this app drive the identical `Pipeline.stream()`, so there is no chance of the
demo showing something the command line does not do. Progress is Server-Sent Events -- no
websockets, no build step, no npm.

Owner: D.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from ..pipeline import Pipeline, PipelineConfig

app = FastAPI(title="SpecAlive", docs_url="/api/docs")

STATIC = Path(__file__).parent / "static"
RUNS = Path("out/runs")
RUNS.mkdir(parents=True, exist_ok=True)

#: run_id -> {"packet": Path, "out": Path, "options": {...}}
_RUNS: dict[str, dict[str, Any]] = {}


def _router():
    mode = os.getenv("SPECALIVE_PROVIDER", "auto")
    if mode == "none":
        return None
    from ..llm.router import Router

    try:
        return Router(mode=mode)
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    from ..verify.omc import describe_environment

    env = describe_environment()
    catalog = Path("out/catalog.jsonl")
    return {
        "omc": env.get("omc_version"),
        "omc_ok": env.get("omc_version") is not None,
        "catalog_classes": sum(1 for _ in catalog.open(encoding="utf-8")) if catalog.exists() else 0,
        "provider": os.getenv("SPECALIVE_PROVIDER", "auto"),
    }


@app.post("/api/runs")
async def create_run(
    files: list[UploadFile] = File(default=[]),
    packet_path: str = Form(default=""),
    reference_ir: str = Form(default=""),
    reference_trace: str = Form(default=""),
) -> dict[str, str]:
    """Stage an upload (or point at a directory already on disk) and return a run id."""
    run_id = uuid.uuid4().hex[:12]
    out_dir = RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if packet_path:
        packet = Path(packet_path)
        if not packet.exists():
            raise HTTPException(400, f"packet path does not exist: {packet}")
    else:
        packet = out_dir / "packet"
        packet.mkdir(exist_ok=True)
        if not files:
            raise HTTPException(400, "upload at least one file, or give a packet_path")
        for f in files:
            # Flatten any client-supplied path: never let an upload name escape the run dir.
            dest = packet / Path(f.filename or "unnamed").name
            with dest.open("wb") as fh:
                shutil.copyfileobj(f.file, fh)

    _RUNS[run_id] = {
        "packet": packet,
        "out": out_dir,
        "reference_ir": Path(reference_ir) if reference_ir else None,
        "reference_trace": Path(reference_trace) if reference_trace else None,
    }
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/events")
def stream_events(run_id: str) -> StreamingResponse:
    """Server-Sent Events, one per pipeline stage transition."""
    info = _RUNS.get(run_id)
    if info is None:
        raise HTTPException(404, "unknown run")

    def gen() -> Iterator[str]:
        cfg = PipelineConfig(
            packet=info["packet"],
            out_dir=info["out"],
            reference_ir=info["reference_ir"],
            reference_trace=info["reference_trace"],
        )
        pipeline = Pipeline(cfg, _router())
        try:
            for ev in pipeline.stream():
                yield "data: " + json.dumps(
                    {"stage": ev.stage, "status": ev.status, "message": ev.message, "data": ev.data},
                    default=str,
                ) + "\n\n"
        except Exception as exc:  # a crash must reach the browser, not vanish into the log
            yield "data: " + json.dumps(
                {"stage": "report", "status": "fail", "message": f"pipeline crashed: {exc!r}"}
            ) + "\n\n"
        result = pipeline.result
        yield "data: " + json.dumps(
            {
                "stage": "done",
                "status": "ok" if result.ok else "fail",
                "message": "complete",
                "data": {
                    "artifacts": result.artifacts,
                    "gate": result.gate,
                    "acceptance": (
                        {"passed": result.scorecard.passed, "total": result.scorecard.total}
                        if result.scorecard
                        else None
                    ),
                },
            },
            default=str,
        ) + "\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/artifact/{name}")
def artifact(run_id: str, name: str) -> FileResponse:
    info = _RUNS.get(run_id)
    if info is None:
        raise HTTPException(404, "unknown run")
    out: Path = info["out"]
    target = (out / name).resolve()
    if not str(target).startswith(str(out.resolve())) or not target.exists():
        raise HTTPException(404, f"no such artifact: {name}")
    media = {
        ".html": "text/html",
        ".json": "application/json",
        ".csv": "text/csv",
        ".mo": "text/plain",
        ".sysml": "text/plain",
    }.get(target.suffix, "application/octet-stream")
    return FileResponse(target, media_type=media)
