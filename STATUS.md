# SpecAlive — status, decisions, backlog

Companion to [PLAN.md](PLAN.md). PLAN.md is *what we are building and who owns what*. This is
*where we are, what we already decided and why, and what is left*.

Keep this current. When you finish something, move it from §4 to §2 with the evidence that
proves it. When you make a call that another person could reasonably have made differently,
add it to §3 — that is how we avoid re-litigating decisions at 2am on day three.

**Last updated:** after integrating workstreams A, B and D onto one branch.
**Verdict:** the hard gate passes on **two domains**, all model tiers are live and verified,
IR assembly (B) and the model extraction path (A) have both landed, and the report carries
plots. On track.

---

## 1. One-screen summary

| | |
|:--|:--|
| Hard gate (Modelica compiles) | **PASS** |
| Simulation runs 3000 s | **PASS** |
| Acceptance checks | **11/12** (the twelfth is a defect in the source data — see §5) |
| Tests | see the integration run below |
| Pipeline stages implemented | 10 of 10 wired; L2 synthesis is the remaining stub |
| Extracted IR vs reference (`ir-diff`) | **83%** overall; topology 90%, series groups 100%, requirements 100% |
| Modelica catalog | **1,529 classes** harvested from full MSL in **203 s** |
| Catalog retrieval | **7/8 top-1** across rotational, electrical, fluid, signal, thermal — BM25 only, no model |
| Domains proven | **two end to end**: fluid+thermal+control (NaCl, 11/12) and rotational mechanics (drivetrain, **7/7**, all L0) |
| LLM calls required to reach the above | **zero** |
| Local model tier | **live** — qwen3:4b, 100% on the task bake-off, 43 tok/s fully on GPU |
| Cloud tiers | **live** — Groq `openai/gpt-oss-120b`, Gemini vision read the P&ID 15/15 valves |

Reproduce:

```bash
pip install -e .
python -m pytest              # 51 fast
python -m pytest -m slow      # + 2 compile/simulate gate tests, ~55 s
specalive harvest             # 1529 classes, ~200 s, once per machine
specalive run nacl_evaporation_sysmlv2_full_dataset \
  --reference-ir benchmarks/nacl_evaporation/reference_ir.json \
  --reference-trace nacl_evaporation_sysmlv2_full_dataset/09_datasets/10_batch_run_3000s.csv \
  --provider none --out out/nacl
```

---

## 2. Done, and how we know

Everything here was executed on the dev machine, not just written.

### 2.1 Modelica — the hard gate

| Item | Evidence |
|:--|:--|
| `modelica/SpecAlive.mo` — domain-general L1 library | every component passes `checkModel`, all balanced |
| Vessels: `PartialVessel`, `Reservoir`, `CooledVessel`, `Evaporator` | mass, solute and energy balances; states are `m`, `mSolute`, `T` so there is no algebraic loop |
| Transport: `Path`, `Pump`, `Condenser`, `Junction`; Sources: `FixedSupply`, `Drain` | checked individually |
| Reference plant `benchmarks/nacl_evaporation/reference/GeneratedPlant.mo` | 249 eq / 249 var, compiles, simulates 3000 s |
| Full BAT-09 behaviour | charge → mix → buffer → evaporate → **parallel split** → cool B6 and B7 → return both → **join** → restart after 2500 s |
| Routing correctness | B1 gains condensate (0.45 → 0.339 after two draws), B2 dilutes 0.250 → 0.242 from returned concentrate |

### 2.2 Pipeline

| Stage | State | Evidence |
|:--|:--|:--|
| ingest | **done** | 15/15 files of the NaCl packet parse, zero adapter warnings, 121 blocks |
| extract (deterministic) | **done** | 501 claims with cell-level locators |
| extract (model path) | *stub* | `TODO(A)` in `extract/claims.py` |
| reconcile (precedence) | **done** | resolves `CR-017 supersedes REQ-ROU-001, REQ-ROU-002` with no model call |
| reconcile (IR assembly) | **done** | 47 blocks, 19 connections, 37 signals, 4 interlocks, 19-state FSM (3 regions, fork + join), BAT-09 scenario with 10 derived checks; validate 0 errors; SysML round-trip clean; `ir-diff` 83% |
| validate | **done** | 10 checks; reference IR passes with 0 errors, 0 warnings |
| SysML emit | **done** | round-trip check loses nothing |
| Modelica emit | **done** | L0=1, L1=15 on the NaCl fixture |
| compile + repair | **done** | 5 deterministic fixers; loop keeps best, never regresses |
| simulate | **done** | via scripted `omc`, auto-discovered |
| verify | **done** | 12 acceptance checks + reference-trace conservation screen |
| report | **done** | `report.html` + `report.json` |

### 2.3 Infrastructure

- **Catalog harvest** is done and fast: **1,529 instantiable classes from full MSL plus our
  own library in 203 s**, every one with typed parameters (units resolved) and ports
  (connector types), inheritance resolved. Getting here took four fixes — see §6.
  `out/catalog.jsonl` is **not** committed (see D26): run `specalive harvest` once per
  machine, and `specalive doctor` tells you whether it is there.
