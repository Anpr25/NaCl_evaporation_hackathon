# SpecAlive — architecture and work split

Written for: the four of us building this. Read the whole thing once before you start; after
that, live in your own section.

---

## 1. What we are actually being asked for

At evaluation we are handed **an engineering packet in an unknown domain** — a brochure, a
datasheet, a mixed bag of PDFs, spreadsheets and drawings — and must produce:

1. a **SysML v2** system model,
2. an **executable Modelica** model that **compiles** (the one hard gate),
3. **simulation results**.

The NaCl evaporation packet is one fixture, not the product. Nothing NaCl-specific may be
load-bearing. Scoring: model correctness 30, AI architecture 30, product and design thinking
20, traceability and honesty 20.

Two jobs belong to the AI: **author the SysML**, and **author the Modelica and fix it until it
runs** — all on free or local models.

## 2. The thesis

> **Ground the small model; don't grow the model.**

A 3B local model cannot write a plant. A 3B model *can*:

- fill a JSON schema from a paragraph, with the quote it came from;
- pick the right entry from twelve retrieved candidates;
- apply a three-line patch given a precise compiler error.

So we build the scaffolding that reduces every task to one of those three, and we do
everything else with deterministic code. Deterministic code is free, exact, offline,
reproducible, and cannot hallucinate.

Consequence, and it is the headline number for the architecture score: on the NaCl packet,
**501 of the evidence claims are extracted with zero model calls**.

## 3. Pipeline

```
 packet (pdf docx xlsx png eml csv json puml mo md txt)
        │
 [1] INGEST      per-format adapters → Document(blocks, spans, locators)
        │        deterministic; vision only for images and scans
 [2] EXTRACT     schema-constrained → EvidenceClaim[] {source, locator, quote, confidence}
        │
 [3] RECONCILE   claims → SystemModel IR + DecisionRecord[] (winner, losers, rule, why)
        │
 [4] VALIDATE    port closure, domain match, FSM reachability, guard symbols, units,
        │        binding coverage, guard reachability ← finds defects in the *source data*
        ├──────────────────────────────┐
 [5a] SysML v2 emitter          [5b] Modelica emitter
      deterministic +                 catalog-grounded, L0→L1→L2 cascade
      round-trip check                      │
        │                          [6] omc compile ──errors──▶ REPAIR
        │                                   │    deterministic first, model second,
        │                                   │◀───  keep-best, bounded at 6
        │                          [7] simulate
        ▼                                   ▼
 [8] VERIFY   event-level acceptance first, signal RMSE only if the reference data
        │     passes a physical-consistency screen
 [9] REPORT   report.html + report.json: gates, traceability matrix, decision log, gaps
```

Every stage emits a `PipelineEvent`. The CLI, the web app and the bench all consume
`Pipeline.stream()`, so there is exactly one definition of what the pipeline does.

## 4. The three pillars

### 4.1 Catalog grounding

`omc` introspects every installed Modelica library: **6,368 classes** from MSL alone, each
with doc comment, restriction, typed parameters and connector list. Harvested once, offline,
free (`specalive harvest`).

The emitter only ever writes a class the catalog verified exists, with parameters the catalog
verified it has. Whole error families — wrong class path, invented parameter, mismatched
connector — become structurally impossible rather than merely unlikely.

### 4.2 Three-tier binding cascade

| Tier | Mechanism | When | Risk |
|:--|:--|:--|:--|
| **L0** | harvested catalog class, deterministic `connect()` | confident retrieval match | ~zero |
| **L1** | `SpecAlive.*` template filled from extracted parameters | domain known, no exact match | low |
| **L2** | model authors *equations only*, inside a skeleton with ports, units and connector balance pre-fixed | genuinely novel component | guarded by repair |

Lowest tier that works, always. The per-block tier table goes in the report: it is both an
architecture slide and an honesty artefact.

### 4.3 Deterministic-first repair

