# SpecAlive

**From specs to live engineering models.**

Give it an engineering packet in whatever formats it happens to exist in — PDFs, spreadsheets,
a P&ID, an email thread, a legacy model, loose notes. Get back a SysML v2 system model, an
executable Modelica model that compiles and runs, simulation results, and a report that shows
where every number came from and which conflicts were resolved how.

Built for the SpecAlive internal hackathon.
Architecture and work split: **[PLAN.md](PLAN.md)**. Progress, decisions and backlog: **[STATUS.md](STATUS.md)**.

---

## Quick start

```bash
pip install -e .
specalive doctor                      # is the toolchain here?
specalive harvest                     # index the installed Modelica libraries (~200 s, once)

specalive run nacl_evaporation_sysmlv2_full_dataset \
  --reference-ir benchmarks/nacl_evaporation/reference_ir.json \
  --reference-trace nacl_evaporation_sysmlv2_full_dataset/09_datasets/10_batch_run_3000s.csv \
  --out out/nacl
```

```
ok   ingest    15 sources, 121 blocks
ok   validate  0 error(s), 0 warning(s)
ok   sysml     NaClEvaporationPlant.sysml, round-trip clean
ok   modelica  GeneratedPlant.mo: L0=1, L1=15
ok   compile   repaired after 0 iteration(s)
ok   simulate  simulate: OK -> generatedplant_res.csv
warn verify    11/12 acceptance checks passed
ok   report    out/nacl/report.html
```

Open `out/nacl/report.html`. The one failing check is expected — see *Two defects we found*.

## What it needs

| | |
|:--|:--|
| **Required** | Python 3.10+, [OpenModelica](https://openmodelica.org) (found automatically, or set `SPECALIVE_OMC`) |
| **Optional** | [Ollama](https://ollama.com) for local models, a free [Groq](https://console.groq.com/keys) key, a free [Gemini](https://aistudio.google.com/apikey) key |

Nothing beyond OpenModelica is required to run the pipeline: `--provider none` is fully
deterministic. Copy `.env.example` to `.env` to add keys.

```bash
ollama pull qwen2.5:3b-instruct-q4_K_M     # ~2.0 GB, fits a 4 GB card
ollama pull nomic-embed-text               # ~274 MB
```

## Commands

```bash
specalive doctor                             # what is installed, what is missing
specalive harvest                            # Modelica libraries -> out/catalog.jsonl
specalive run <packet> [--provider auto|local|cloud|replay|none]
specalive gate <Model> <files...>            # just the hard gate, fast
specalive bench                              # every benchmark packet, pass-rate matrix
specalive ir-diff <extracted.json> <reference.json>
specalive serve                              # web app on :8000
```

## How it works

The short version: **ground the small model, don't grow the model.**

`omc` can introspect every installed Modelica library. Harvesting full MSL yields **1,529
instantiable classes** in about 200 s, each with its doc comment, typed parameters and
connector signature (inherited ones resolved), offline and free. That turns *"write
correct Modelica for an unknown domain"*, which a 3B local model cannot do, into *"pick the
right entry from twelve retrieved candidates and fill its declared parameters"*, which it can.

Everything downstream of the validated IR is deterministic codegen, so the emitter cannot
invent a class or a parameter that does not exist. On the NaCl packet, 501 evidence claims are
extracted with **zero model calls**, and retrieval alone gets 7 of 8 probe queries right at
rank 1 across five physical domains.

```
ingest → extract → reconcile → validate → SysML v2
                                        → Modelica → compile ⇄ repair → simulate → verify → report
```

Components bind through a three-tier cascade — **L0** a harvested catalog class, **L1** a
`SpecAlive.*` template, **L2** model-authored equations inside a fixed port skeleton — always
the cheapest tier that works, with the per-block tier table printed in the report.

Compile failures go to deterministic fixers first (discrete algebraic loops, missing `inner`,
typos, over-determined initialisation); only semantic failures reach a model, and then only
with a precise diagnostic and an instruction to return a minimal diff. The loop keeps the best
version seen and never applies a patch that increases the error count.

Full detail in [PLAN.md](PLAN.md).

## Layout

```
src/specalive/
  ingest/      format adapters -> Document(blocks, locators)      [A]
  extract/     Document -> typed EvidenceClaim                    [A]
  reconcile/   claims -> SystemModel, with DecisionRecords        [B]
  ir/          the domain-agnostic IR and its static checks       [B]
  emit/        IR -> .sysml and IR -> .mo                         [B,C]
  catalog/     omc library harvest + hybrid retrieval             [C]
  repair/      omc diagnostics -> fixes, deterministic first      [C]
  verify/      omc driver, acceptance scoring, the report         [C,D]
  llm/         provider-neutral tiered router, cache, quotas      [D]
  web/         FastAPI + SSE front end                            [D]
modelica/SpecAlive.mo    L1 component library
benchmarks/              one directory per packet + expectations.yaml
```

## Two defects we found in the supplied data

Both are declared in the generated report rather than papered over.

**The B5 charge setpoint is unreachable.** `REQ-FUN-006` requires B5 to reach 0.18 m, but a
single B3 batch that satisfies the 0.080 kg/kg recipe from a 0.13 m water prefill can only
fill it to about 0.145 m. The two setpoints are mutually unsatisfiable under a mass-consistent
balance. We add a declared fallback exit so the sequence cannot deadlock, and flag it.
`ir/validate.py::check_guard_reachability` finds this class of defect automatically.

**The reference trace is not mass-consistent.** Across the B5 evaporation phase the solute
inventory rises 44% while concentration rises 0.080 → 0.180, so NaCl appears from nowhere.
Signal RMSE against that trace would not be evidence of correctness, so we score BAT-09's
event criteria first and only quote signal error once
`verify/acceptance.py::screen_reference` passes.

## Development

```bash
pip install -e ".[dev]"
pytest
specalive gate GeneratedPlant.BAT09 \
  benchmarks/nacl_evaporation/reference/GeneratedPlant.mo modelica/SpecAlive.mo
```

Run `specalive gate` before every push. The hard gate is the one thing that must never break.