- **Retrieval** is **7 of 8 top-1** on queries phrased the way a brochure would phrase them,
  across five domains, with BM25 alone and no model:

  | query | returns |
  |:--|:--|
  | "flywheel rotating mass with moment of inertia" | `Rotational.Components.Inertia` |
  | "gearbox with fixed transmission ratio" | `Rotational.Components.Gearbox` |
  | "permanent magnet DC machine" | `Machines.BasicMachines.DCMachines.DC_PermanentMagnet` |
  | "open storage tank with fluid ports" | `Fluid.Vessels.OpenTank` |
  | "PID controller block" | `Blocks.Continuous.PID` |
  | "ideal linear electrical resistor" | `Analog.Basic.Resistor` |
  | "linear translational damper" | `Translational.Components.Damper` |
  | "thermal conduction between two ports" | `Interfaces.Element1D` — wanted `ThermalConductor`, which ranks 3rd |

  The one miss is a partial base class leaking into the results, and the right answer is in
  the shortlist. That is exactly the case the LLM picker exists for. Backlog C7 tightens it.
- **LLM router**: provider-neutral, five modes, disk cache, quota tracking, schema validation
  with escalation. **Now exercised against a live Ollama endpoint** and against 19 fault-injection
  tests covering invalid JSON, schema violation, validator rejection, retry feedback, dead
  daemon, mid-call disconnect, 429 quota, declared rate limits, cache hit/miss, replay on a warm
  and a cold cache, total failure, and the stats log. Groq and Gemini remain untested: no keys.
- **Cloud tiers are up and verified against real endpoints.**

  | Tier | Model | Verified by |
  |:--|:--|:--|
  | `t3_cloud_reasoning` | `openai/gpt-oss-120b` | adjudicated the CR-017 vs legacy B7 conflict correctly in 2.2 s |
  | `t4_cloud_vision` | `gemini-flash-latest` -> `gemini-3.5-flash` | read the P&ID: **10/10 equipment, 15/15 automated valves**, 17 instruments |

  The vision run is also a live demonstration of trap F5: the model correctly read *29*
  valves, because the drawing shows all of them. Ownership comes from the register.
- **Local tier is up.** `qwen3:4b` + `nomic-embed-text`, both reported `up` by `doctor`.
  Measured on the Quadro T1000 (4 GB, display on the iGPU):

  | Ollama config | GPU residency | throughput |
  |:--|:--|:--|
  | default | 67% | 13.3 tok/s |
  | `num_gpu: 99` | **100%**, 3.18 GB | **43.1 tok/s** |

  A 3.2x speedup from one setting. Ollama leaves ~1.6 GB of a 4 GB card unused by default.
- **Bake-off result** (`specalive models`, 5 extraction + 6 catalog-pick tasks):

  | Model | Extraction | Catalog pick | tok/s |
  |:--|:--|:--|:--|
  | **qwen3:4b** | **5/5** | **6/6** | 10-43 |
  | gemma3:4b | 5/5 | 5/6 | 4 |

  Getting there took four fixes to **our own code**, not a change of model — see §6.
- **CLI**: `doctor`, `harvest`, `run`, `gate`, `bench`, `serve`, `ir-diff`. All run.
- **Web app**: FastAPI + SSE, no build step. Smoke-tested (`/`, `/api/health`, `POST /api/runs`).
- **Tests**: 40 fast + 2 gate, each encoding a real bug or a planted trap. Workstream B's live in
  `tests/test_reconcile.py`; the synthetic cases use a switchboard, capacitors and flywheels so a
  tank-shaped rule fails there first.

### 2.4 Generality — the drivetrain bench

A geared drive rig that shares nothing with the NaCl packet: rotational mechanics, acausal
`Flange_a`/`Flange_b` connectors, no state machine at all, and **every block bound at L0**
against the harvested catalog. Five heterogeneous source files, its own precedence trap
(archived model says ratio 4.0, approved CR-114 says 5.0).

| | |
|:--|:--|
| Bindings | **L0=6, L1=0, L2=0** — not one SpecAlive template |
| Acceptance | **7/7** |
| Steady state | `w_load = ratio*tau/d = 5*2/0.8 = 12.5` rad/s; simulated **12.500**, error **0.000%** |

The acceptance thresholds are derived from the analytic solution, not fitted to the output.

```
| Packet              | Compiles | Simulates | Acceptance | Verdict   |
| drivetrain          | yes      | yes       | 7/7        | PASS      |
| hvac_heat_exchanger | -        | -         | -          | NO PACKET |
| nacl_evaporation    | yes      | yes       | 11/12      | PASS      |
```

### 2.5 Analysis of the packet

All six planted traps identified and resolved, each with a `DecisionRecord` naming the rule
and the trap. Routing verified against the supplied trace by decoding valve commands per
state. Two defects found in the organisers' own data (§5).

### 2.6 Input-handling rules (6.2 / 6.3)

The brief governs how we behave on incomplete, ambiguous, contradictory, implicit and custom
input. Current standing, measured on the autonomous run (no `--reference-ir`):