Most Modelica errors are mechanical. Those are fixed by code — discrete algebraic loops,
missing `inner`, single-edit typos, over-determined initialisation, unit clashes. Only
semantic failures reach a model, and then it gets the exact diagnostic, a ±15-line window, the
verified catalog signature, and an instruction to return a **minimal diff**.

Invariants: **keep-best-so-far** (a patch that increases the error count is discarded, never
applied) and **bounded** (stop and declare a gap rather than burn quota).

## 5. Model routing (free tier + 4 GB VRAM)

The Quadro T1000 fits a 3B fully in VRAM; a 7B needs CPU offload.

| Task | Tier |
|:--|:--|
| xlsx / csv / json / puml / mo parsing, PDF tables | **T0 deterministic** |
| span → typed claim, catalog pick, report prose | **T1** `qwen2.5:3b-instruct-q4_K_M` (local, GPU) |
| catalog retrieval | **T0 BM25**, + **T1** `nomic-embed-text` when available |
| dense prose extraction | **T2** `qwen2.5:7b` (local, offload) |
| conflict adjudication, equation synthesis, repair diffs | **T3 Groq** `llama-3.3-70b-versatile` |
| diagrams, scanned pages, long cross-doc context | **T4 Gemini** `2.5-flash` → local `qwen2-vl:2b` |

Router guarantees: schema-validated output **or escalate** — never silent acceptance ·
content-hash disk cache · quota-aware degradation · structured call log.

Modes: `auto` · `local` (offline) · `cloud` · `replay` (pre-warmed cache, demo-safe) ·
`none` (deterministic only). **Warm the cache the night before and commit it.**

## 6. Proving generality

`specalive bench` runs every packet in `benchmarks/` and prints a pass-rate matrix. Three
slots exist now: `nacl_evaporation` (green), `hvac_heat_exchanger`, `drivetrain`. Drop the
organisers' other three packets in with an `expectations.yaml` and nothing else changes.

The drivetrain fixture is the real test: rotational mechanics shares no vocabulary, no
connector type and no L1 template with the NaCl case, so every block must bind at **L0**
against the harvested catalog. If it passes, the system is not NaCl-shaped.

## 7. What already works

Verified on this machine, end to end:

```
$ specalive run nacl_evaporation_sysmlv2_full_dataset \
    --reference-ir benchmarks/nacl_evaporation/reference_ir.json --provider none

ok   ingest    15 sources, 121 blocks
ok   validate  0 error(s), 0 warning(s)
ok   sysml     NaClEvaporationPlant.sysml, round-trip clean
ok   modelica  GeneratedPlant.mo: L0=1, L1=15
ok   compile   repaired after 0 iteration(s)
ok   simulate  simulate: OK -> generatedplant_res.csv
warn verify    11/12 acceptance checks passed
ok   report    out/nacl/report.html
```

- `modelica/SpecAlive.mo` — domain-general L1 component library; every component balanced.
- The generated plant runs the full 3000 s BAT-09 cycle: charge → mix → buffer → evaporate →
  **parallel split** → cool both branches → return → **join** → restart after 2500 s.
- The one failing check is **OPEN-ISSUE-01** and *should* fail — see §9.

## 8. The traps in the NaCl packet

The packet's own README says it plants these. All are resolved deterministically, each with a
`DecisionRecord` naming the rule and the trap.

| Trap | Wrong answer | Effective truth | Authority |
|:--|:--|:--|:--|
| F1 recency bias | B7 cools to 20 °C | **25 °C** | CR-017 |
| F2 layout implies function | P1 is next to B1, so P1 → B1 | **P1 → B2**, headers cross-connected | CR-017 + datasheet §3 |
| F3 abstraction as architecture | K1 is merged into B5, so delete it | **K1 stays a part**; the merge is simulation-only | DR-07 #5 |
| F4 baseline as intent | StandardWater is the answer | baseline for debugging; **mixture** is intended | REQ-MOD-001/002 |
| F5 drawing completeness | 28 valves on the P&ID | **15 automated**, 13 manual | valve register + datasheet |
| F6 defect as requirement | WaterNaCl crashes at pump start, so delete the pumps | **keep them**, document the defect | REQ-MOD-003 |

