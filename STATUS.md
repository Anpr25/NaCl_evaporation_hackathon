# SpecAlive — status, decisions, backlog

Companion to [PLAN.md](PLAN.md). PLAN.md is *what we are building and who owns what*. This is
*where we are, what we already decided and why, and what is left*.

Keep this current. When you finish something, move it from §4 to §2 with the evidence that
proves it. When you make a call that another person could reasonably have made differently,
add it to §3 — that is how we avoid re-litigating decisions at 2am on day three.

**Last updated:** after the catalog harvest was made to work at full scale.
**Verdict:** the hard gate passes, the pipeline runs end to end, the full Modelica catalog
is built and retrieval works across five domains. Three modules are still stubs. On track.

---

## 1. One-screen summary

| | |
|:--|:--|
| Hard gate (Modelica compiles) | **PASS** |
| Simulation runs 3000 s | **PASS** |
| Acceptance checks | **11/12** (the twelfth is a defect in the source data — see §5) |
| Tests | **24/24** green (22 fast, 2 gate) |
| Pipeline stages implemented | 10 of 10 wired; 3 have stubbed internals |
| Modelica catalog | **1,529 classes** harvested from full MSL in **203 s** |
| Catalog retrieval | **7/8 top-1** across rotational, electrical, fluid, signal, thermal — BM25 only, no model |
| Domains proven | fluid + thermal + sequential control end to end; catalog retrieval across five domains |
| LLM calls required to reach the above | **zero** |

Reproduce:

```bash
pip install -e .
python -m pytest              # 22 fast
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
| reconcile (IR assembly) | *stub* | `TODO(B1..B5)` in `reconcile/builder.py` |
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
  with escalation. Providers written for Ollama, Groq, Gemini and replay. **Not yet exercised
  against a live endpoint** — no keys and no Ollama on the dev machine.
- **CLI**: `doctor`, `harvest`, `run`, `gate`, `bench`, `serve`, `ir-diff`. All run.
- **Web app**: FastAPI + SSE, no build step. Smoke-tested (`/`, `/api/health`, `POST /api/runs`).
- **Tests**: 24, each encoding a real bug or a planted trap.

### 2.4 Analysis of the packet

All six planted traps identified and resolved, each with a `DecisionRecord` naming the rule
and the trap. Routing verified against the supplied trace by decoding valve commands per
state. Two defects found in the organisers' own data (§5).

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
| D22 | A hand-built **reference IR** is a first-class artefact | decouples B/C/D from A on day one, and doubles as A's scoring oracle via `ir-diff` | must be kept in step with the IR schema |

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

- [ ] **B1 `[!]`** `reconcile/builder.py` TODOs B1–B5: assemble blocks, connections, signals,
      the FSM and the scenario from resolved claims. Precedence wiring is done; this is
      mechanical.
- [ ] **B2** Series-group detection: walk from/to chains and populate
      `Connection.series_elements`. Test: `RET_A` must carry `{P2,V20,V24,V25,V1,V3}`.
- [ ] **B3** Generalise `_supply_ceiling` in `validate.py` beyond geometric vessels, so the
      guard-reachability check works for charge and rotational energy too.
- [ ] **B4** Richer SysML: `satisfy` / `verify` as first-class relationships rather than
      trace comments.
- [ ] **B5** Keep `parse_back()` in step with the emitter — it is our only structural check,
      and a stale one is worse than none.

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

- [ ] **D1 `[!]`** `ollama pull qwen2.5:3b-instruct-q4_K_M nomic-embed-text`; get Groq and
      Gemini keys; `specalive doctor` all green. Nothing in `llm/` has met a live endpoint yet.
- [ ] **D2** Exercise every router path deliberately: quota exhaustion, offline, replay, and
      a tier returning schema-invalid JSON. An untested fallback is not a fallback.
- [ ] **D3** Warm the response cache and commit it so `--provider replay` reproduces a
      known-good run with no network.
- [ ] **D4** Charge and energy conservation screens in `screen_reference`, for the electrical
      and drivetrain benches.
- [ ] **D5** Plots in the report (matplotlib → inline SVG), overlaying the reference trace
      only where it is trustworthy.
- [ ] **D6** Build the HVAC and drivetrain bench packets; wire `specalive bench` into CI.
- [ ] **D7** Drop the organisers' other three packets into `benchmarks/` when they arrive.

---

## 5. Findings we will present

Two defects in the organisers' own data, both found by code in the repo, both declared in the
generated report rather than papered over. These are worth points under traceability and
honesty and are worth a slide each.

**OPEN-ISSUE-01 — `REQ-FUN-006`'s guard is unreachable.** B5 cannot reach 0.18 m from a single
B3 batch under a mass-consistent balance. B3 holds at most ~0.0091 m³ once it reaches the
0.080 kg/kg recipe target from a 0.13 m water prefill, which fills B5 to about 0.145 m against
a required 0.18 m. The two setpoints are mutually unsatisfiable as written. We add a declared
fallback exit on B4 exhaustion so the sequence cannot deadlock.
Found by `ir/validate.py::check_guard_reachability`, which generalises to any monotone
threshold on a conserved accumulation.

**OPEN-ISSUE-02 — the reference trace is not mass-consistent.** Across the B5 evaporation
phase, solute inventory rises 44% while concentration rises 0.080 → 0.180: NaCl is created.
Signal RMSE against that trace is therefore not evidence of correctness.
Found by `verify/acceptance.py::screen_reference`, which distinguishes a genuine concentration
phase from an ordinary tank drain (the naive version flagged B3 emptying as a false positive).

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
| Catalog params and ports came back empty | three separate omc quirks, two of them silent: named args nested in a call abort the script; `String()` on a list-of-lists returns nothing; the record regex matched only each record's empty trailing `{}` | `test_component_record_parsing`, `test_probe_script_escapes_newlines_for_mos` |
| Variability read from the wrong field | the trailing `{}` collapses to an empty field, shifting the index; it is now located by value, not position | `test_component_record_parsing` |
| Full MSL harvest never finished (30 min timeout) | four omc workers shared one working directory and thrashed; single-process was 10.5 classes/s, the shared-directory chunk managed under 0.2/s | `test_base_classes_are_probed_but_never_emitted` guards the related filter; timing is checked by running it |
| `OpenTank` had no ports | `.BaseClasses` was cut from the probe pass for speed, so the partial parent holding the connectors was never read | `test_base_classes_are_probed_but_never_emitted` |
| Every controller was invisible to retrieval | `search()` defaulted to `restriction="model"`; a controller is a `block` | `test_retrieval_covers_blocks_not_just_models` |
| `'dict' object has no attribute 'lower'` in classification | YAML parsed a bare `re:` token as a mapping | fixed in `config/precedence.yaml`; consumer hardened |

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