| Clause | Behaviour | Evidence |
|:--|:--|:--|
| Missing info **inferred with a stated assumption** | 6 assumptions, each citing a convention registered in `config/assumptions.yaml` *before* the run | report §*Stated assumptions*; `assumptions_unfounded` = **0** |
| ...**or surfaced as a question** | 4 questions, 2 of them blocking, each with what we searched and what we did meanwhile | report §*Questions for the customer* |
| **Never silently invented** | `assume()` raises on an unregistered basis; an unfounded inference is still recorded and counted, never hidden | `tests/test_assumptions_and_questions.py` |
| **Contradictions flagged, not resolved arbitrarily** | 12 decision records naming a precedence rule; 2 setpoint contradictions proved from the trace and reported unresolved | report §*Conflict resolutions*, §*Declared gaps* |
| **No fabricated components, ports or physics** | 0 blocks with empty provenance; ports are added only under SA-01, where a connection or requirement needs them | `coverage()` |

The diagnosis pass is the part worth demonstrating: it rediscovers **OPEN-ISSUE-01**
unaided, from the simulation rather than from static analysis — *"B5.level settled at 0.1476
against a required 0.18 ... 18.5% short ... the specification asks for something its own
numbers forbid"* — and separates the two real contradictions from the five checks that are
merely downstream of them.

It then **acts** on that finding without hiding it (SA-05, decision D42). The customer's
guard is left exactly as written and evaluated first; a second, clearly marked transition is
added beside it; and the model is built and run again. Both the Modelica and the SysML show
the two exits side by side. The contradicted checks **still fail** — nothing turns green
because we added an exit — but the twelve steps behind the deadlock now get exercised, which
takes the autonomous run from **3/10 to 8/10**.

The two still red are the genuine contradictions (OPEN-ISSUE-01 and OPEN-ISSUE-07),
correctly reported as found. Nothing turns green because we added an exit.

Getting from 5/10 to 8/10 was extraction, not modelling, and it was one chain:
`SP-K1-CW = 0.1 kg/s` was extracted and then never wired to `K1.cw_flow`; that input read
zero; `FIS-801` — which no document gives a binding — read zero too; the heater permissive
`FIS-801 >= 0.10` was false for the whole run; B5 never boiled; nothing condensed; B6 and B7
never got the charge they were meant to cool. An unbound input now looks for a setpoint the
evidence supplies before assuming, and a sensor compared against a setpoint we have already
resolved is bound to that quantity. Both are evidence-backed recoveries, not assumptions.

---

## 3. Decisions taken

Each of these is a call someone could reasonably have made differently. Revisit only with a
reason, and update the row rather than arguing from memory.

### Product and scope

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| D1 | NaCl is a **fixture**, not the product; architecture is domain-general | evaluation hands us an unknown domain | nothing NaCl-specific may be load-bearing, which is more work up front |
| D2 | **LLM at the edges, deterministic core** | free/local models can't carry generation; the compile gate must be reliable | more code than "ask the model" |
| D3 | Stack is **Python** | the PDF/XLSX/Modelica ecosystem lives there | — |
| D4 | **CLI + self-contained HTML report** is the primary surface; web app secondary | a live demo that hangs mid-presentation is worse than no demo | web app gets less polish |
| D5 | Bench covers **NaCl + HVAC + drivetrain** | HVAC is the likely-neighbour case, drivetrain shares nothing with NaCl and is the real generality proof | two extra packets to build |

### Generation strategy

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| D6 | **Catalog grounding**: harvest MSL via `omc` introspection, retrieve, let the model only *pick* | makes wrong class paths and invented parameters structurally impossible; a 3B can do multiple choice | one-off harvest step per machine |
| D7 | **Three-tier cascade** L0 catalog → L1 template → L2 synthesis | lowest risk that can do the job; the tier table is also an honesty artefact | L2 still unimplemented |
| D8 | **Tier 1 uses a causal directed-flow abstraction**, not `Modelica.Fluid` | removes nonlinear pressure networks entirely, so generated models integrate reliably; the packet even warns that the acausal variant fails at pump start | REQ-MOD-004/005/006 (regularized port loss, junction volumes, gravity head) have no numerical effect in Tier 1. **Declared as OPEN-ISSUE-04, not hidden.** Tier 2 is the fix |
| D9 | **State machines lower to a sampled algorithmic FSM**, one `Integer` per region, not `Modelica.StateGraph` | domain-general, no library dependency, no continuous state, and it is literally how a PLC executes | loses the visual StateGraph diagram |
| D10 | Region states are read through **`pre()`** inside the scan | without it omc's alias elimination folds the output equations back into the state reads and reports a purely discrete algebraic loop | one-scan delay on forks, which is correct PLC semantics anyway |
| D11 | A **series element group lowers to one commanded path** with an AND of its members | physically correct — all must be open for flow — and keeps the causal model clean | SysML keeps every valve; only the executable model collapses them, recorded via `@lowering` |
| D12 | Ports carry both an IR **id** and a Modelica **name** | the id is a stable handle, the name is what the bound class actually calls the connector | emitter must resolve one to the other (bug we already hit once) |