Verified against the supplied trace: in `Step13` the commanded group is
`P2 + V20,V24,V25 + V1,V3` (B6 → B1) and in `Step10` it is `P1 + V18,V22,V23 + V5,V6`
(B7 → B2). The pump-side group follows its pump; the **destination-side group swaps**.

## 9. Two defects we found in the supplied data

Both are declared in the report, and both are worth points on their own.

**OPEN-ISSUE-01 — REQ-FUN-006's guard is unreachable.** B5 cannot reach 0.18 m from one B3
batch under a mass-consistent balance. B3 holds at most ~0.0091 m³ once it reaches the
0.080 kg/kg recipe target from a 0.13 m water prefill, which fills B5 to about 0.145 m against
a required 0.18 m. The two setpoints are mutually unsatisfiable as written. We add a declared
fallback exit on B4 exhaustion so the sequence cannot deadlock, and raise it as a source-data
defect. `ir/validate.py::check_guard_reachability` finds this class of defect automatically.

**OPEN-ISSUE-02 — the reference trace is not mass-consistent.** Across the B5 evaporation
phase the solute inventory rises 44% while concentration rises 0.080 → 0.180: NaCl is created.
So signal RMSE against that trace is not evidence of correctness. We score **events first**
(BAT-09 §3 is ten threshold/ordering criteria anyway) and only quote signal error after
`verify/acceptance.py::screen_reference` passes.

## 10. Work split

Contracts freeze in hour 1: `ir/system.py`, `ir/evidence.py`, and the artifact JSON shapes.
After that the only coupling is those files. Everyone works against
`benchmarks/nacl_evaporation/reference_ir.json`.

### A — Ingestion and evidence
**Owns** `ingest/`, `extract/`
**Gate** any file type → claims with accurate locators

- [ ] Model extraction path in `extract/claims.py` (the `TODO(A)` block). The validator
      matters more than the prompt: **reject any claim whose `quote` is not a literal substring
      of the chunk.** That one check removes almost all small-model fabrication and is free.
- [ ] Vision path for `doc.images()` — P&IDs, scanned pages. Tiling is already implemented.
- [ ] Claim de-duplication across sources (same fact, five documents → one group, five
      supports). Do not collapse *differing* values: those are the conflicts we need.
- [ ] Per-claim authority, not per-file. Today `classify_source` is a title-area heuristic and
      it still mislabels the lab notebook. An explicit `superseded_by` field must always win.
- [ ] Raise extraction recall against the reference IR; `specalive ir-diff` is the scoreboard.

### B — IR, reconciliation, SysML
**Owns** `ir/`, `reconcile/`, `emit/sysml.py`, `config/precedence.yaml`
**Gate** valid IR → valid `.sysml`, round-trip clean

- [ ] `reconcile/builder.py` TODOs B1–B5: assemble blocks, connections, signals, the FSM and
      the scenario. The precedence wiring is done; this is mechanical assembly.
- [ ] Series-group detection: walk from/to chains and populate `Connection.series_elements`.
      Test: `RET_A` must carry `{P2,V20,V24,V25,V1,V3}`.
- [ ] Generalise `_supply_ceiling` in `validate.py` beyond geometric vessels (charge, energy).
- [ ] Richer SysML: `satisfy`/`verify` as first-class relationships rather than comments.
- [ ] Keep `parse_back()` in step with the emitter — it is our only structural check.

### C — Modelica, catalog, repair
**Owns** `catalog/`, `emit/modelica.py`, `repair/`, `modelica/SpecAlive.mo`, `verify/omc.py`
**Gate — the hard one — it compiles and it runs**

- [ ] Run `specalive harvest` (several minutes for full MSL) and commit `out/catalog.jsonl`.
      Verified working on a 239-class subset: params carry units, ports carry connector types,
      inheritance resolved. Sanity-check a few classes per domain after the full run.