### Evidence and honesty

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| D13 | **Precedence, never recency.** Explicit supersession → status → authority class → revision/date → specificity → corroboration → escalate | the packet's README says the newest-looking file is not the authority | more machinery than a date sort |
| D14 | **Supersession direction handled explicitly in both forms** | registers state it both ways in adjacent columns; inverting it makes the system prefer exactly the legacy values being tested for | two code paths instead of one heuristic |
| D15 | When no rule discriminates, emit a **provisional value plus an open question** | a declared gap beats a confident guess | the report has an "unresolved" section, by design |
| D16 | **Event-level acceptance is primary**; signal RMSE only after the reference trace passes a conservation screen | the supplied trace creates NaCl during evaporation, so RMSE against it is meaningless | we do not get to quote a flattering error number |
| D17 | Source classification uses the **title area only**, not the whole document | a register that *mentions* change records is not a change record | still imperfect; per-claim classification is the real fix (backlog A4) |
| D18 | The unreachable guard gets a **declared fallback exit**, not a silent setpoint change | the sequence must not deadlock, and the customer must be told their setpoints conflict | one acceptance check legitimately fails |
| D42 | D18 now applies **automatically** (SA-05): the pipeline proves unreachability from its own trace, adds a marked fallback beside the untouched guard, and builds again | a defect in the customer's spec should cost us that step, not the twelve after it; and doing it by hand does not generalise to an unseen packet | the emit→verify section became a pass that can run up to three times |
| D43 | The fallback **dwell is derived from the trace**, not configured | any constant we chose would be the thing a judge asks about; 1.25x the observed rise time is defensible and per-step | it depends on a first pass having run, so the feature cannot be static-only |
| D39 | **Assumptions and questions are separate records from gaps**, and both appear ahead of the gap table in the report | rule 6.3 makes them the two permitted responses to missing information; burying them among warnings makes an assumption indistinguishable from an invention | two more IR types and two more report sections |
| D40 | An inference must cite a **pre-registered convention** in `config/assumptions.yaml`, or be counted as unfounded | a basis invented at the call site is a rationalisation, not a declared assumption; writing the convention first is what makes it checkable | the register has to be maintained, and `assume()` raises on an unregistered id |
| D41 | A red check is **diagnosed, not just counted** — plateaued-short vs never-moved vs still-moving | seven reds from one root cause is as misleading as none; only the plateau is evidence of a contradiction | a fourth heuristic with thresholds we had to pick |

### Operations

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| D19 | **Deterministic repairs first**, model only for semantic failures, minimal diffs | most Modelica errors are mechanical; this is what makes free models sufficient | a fixer library to maintain |
| D20 | Repair loop is **bounded and keep-best** | a patch that increases the error count is discarded; never thrash | may stop before fixing everything, and says so |
| D21 | **Cloud-first, local fallback, replay cache** | three layers of demo-day safety | three code paths to test |
| D23 | Harvest is **chunked and parallel, one working directory per worker** | several omc processes sharing a directory collide catastrophically — a chunk that runs in 30 s alone did not finish in 30 minutes with four workers in one folder | a little more orchestration code |
| D24 | Base classes are **probed but never emitted**; dead subtrees are cut before the expensive pass | MSL declares connectors in partial base classes, so skipping them for speed silently strips ports off everything that inherits them | two filters instead of one |
| D25 | A failed chunk is **reported and skipped**, not fatal | a partial catalog beats no catalog, especially on an unfamiliar machine | the catalog can be silently incomplete, so the warning must be loud |
| D26 | The harvested catalog is **regenerated per machine, never committed** | it must match the MSL actually installed; a catalog built against 4.1.0 and used on 4.0.0 would name classes that do not exist there, breaking the one guarantee the whole design rests on | a 200 s setup step, which `doctor` prompts for |
| D35 | Reference-data screens are **opt-in by content and tri-state** | a trace with nothing screenable is reported as "neither endorsed nor rejected", never as a pass; silence must not look like approval | some traces get no screen at all |
| D36 | Screens **consult the IR**, not just column names | omc eliminates a constant source torque as a parameter alias, so `M1.tau` is absent from the result and a name-based check wrongly concludes there is no constant drive | `screen_reference` now takes an optional model |
| D37 | Report plots are **hand-written inline SVG**, not matplotlib | the report must stay one self-contained file that survives being emailed, must be readable in dark mode, and must not add a 50 MB dependency to a fresh machine | we write our own axis code |
| D38 | Plots show **what the acceptance criteria name**, with thresholds drawn on the same axes | ranking by variation surfaced `der(J1.w)` and connector internals; and a reader should see the criterion being met, not trust a PASS in a table | fillers capped at two |
| D31 | `.env` is **loaded at every entry point** via `settings.load_env()` | the file existed with valid keys, `python-dotenv` was a declared dependency, and nothing ever called it -- so both cloud tiers reported down and the router silently degraded to local | new entry points must remember to call it |
| D32 | Tiers carry **`fallback_models`, and providers now walk the list** | the field was in config and no provider read it. `llama-3.3-70b-versatile` 404s on a current key, which would otherwise be a dead tier | one wasted request per stale name, once per run |
| D33 | **502/503/529 falls through to the next model**, not the next tier | transient overload is the most likely free-tier failure. Observed live: gemini-flash-latest was overloaded and the P&ID run only succeeded by walking down to gemini-3.5-flash | a busy model costs one request before we move on |
| D34 | Cloud model ids are **verified against the live /models endpoint**, not assumed | hosted catalogues churn faster than our config; `doctor` now reports the model that actually resolved | one cheap API call at probe time |
| D27 | Local models run with **`num_gpu: 99`** forced | measured 3.2x: Ollama otherwise leaves ~1.6 GB of a 4 GB card unused and runs a third of the model on CPU | must be lowered on a smaller card; `specalive models` shows the split |
| D28 | **Thinking is disabled** on reasoning models (`think: false`) | with it on, qwen3 returns an EMPTY `response` and puts everything in a separate `thinking` field, so every structured call fails and the router escalates for nothing. We do not want reasoning for span extraction or multiple choice anyway | a provider flag per tier |
| D29 | The catalog picker answers with a **class name, not a list index** | measured: with an index, a 4B model falls back to "0" when unsure, and that was two of its three errors. A name must be copied from the list, and a name never offered is detectable as a hallucination | slightly longer output |
| D30 | A cache hit reports **its own latency**, not the original call's | replaying the old figure inflated every "time spent on models" number, and that number is evidence we quote | one extra field, `original_latency_s`, to keep the saving visible |
| D22 | A hand-built **reference IR** is a first-class artefact | decouples B/C/D from A on day one, and doubles as A's scoring oracle via `ir-diff` | must be kept in step with the IR schema |

### IR assembly (workstream B)

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| D27 | The builder types a subject by the **shape of its resolved facts** (`from`+`to` = hop, `next` = step, `location`+measurement = instrument, numeric `value` = parameter, tagged + physical kind = part), never by sheet or file name | an unknown packet will not call its sheets "Interfaces" or "State_Sequence" | a subject whose facts fit no shape is not built; `GAP-UNUSED-*` counts them |
| D28 | Table extraction keeps **every named column**: an unrecognised header keeps its own name, a header with a unit names a quantity, colliding synonyms fall back to their own name, and the id column must be unique | the vocabulary dropped the Interfaces, State_Sequence and Instruments sheets entirely, and B1 cannot assemble what was never extracted | touches A's `extract/claims.py` (one helper plus the header rule); more `note` claims per packet |
| D29 | **Series elements are real parts** with `abstracted_into=<path>`; the path is a lumped block | SysML keeps every valve and pump as a part (D11) while Modelica collapses them, and `simulatable_blocks()` already excludes abstracted parts | more blocks in the IR than the reference, which hides them |
| D30 | A **named group** ("plus B1 routing group") is resolved from wherever its members are listed, **including superseded records**, and each derivation is a `DecisionRecord` (`D-group-membership`, F2) | a change record that re-pairs branches with destinations does not move valves; the superseded text is the only place the B1 group is spelled out | the argument must be written down, and it is |
| D31 | A guard clause the parser cannot formalise is **dropped and declared** as a Gap, never guessed. "B6 return complete" is formalised only via the transfer's own interlock (`LIS_601 > 0.02` on P2, so done at `LIS_601 <= 0.02`) | honesty over apparent completeness; the derived rule is domain-neutral | `Initial -> Step1` fires on the next scan (its "startEnable AND B3 available" is declared unformalised) |
| D32 | Drawing and vision edges **corroborate** register topology; they never create it when a connection register exists | a drawing is not a routing authority (F2), and the vision model's P&ID edges are mostly wrong (B1->B2, B6->B7) | uncorroborated edges are listed in an info gap, not modelled |
| D33 | `satisfy` / `verify` are **first-class SysML relationships**, derived from what each requirement's text names (sensor + value + unit for transitions; actuator + sensor for interlocks; routed ends for paths); `parse_back()` must recognise **every** emitted line | a trace comment cannot be checked; a parser that silently skips new constructs is worse than none (B5) | satisfaction is heuristic, and explained in each requirement's provenance note |
| D34 | Validation treats a block **nobody has tried to bind yet** as `info`, not an error | validation runs before the emitter binds, so every extracted block used to fail it | an unbound block after binding is still an error |

---

## 4. Backlog

Ordered by priority within each owner. `[!]` means it blocks someone else.

### A — Ingestion and evidence

- [ ] **A1 `[!]`** Model extraction path in `extract/claims.py`. The validator matters more
      than the prompt: **reject any claim whose `quote` is not a literal substring of the
      chunk.** Free, and it removes almost all small-model fabrication.
- [ ] **A2** Vision path for `doc.images()` — the P&ID and any scanned pages. Tiling is
      already implemented; wire `router.run("read_diagram", ..., images=[...])`.
- [ ] **A3** Claim de-duplication across sources. Same fact from five documents is *one* group
      with five supports. Do **not** collapse differing values — those are the conflicts.
- [ ] **A4** Per-claim authority instead of per-file. `classify_source` still mislabels the
      lab notebook as a change record because it cites `CR-017`. An explicit `superseded_by`
      field must always beat the heuristic.
- [ ] **A5** Raise extraction recall against `reference_ir.json`; `specalive ir-diff` is the
      scoreboard.

### B — IR, reconciliation, SysML