- [ ] **Add embeddings to retrieval.** BM25 alone already gets top-1 right for clear queries
      (`"torsional spring and damper coupling"` → `Rotational.Components.SpringDamper`), but it
      picks `VariableResistor` over `Resistor` for `"electrical resistance element"` and a
      sensor for `"heat conduction through a wall"`. Those are precisely the ambiguous cases
      the LLM picker exists for — wire `nomic-embed-text` and confirm the picker resolves them.
- [ ] L1 templates for the bench domains: rotational inertia/spring/damper, thermal
      capacitor/conductor, 1-port electrical. Keyword lists are the cheap part.
- [ ] L2 synthesis (`_try_l2`): skeleton is designed, prompt and balance check are not written.
- [ ] More deterministic fixers. Every one you add is an LLM call we never make. Mine real
      omc output for patterns — `fix_discrete_loop` came from a bug this scaffold actually hit.
- [ ] **Tier 2 stretch**: acausal `Modelica.Fluid` variant + `WaterNaCl` medium, shipped with
      the pump-start convergence issue documented (REQ-MOD-003 literally asks for this).

### D — Platform, verification, proof
**Owns** `llm/`, `verify/acceptance.py`, `verify/report.py`, `web/`, `cli.py`, `benchmarks/`
**Gate** the demo does not break

- [ ] `ollama pull qwen2.5:3b-instruct-q4_K_M nomic-embed-text`; get Groq and Gemini keys;
      make `specalive doctor` all green.
- [ ] Exercise every router path: quota exhaustion, offline, replay. Force each failure
      deliberately — an untested fallback is not a fallback.
- [ ] Warm the cache and commit it, so `--provider replay` reproduces a known-good run.
- [ ] Charge and energy conservation screens in `screen_reference`.
- [ ] Plots in the report (matplotlib → inline SVG; overlay reference where it is trustworthy).
- [ ] Build the two extra bench packets; wire `specalive bench` into CI.

## 11. Milestones

| When | Everyone must be able to say |
|:--|:--|
| **Hour 1** | contracts frozen; `specalive doctor` green; everyone has run the NaCl pipeline |
| **Day 1** | catalog harvested; A's model extraction produces claims; B assembles blocks + connections; C has one non-NaCl domain compiling; D has the router live on local + Groq |
| **Day 2** | full pipeline with no `--reference-ir` on NaCl; two bench domains green; report complete; web app demoable |
| **Day 3 am** | all four organiser packets in `benchmarks/`; `specalive bench` run and its matrix in the deck |
| **Day 3 pm** | freeze. Cache warmed, `--provider replay` rehearsed, submission packet assembled |

**Freeze rule:** after the Day-3 freeze, the only permitted changes are ones that turn a red
bench cell green. Nothing else. Demos die from last-minute refactors.

## 12. How we are judged, and where the points are

| Criterion | Pts | Where we earn it |
|:--|--:|:--|
| Model correctness | 30 | it runs the full cycle incl. parallel split/join and restart; 11/12 acceptance; physics is coherent, not curve-fitted to a trace we proved is wrong |
| AI architecture | 30 | catalog grounding; tier cascade; deterministic-first repair; validator-driven escalation; runs on a 3B + free tiers; the call log proves it |
| Product & design | 20 | one command; one self-contained report; web app; `doctor`; `bench`; degrades instead of failing |
| Traceability & honesty | 20 | decision log with rule + rationale + trap; traceability matrix; gaps declared **above** the pretty parts; two defects found in the organisers' own data |

**Hard gate:** the Modelica compiles. It does today. Keep it that way — run
`specalive gate` before every push.

## 13. Standing rules

1. **If a parser can do it, a model must not.** Every model call needs a reason.
2. **No unvalidated model output reaches the IR.** Schema, then domain validator, then escalate.
3. **Never resolve a conflict by recency or polish.** Authority, status, explicit supersession.
4. **A declared gap beats a silent guess**, every time, including under demo pressure.
5. **Don't chase the reference trace.** We proved it is not mass-consistent. Score events.
6. **The gate is sacred.** A beautiful IR that does not compile scores zero on the gate.