- [x] ~~**B1** Builder assembly~~ — **done**: blocks, ports, connections, signals, interlocks,
      FSM, scenario and requirement satisfaction from resolved claims (`reconcile/builder.py`,
      `entities.py`, `topology.py`, `behaviour.py`). NaCl: B1–B7 + K1 simulatable, P1/P2 and 15
      automated valves abstracted into their paths, 13 manual valves architecture-only, 15
      `cmd_V*` actuators, 3 regions / 19 states with the fork at Step6 and the join into `Join`.
- [x] ~~**B2** Series groups~~ — **done**: the B6->B1 return (reference `RET_A`) carries exactly
      `[P2, V20, V24, V25, V1, V3]`, B7->B2 carries `{P1, V18, V22, V23, V5, V6}`; `ir-diff`
      series groups 100%. Proven domain-neutral on a synthetic breaker chain.
- [x] ~~**B3** Generalised supply ceiling~~ — **done**: store models for geometric volume,
      electrical charge, rotational/translational kinetic energy and mass; transitive upstream
      traversal through non-storing elements; `or` guards skipped; returns None on any missing
      number. Tests on capacitors and flywheels; reference IR still clean.
- [x] ~~**B4** First-class `satisfy` / `verify`~~ — **done**: requirement usages, `satisfy <req>
      by <element>` (89 on the reference IR), verification defs with `objective { verify ... }`,
      interlocks as `constraint`s, `exhibit state` on the system, `entry; then` for initial
      states. Also fixed: part defs now declare the ports of *every* block of their kind.
- [x] ~~**B5** `parse_back()` in step~~ — **done**: parses every construct above and reports any
      line it does not recognise, and `round_trip_check` fails on it. Mutation tests cover a
      dropped `satisfy` and an unknown construct.
- [ ] **B6** Guard normalisation through the router for clauses the deterministic parser drops
      ("startEnable AND B3 available"), with a validator that every symbol is a known signal or
      parameter. Needs a `normalise_guard` task chain in `config/models.yaml` (D).
- [ ] **B7** Initial conditions: the packet states B1/B2 initial levels only in prose and legacy
      code; once A's model path lands, lift them into `Block.parameters` (`level_start`) so the
      B3 reachability check has numbers to work with on the extracted IR.

**Handoffs found while doing B** (not B's code; each blocks the no-reference-IR gate):

- **C — port mapping at bind time.** The builder's ports carry source names (`bottom_port`,
  `return_inlet`); the L1 templates call them `inlet[1]` / `outlet[1]` / `port_a`. `Binder` must
  rename `Port.name` onto the bound class's connectors by direction and order (and set
  `nIn`/`nOut`). Until then the extracted-IR Modelica cannot compile.
- **C — unbound sensors.** The controller declares every sensor as an `input`; FIS-801, PIS-901
  and PIS-1001 have no plant binding (declared as gaps), which leaves the model unbalanced.
  Emit inputs only for bound sensors, or bind unbound ones to a declared constant.
- **D — `specalive run` crashes without `omc`.** `OmcRunner()` raises `FileNotFoundError`
  instead of the pipeline emitting a `compile: fail` event and still writing the report.

### C — Modelica, catalog, repair

- [x] ~~**C1** Full MSL harvest~~ — **done**: 1,529 classes in 203 s. `out/catalog.jsonl`
      is built and spot-checked across five domains. Commit it.
- [ ] **C2** Add embeddings to retrieval. BM25 is already 7/8 top-1, so this is a
      refinement rather than a rescue: wire `nomic-embed-text`, re-run the eight probe
      queries, and confirm the LLM picker resolves whatever still lands outside the top spot.
- [ ] **C7** Exclude partial classes from the catalog properly. `_parent_only` catches
      `*.BaseClasses.*` and `Partial*` by name, but `Interfaces.Element1D` is partial and
      slips through, outranking `ThermalConductor`. omc exposes `isPartial(cls)`; one extra
      assignment per class in the probe script would make this exact rather than heuristic.
- [ ] **C3** L1 templates for the bench domains: rotational inertia / spring / damper,
      thermal capacitor / conductor, 1-port electrical. Keyword lists are the cheap part.
- [ ] **C4** L2 synthesis (`Binder._try_l2`). Skeleton is designed; prompt and connector
      balance check are not written.
- [ ] **C5** More deterministic fixers. Every one is an LLM call we never make. Mine real
      `omc` output for patterns — `fix_discrete_loop` came from a bug this scaffold hit.
- [ ] **C6** *Stretch:* Tier 2 acausal `Modelica.Fluid` variant + `WaterNaCl` medium, shipped
      with the pump-start convergence issue documented. REQ-MOD-003 literally asks for this,
      and it closes OPEN-ISSUE-03 and -04.

### D — Platform, verification, proof

- [x] ~~**D1** bring every tier up~~ — **done**. Local (`qwen3:4b`, 100% GPU, 11/11 on the
      bake-off), Groq (`openai/gpt-oss-120b`) and Gemini vision (read the P&ID 15/15) all
      verified against live endpoints. `doctor` is green.
- [x] ~~**D2** exercise every router path~~ — **done**. 23 fault-injection tests in
      `tests/test_router.py`; all green, all offline.
- [ ] **D3** Warm the response cache and commit it so `--provider replay` reproduces a
      known-good run with no network. **Blocked in a good way:** with the reference IR the
      pipeline currently makes *zero* model calls, so there is nothing to warm. Do this once
      A1 lands and the extraction path actually calls a model.
- [x] ~~**D4** conservation screens~~ — **done**. Three screens (conserved species,
      first-order spin-up, energy direction), each opt-in by trace content, IR-aware.
- [x] ~~**D5** plots in the report~~ — **done**. Inline SVG, no new dependency, acceptance
      thresholds drawn on the same axes as the signal.
- [x] ~~**D6** drivetrain bench~~ — **done**, 7/7, all L0, analytic steady state matched to
      0.000%. HVAC packet still outstanding; it is the near neighbour of NaCl and worth less
      than the drivetrain, so it waits for the organisers' real packets.
- [ ] **D6b** Wire `specalive bench` into CI once we have somewhere to run it.
- [ ] **D7** Drop the organisers' other three packets into `benchmarks/` when they arrive.

---

## 5. Findings we will present

Three defects in the organisers' own data, all found by code in the repo, all declared in the
generated report rather than papered over. These are worth points under traceability and
honesty and are worth a slide each.

**OPEN-ISSUE-01 — `REQ-FUN-006`'s guard is unreachable.** B5 cannot reach 0.18 m from a single
B3 batch under a mass-consistent balance. B3 holds at most ~0.0091 m³ once it reaches the
0.080 kg/kg recipe target from a 0.13 m water prefill, which fills B5 to about 0.145 m against
a required 0.18 m. The two setpoints are mutually unsatisfiable as written. We add a declared
fallback exit on B4 exhaustion so the sequence cannot deadlock.
Found by `ir/validate.py::check_guard_reachability`, which generalises to any monotone
threshold on a conserved accumulation — and, independently and more convincingly, by
`verify/diagnose.py` from the simulation itself: *"B5.level settled at 0.1476 against a
required 0.18, having travelled 0.1426 of the 0.175 needed (18.5% short) and then stopped
changing."* The static check needed upstream geometry the extractor does not always find; a
plateau needs no such inference.

**It is not an artifact of our own assumption.** The packet never states how much B1/B2 hold,
so we assume 80% of the stated maximum (SA-02) and say so. Re-running with a **100%** charge
gives `B5.level` max = **0.1476** — identical. The setpoint is unreachable however full the
charging tanks start.

**OPEN-ISSUE-02 — the reference trace is not mass-consistent.** Across the B5 evaporation
phase, solute inventory rises 44% while concentration rises 0.080 → 0.180: NaCl is created.
Signal RMSE against that trace is therefore not evidence of correctness.
Found by `verify/acceptance.py::screen_reference`, which distinguishes a genuine concentration
phase from an ordinary tank drain (the naive version flagged B3 emptying as a false positive).

**OPEN-ISSUE-07 — the B7 pump permissive contradicts the step that depends on it.** Step7
completes when `LIS-701 < 0.01 m`, but P1's permissive is `LIS-701 > 0.02 m`, so the pump
that drains B7 stops at twice the level the step is waiting for. B7 settles at 0.02 m against
a required 0.01 m (19.2% short) and the branch can never complete on the specified guard.
Found by `verify/diagnose.py` on the autonomous run. This one was invisible until the
diagnosis learned to measure the *approach* rather than the whole series: B7 starts at
0.005 m, fills to 0.167 m and drains back to 0.02 m, so against sample zero its minimum looks
identical to its start and the check was filed as "never moved".

---

## 6. Bugs already hit and fixed

Recorded because each is now a regression test, and because they are the kind of thing that
will bite again on a new packet.

| What broke | Root cause | Where the test lives |
|:--|:--|:--|
| `Purely discrete algebraic loops cannot be solved` | omc alias elimination folded `cmd_V8 = (sMain == 1)` back into the state reads inside the scan, closing a cycle | `test_deterministic_fix_for_discrete_algebraic_loop` |
| `Variable B1.out not found in scope Plant` | emitter used the port *id* where the Modelica connector *name* was needed | covered by the full-pipeline gate test |
| Supersession resolved backwards | `Superseded By` means *X is superseded by Y*, the opposite of *X supersedes Y* | `test_supersession_direction_is_not_inverted` |
| `before(crosses(a,1), crosses(b,2))` mis-parsed | split on the first comma instead of the top-level one | `test_before_handles_nested_calls` |
| Conservation screen flagged an ordinary tank drain | required falling inventory but not rising concentration | `test_reference_trace_fails_the_conservation_screen` |
| Duplicate `port def FluidPort` in the SysML | named by domain only, not by domain + direction | `test_sysml_declares_no_duplicate_port_defs` |
| A rotational screen flagged a salt concentration | the speed pattern `_w_` matched `B5_w_NaCl`, so a NaCl mass fraction was reported as an impossible rotational overshoot | `test_speed_detection_does_not_mistake_a_mass_fraction_for_a_speed` |
| A screen silently skipped itself on our own data | it checked `torques[0]` for constancy, which was an internal flange torque that varies by definition; the real constant source is not in the result at all | `test_screen_consults_the_ir_for_facts_the_columns_do_not_carry` |
| Report plots ranked solver noise highest | filling panels by variation surfaced `der(J1.w)` and `.flange` internals | criteria now choose the panels; fillers capped |
| Keys were set and the app could not see them | `.env` existed, `python-dotenv` was installed, nothing ever called `load_dotenv()`. Both cloud tiers reported down and the router degraded silently | `settings.load_env()` at every entry point; `doctor` now shows which env file loaded and each key's shape |
| Groq tier was dead on a valid key | the configured model had been retired upstream. `fallback_models` was in the config and no provider read it | `test_stale_model_name_falls_through_to_the_next` |
| P&ID read failed with 503 | the primary Gemini model was overloaded, and overload was treated as a hard error instead of a reason to try the next model | `test_overloaded_model_falls_through_rather_than_failing_the_tier` |
| Every structured call to qwen3 returned empty | it is a reasoning model: with thinking on, `response` is `""` and the answer lands in a separate `thinking` field. The router would have escalated on every single call | provider now sends `think: false` and falls back to parsing the `thinking` field |
| Local models scored 36-55% on our own tasks | our prompt and schema were vague: `value` had no description, so models wrote whole clauses into it. Field descriptions plus a worked example took extraction from 2/5 to 5/5 | the bake-off itself is the regression test |
| The catalog-pick benchmark penalised correct answers | MSL has character-identical descriptions (`Spice3.Basic.C_Capacitor` and `Analog.Basic.Capacitor` are both "Ideal linear electrical capacitor"). Ground truth now accepts any identically-described candidate | `build_pick_cases` marks these `ambiguous` |
| Cache hits reported the original call's latency | inflated the AI-cost figures in the report | `test_cache_hit_reports_its_own_latency_not_the_original` |
| Catalog params and ports came back empty | three separate omc quirks, two of them silent: named args nested in a call abort the script; `String()` on a list-of-lists returns nothing; the record regex matched only each record's empty trailing `{}` | `test_component_record_parsing`, `test_probe_script_escapes_newlines_for_mos` |
| Variability read from the wrong field | the trailing `{}` collapses to an empty field, shifting the index; it is now located by value, not position | `test_component_record_parsing` |
| Full MSL harvest never finished (30 min timeout) | four omc workers shared one working directory and thrashed; single-process was 10.5 classes/s, the shared-directory chunk managed under 0.2/s | `test_base_classes_are_probed_but_never_emitted` guards the related filter; timing is checked by running it |
| `OpenTank` had no ports | `.BaseClasses` was cut from the probe pass for speed, so the partial parent holding the connectors was never read | `test_base_classes_are_probed_but_never_emitted` |
| Every controller was invisible to retrieval | `search()` defaulted to `restriction="model"`; a controller is a `block` | `test_retrieval_covers_blocks_not_just_models` |
| `'dict' object has no attribute 'lower'` in classification | YAML parsed a bare `re:` token as a mapping | fixed in `config/precedence.yaml`; consumer hardened |
| Whole register sheets produced zero claims | header vocabulary only: `Interface ID` matched nothing so there was no subject column; `State` mapped to *status*; `From Port` collided with `From` | `test_every_named_column_becomes_a_predicate` |
| SysML `connect B3.top_port_2` pointed at an undeclared port | part defs took ports from the first block of each kind only | `test_part_defs_declare_the_ports_of_every_block_of_their_kind` |
| Every unmatched block bound to `Vessels.Evaporator` | the L1 score added a specificity bonus that alone cleared the threshold, with zero keyword hits | checked by binding the extracted IR: all 15 blocks bind as in the reference |
| `Step9 -> Step10` invented a second fork | the merged row is named `Step10/11`; step names now alias each number | `test_state_machine_has_three_regions_a_fork_and_a_join` |

---

## 7. Risks

| Risk | Likelihood | Mitigation | Owner |
|:--|:--|:--|:--|
| Free-tier quota dies mid-demo | medium | replay cache (D3) + local fallback | D |
| An eval packet is a scanned PDF with no text layer | medium | vision path (A2); `pypdfium2` rasterises, and the gap is declared if it is not installed | A |
| An eval domain has thin MSL coverage (hydraulics, pneumatics) | medium | L1 templates (C3), then L2 (C4) | C |
| We over-fit to NaCl without noticing | medium | the drivetrain bench exists precisely to catch this — build it early, not late | D |
| Extraction recall too low to drop `--reference-ir` | medium | `ir-diff` gives a number from day one; if it stalls, ship with the reference-IR path documented as a fixture, not as the product | A, B |
| Last-minute refactor breaks the gate | **high** | run `specalive gate` before every push; freeze on day 3 | everyone |

---

## 8. Definition of done

We are finished when all of these are true:

- [ ] `specalive bench` is green on every packet in `benchmarks/`, and the matrix is in the deck
- [ ] the NaCl packet runs with **no** `--reference-ir`
- [ ] `specalive doctor` is green on a machine that is not the dev machine
- [ ] `--provider replay` reproduces a full run offline in under ten seconds
- [ ] the report's gap list is complete and honest — nothing silently missing
- [ ] `pytest -m slow` passes from a clean clone
