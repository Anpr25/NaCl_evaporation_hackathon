# SpecAlive — consolidated decision log

One document for every decision the four workstreams recorded, as of **2026-10-06**. Built from
[A.md](A.md), [B.md](B.md), [C.md](C.md) and [D.md](D.md), the B decision table in
[STATUS.md §3](../STATUS.md), and the commit messages of `modelling_improvement_Dev-D` steps 1–3,
which landed without a Decisions entry.

The four per-workstream files stay as the detailed record — measurements, dead ends, the
reasoning in full — and code cites them (`emit/sysml_read.py` points at C.md). This file is the
index and the current state: what was decided, why, what it cost, and whether it still stands.

**How to read the IDs**

| Prefix | Meaning | Source |
|:--|:--|:--|
| `A-nn` | workstream A (ingestion, extraction) | A.md |
| `B-Dnn` | workstream B (IR, reconcile, SysML) — the IR-assembly rows of STATUS §3 | STATUS.md, B.md |
| `C-nn`, `C-AI-n` | workstream C (Modelica, catalog, repair) | C.md |
| `PV-nn` | workstream D (platform, verification, proof). **Numbered here for the first time** — D.md records its decisions in prose | D.md |
| `S1`–`S3` | Dev-D steps 1–3, recorded only in commit messages | `fda9ea2`, `47483f2`, `adbf5ec` |
| `SA-nn` | registered assumption conventions | `config/assumptions.yaml` |

Status column: **stands** · **revised** (by the ID named) · **superseded** · **partial**.

---

## 1. Where the system stands

SpecAlive turns an engineering evidence packet (registers, specs, P&IDs, test procedures, emails)
into an IR, SysML v2 and one self-contained Modelica file that compiles, simulates and is
scored against the packet's own acceptance criteria.

```
ingest → extract (deterministic, then model) → reconcile (precedence) → validate
       → SysML v2 → bind & wire → Modelica (one file, saveTotalModel) → compile ⇄ repair
       → simulate → verify (five-level gate) → report
```

| Workstream | Owns | State |
|:--|:--|:--|
| **A** — ingestion, evidence | `ingest/`, `extract/` | model text + vision extraction live; skeleton pass; row-level status; last recall 83% |
| **B** — IR, reconcile, SysML | `ir/`, `reconcile/`, `emit/sysml.py` | IR assembled from claims; SysML round-trips clean |
| **C** — Modelica, catalog, repair | `catalog/`, `emit/modelica.py`, `repair/`, `modelica/`, `verify/omc.py` | wiring checked before emission; one self-contained `.mo`; backlog empty since 2026-09-25 |
| **D** — platform, verification | `llm/`, `verify/`, `web/`, `cli.py`, `benchmarks/` | five-level gate on every surface; reference-trace scoring; independent criterion review |

**Latest results** (2026-10-04/06):
- **Benchmarks:** drivetrain **7/7 MET**, nacl_evaporation **11/12** (BAT09-04 fails by design, OPEN-ISSUE-01), hvac **no packet**.
- **Dev-D packets** (cloud):
  - tank — MET, 7 of 13 criteria checkable;
  - IAQ — peak CO₂ 996.5 ppm against the reference ≈996;
  - magnetic circuit — fluxes within 0.01% of the packet's own dataset;
  - NaCl — **INCOMPLETE**, because its three-consumer cooling header is unbound.
- **Tests:** 244 fast + 11 slow, green.

---

## 2. Principles that run through every workstream

These are not separate decisions; they are the reason most of the decisions below look the way
they do.

1. **Deterministic core, models at the edges** (STATUS D2, C-05, A-07). Code does everything
   that has an exact answer; a model is called only for judgement, and the cheapest tier that can
   do the job is tried first — *as measured*, not as hoped.
2. **Ground truth over recall.** A model may choose, never invent:
   - a quote must be a literal substring of its source (A-01);
   - a class must exist in the harvested catalog (C-03);
   - a repair may look up a verified signature (C-AI-2) or the compiler's own documentation
     (C-34) instead of guessing.
3. **Never silent.** A missing fact becomes a gap, an assumption citing a registered convention,
   or a question (PV-17–PV-20). A criterion that cannot be checked is "not machine-checkable",
   never passed. A gate that compiled with parts missing says INCOMPLETE (C-28).
4. **Precedence, never recency** (STATUS D13): supersession → status → authority → revision →
   specificity → corroboration → escalate.
5. **Measure, then decide — and write down what you got wrong.** Several decisions below exist
   because a measurement overturned the plan: embeddings dropped (C-AI-4), local-first
   extraction reversed (A-07), the `ir-diff` ruler rebuilt (PV-14).

---

## 3. Workstream A — ingestion and evidence

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| A-01 | Reject any claim whose quote is not a literal substring of its source, checked **per claim** | removes almost all small-model fabrication at no cost; per-claim so one bad quote never sinks a batch | a correct paraphrase is dropped too — recall traded for honesty. Live: 698 NaCl claims, ~19% of raw text claims dropped | stands |
| A-02 | The text model sees **prose blocks only** | tables, key-values, graphs and code already have exact readers | a `kinds=` filter on `Document.chunks` | stands |
| A-03 | **Confidence fixed per path**: table/key-value 0.95, graph 0.9, supersession 0.8, text 0.6, skeleton 0.5, vision 0.4 | precedence needs numbers it can trust; a model's self-report is not one | a judgement call, recorded so it can be argued with | stands |
| A-04 | Images **embedded in `.docx`** reach the vision path through the shared tiling helper | P&IDs usually arrive pasted into documents | transparent images needed a fix (A-05 bug 2) | stands |
| A-05 | **One malformed claim never discards its batch** (`kind: null` → `note`; guarded construction) | an explicit null crashed extraction and lost the deterministic claims with it | a malformed claim is skipped with a warning | stands |
| A-06 | OpenRouter tiers on **`:free`** models; HTTP 200-with-error-body mapped to the router's error types | live testing should not spend credits; the free tier returned `{"error": 503}` with status 200 and crashed on `choices` | free tiers overload more often | stands |
| A-07 | Extraction calls the **cloud model first**, local 3B underneath | measured on four packets: the 3B missed facts nothing downstream can recover | needs a key and quota; offline still works | stands (reverses the original local-first plan) |
| A-08 | One **whole-packet skeleton** read, subordinate to the deterministic path — verbatim quotes, confidence 0.5, catalog-verified classes, can only add | no chunk contains the system; on three of four packets the untabulated half was recovered by nothing | one large call, capped at 180k chars / 18k per document | stands |
| A-09 | Header vocabulary fixed on evidence: no `start`/`end` as endpoints, `… id`/`… no` is the id, exact synonyms before fuzzy prefixes, a `scope` predicate, `… value` is the value | each rule came from a packet that extracted the wrong thing (twelve phantom components; a scope column read as an id; a whole calculations sheet ignored) | each rule is a special case, so each carries its packet | stands |
| A-10 | A claim carries its **row's own status**; superseded wins | two rows of one register are invisible to source-level precedence; the tank limit resolved to a superseded 0.78 m | *Approved* + *Effective? No* counts as not in force | stands; **partial** answer to per-claim authority |
| A-11 | A name repeated with **different scopes** becomes separate subjects | two tanks' "Low level limit" competed in one contest and one tank lost its limit | only repeated names are qualified | stands |
| A-12 | Claims also written as **`claims.json` + `claims.schema.json`** | the evidence trail was buried in `ir.json` | none; schema generated from the frozen `EvidenceClaim` | stands |

**Related rows owned elsewhere:** STATUS D17 (source class read from the title area only),
D22 (reference IR as A's scoring oracle), B-D28 (B edited A's table extraction), B-D32 (vision
edges corroborate, never create).

---

## 4. Workstream B — IR, reconciliation, SysML

B's decision table is the **IR-assembly** block of STATUS §3, prefixed `B-` here because STATUS
reuses the numbers D27–D34 in two tables (see §11).

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| B-D27 | A subject is typed by the **shape of its facts** (`from`+`to` = hop, `next` = step, numeric `value` = parameter, tagged + physical kind = part), never by sheet or file name | an unseen packet will not name its sheets "Interfaces" | a subject fitting no shape is not built; `GAP-UNUSED-*` counts them | stands |
| B-D28 | Table extraction keeps **every named column**; the id column must be unique | the vocabulary dropped whole sheets | touches A's `extract/claims.py`; more `note` claims | stands |
| B-D29 | **Series elements are real parts**, lowered into one path (`abstracted_into`) | SysML keeps every valve; Modelica collapses them (STATUS D11) | more blocks than the reference | stands |
| B-D30 | A **named group** is resolved from wherever its members are listed, superseded records included, each derivation a `DecisionRecord` | the superseded text is the only place the B1 group is spelled out | the argument is written down | stands |
| B-D31 | A guard clause the parser cannot formalise is **dropped and declared**, never guessed | honesty over apparent completeness | some transitions fire on the next scan | stands |
| B-D32 | Drawing/vision edges **corroborate** register topology; they never create it | a drawing is not a routing authority; vision edges were mostly wrong | uncorroborated edges listed in an info gap | stands |
| B-D33 | `satisfy`/`verify` are **first-class SysML relationships**; `parse_back()` must recognise every emitted line | a trace comment cannot be checked | satisfaction is heuristic, explained per requirement | stands |
| B-D34 | Validation treats a not-yet-bound block as `info` | validation runs before binding | an unbound block *after* binding is still an error | stands |

**B's fix of 2026-09-25 (B.md):** `TK_101`/`TK_102` were misread as "external boundary"
because a *Tag / Scope* column was taken as the row id, merging every setpoint into the tank's
entity. Fixed by exact-synonym-first headers and a `scope` predicate (now A-09), a fallback that
no longer drops a revisioned register, a corrected signal/physical split, and controllers kept
out of the binding cascade.

---

## 5. Workstream C — Modelica, catalog, repair

### Generation and catalog

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| C-01 | Tier 1 emits a **causal directed-flow abstraction** (`SpecAlive.Interfaces`), not `Modelica.Fluid` | no pressure network, so no nonlinear solves; the packet warns the acausal variant stalls at pump start | REQ-MOD-004/005/006 have no effect in Tier 1 (OPEN-ISSUE-04) | stands; cost closed by Tier 2 (2026-09-25), Tier 1 still default |
| C-02 | The catalog is **regenerated per machine, never committed** | it must match the installed MSL | ~200 s setup, prompted by `doctor` | stands (PLAN.md's "commit it" contradicts this — strike it) |
| C-03 | **Bind before emitting**, only to classes and parameters the catalog verified | makes invented classes and connectors structurally impossible | the emitter cannot improvise | stands |
| C-04 | Ports carry an IR **id** and a Modelica **name** | stable handle vs what the class calls it | the emitter must resolve one to the other | stands |
| C-07 | **Partial classes excluded** via omc `isPartial()`, at emit time | name heuristics caught 0 of 127; binding one fails the build, not `checkModel` | one omc call per class, no measurable slowdown | stands |
| C-08 | The Modelica is **derived from the SysML** (behind `--from-sysml`) | "Modelica derived from the SysML, correspondence shown" — the derivation becomes the code path | a parser in front of the hard gate | stands; parity reached 2026-09-25, **still not the default** |
| S1 | Parts are **classified before binding** (component, boundary, instrument, operator input, controller); connector families chosen first by weighted set cover; a **binding memory** learns from omc's verdicts across runs | binding one part at a time from 1,400 classes cannot produce parts that mate; instruments are readings, not components | memory needs guarding (S3) | stands |
| S3 | IAQ templates (well-mixed zone, commanded supply, trace source, biased P controller); memory may never pull a signal block into a fluid family, never reuse a table class without its table, never credit a binding that dropped a wire | IAQ could not bind its zone at all; memory had learned three wrong lessons | more templates to maintain | stands |

### Repair

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| C-05 | **Deterministic fixers first**, model only for semantic failures | most Modelica errors are mechanical | a fixer library | stands; extended with catalog fixers |
| C-06 | Repair is **bounded (6) and keep-best** | never thrash or burn quota | may stop early, and says so | **revised** by C-26 and C-AI-2 |
| C-AI-1 | The repair gate is **check, then build + simulate** | the simulate branch was dead code; simulate failures got no repair | — | stands |
| C-AI-2 | Repair is an **agent**: diagnosis and strategy before the patch, memory of rejected attempts, a catalog `lookup` tool | the compiler points at the symptom; each iteration started blind | lookup never exercised on the eight faults | stands; extended by C-34 |
| C-AI-3 | L2 synthesis is **generate → critique → revise → omc judges** | free generation is the risky tier | one critique pass | stands |
| C-AI-4 | Retrieval: BM25 → (embeddings) → model picks **by class name** → validated | retrieval was 5/10 top-1 | — | **partial**: embeddings dropped on measurement (binding identical without them) |
| C-AI-5 | A **fault-injection harness** (`specalive faults`) measures recovery with and without AI | the demo number; exercises paths a working packet never hits | — | stands — 2/8 → 6/8 without a model, 5/8 → 7/8 with one |
| C-24 | A catalog-tier repair is **written back to the IR**, then re-derived | a binding is an IR decision; patching only the `.mo` shipped the wrong SysML | one extra build pass per fix | stands; extended by C-27 |
| C-25 | SysML is **re-emitted every build pass** | retries read the previous pass's SysML | milliseconds | stands |
| C-26 | A grounded fix needs only **"not worse"**; a model fix must improve; rejected patches remembered | omc stops at the first error, so a correct fix can leave the count flat | slightly weaker keep-best at the deterministic tier | stands (revises C-06) |
| C-27 | A **structural failure produces IR edits** — a graph rule first, one grounded agent call second, ungrounded blocks declared | "which blocks must exist" is a graph question | one build pass, one model call when needed | stands |

### Wiring, the gate, and the deliverable (Dev-D step 4 onward)

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| C-28 | The gate has **five levels** — NOT_MET / INERT / INCOMPLETE / UNVERIFIED / MET — and `--strict` fails on anything short of MET | "compiles and simulates" was satisfiable with parts edited out | changes what "met" may mean everywhere | stands (**revises** the three-state gate of 2026-09-24) |
| C-29 | Every evidenced connection is **classified before emission** (`emit/wiring.py`) | a dropped wire silently picked which safety net fired | one pass over the connections | stands |
| C-30 | A second wire into an **acausal** connector is a **branch node** | Kirchhoff's law is what `connect()` does; the leakage branch had been stranded | three-line exception, causal inputs still protected | stands |
| C-31 | A **potential source** drives flow out of its positive terminal | `V_m = N·i`; every magnetic flux had the wrong sign | an explicit allow-list | stands |
| C-32 | A **through-variable sensor** is moved into series | in parallel it reads nothing, and its grounded end shorted the yoke | connection re-routing | stands |
| C-33 | One **self-contained `.mo`** via omc's own `saveTotalModel`; the new class name is read back, never assumed | a hand merge cannot know which classes the plant uses; omc renames `X` to `X_total` | one extra omc round trip; the file loads with `loadFile()`/`omc`, **not** OMEdit's GUI (omc's own documented limit) | stands |
| C-34 | Repair gets a **`doc_lookup`** channel answered from the live OpenModelica Scripting docs | the agent may now fix how a model is built or saved; recall is the failure `lookup` exists to stop | an optional, cached fetch; never fatal, never offline | stands |
| — | The **domain-wide library vote** in `enforce_connectable` is retired | the step-1 family plan decides library first; the vote only overruled it | — | stands |

---

## 6. Workstream D — platform, verification, proof

`PV-nn` numbers are assigned here; D.md records these in prose under the dates shown.

### Models and routing (2026-09-24)

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| PV-01 | `.env` loaded at every entry point (`settings.load_env()`) | keys existed and nothing read them; cloud tiers silently down | new entry points must call it | stands; **revised** 2026-10-06 to also search the repo root |
| PV-02 | Model ids **verified against live `/models`**; `fallback_models` actually walked | a 404 model is a dead tier | one request per stale name | stands |
| PV-03 | **502/503/529 fall through to the next model**, not the next tier | transient overload is the commonest free-tier failure | one wasted request | stands |
| PV-04 | The catalog picker answers with a **class name, not an index** | a 4B model fell back to "0"; a name never offered is a detectable hallucination | longer output — accuracy 3/6 → 6/6 | stands |
| PV-05 | Every schema field has a **description**, every prompt one worked example | the single biggest quality lever, and free | longer prompts | stands |
| PV-06 | Local models run with `num_gpu: 99`; reasoning models with `think: false` | measured 3.2× speed-up; qwen3 otherwise returns an empty response | per-machine setting (OOM on a 2 GB card) | stands, with caveat |
| PV-07 | Router modes **auto / local / cloud / replay / none**; replay allows the same tiers as auto | replay that listed only t0 did nothing, quickly | three paths to test | stands |

### Verification and honesty (2026-09-24)

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| PV-08 | Reference-data screens are **opt-in by content and tri-state**, and consult the IR | silence must not look like approval; omc removes constant-torque aliases | some traces get no screen | stands |
| PV-09 | Report plots are **hand-written inline SVG**; the criteria decide what is plotted | one self-contained file, readable in dark mode | own axis code | stands |
| PV-10 | Drivetrain built as the **second-domain** benchmark | shares nothing with NaCl — the real generality proof | HVAC waits for a real packet | stands |
| PV-11 | An unbound real input first looks for a **setpoint the evidence states** | the condenser's 0.1 kg/s was extracted, then ignored | — | stands |
| PV-12 | Only **actuator** bindings suppress an input's drive equation | a sensor binding is a read | — | stands |
| PV-13 | Each pass gives a declared fallback only to the **earliest blocked step** per region | a later step measured against a deadlocked one manufactured a contradiction | more passes | stands (revises PV-18) |
| PV-14 | `ir-diff` compares **meaning, not spelling** — edges block-to-block, signals by role and binding | it scored vocabulary: 0% connections on an identical graph | naming reported separately, unscored | stands — 3/10 → 8/10, recall 83% → 92% |
| PV-15 | `Assumption` and `Question` are **separate records from `Gap`**, ahead of gaps in the report | rule 6.3: missing information is inferred with a stated assumption or asked | two IR types | stands |
| PV-16 | An inference must cite a **pre-registered convention** (`config/assumptions.yaml`) or count as unfounded | a basis invented at the call site is a rationalisation | the register must be maintained | stands — 0 unfounded |
| PV-17 | A red check is **diagnosed**: unreachable / stalled / unsettled | seven reds from one cause mislead as much as none | thresholds to choose | stands |
| PV-18 | **SA-05**: an unreachable guard gets a marked fallback beside the untouched one, dwell from the trace (1.25×) | a spec defect should cost one step, not twelve | a blocking question stays open, by design | stands (revised by PV-13) |

### Gate surface, artifacts, verification (2026-10-04)

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| PV-19 | CLI, web UI and report show the **five-level verdict** (C-28); amber for the three middle levels; live parts/wires metrics | the gate stopped being a bool | — | stands |
| PV-20 | The report separates **missing from the model** vs **at the boundary by decision** | the wiring check's distinction was lost by the page | — | stands |
| PV-21 | Claims also published as **`claims.json` + schema** (with A-12) | consumers validate without reading Python | — | stands |
| PV-22 | A **reference trace earns scored checks**: columns auto-paired by tag and quantity word, 10% normalised RMSE, only after `screen_reference` passes; never guesses a pairing | the RMSE was computed and never gated | low recall by design; NaCl's trace fails the screen, so NaCl stays at 12 checks | stands |
| PV-23 | A formalised criterion gets an **independent review** by a different vendor's model; a disagreement reverts it to not-machine-checkable and is never remembered | nothing checked that an expression meant what the English said | double the calls per criterion; reviewer must see the same context as the translator | stands — tank 5 → 7 checkable |

### Operations (2026-10-06)

| ID | Decision | Why | Cost | Status |
|:--|:--|:--|:--|:--|
| PV-24 | Every path the code ships with or keeps between runs resolves against the **repo root** (`settings.REPO_ROOT`, `repo_path()`); a path a user typed is tried where they typed it first | started one folder up, five things failed — four silently (catalog "not built", no models, no `.env`, presets refused, harvest crashed) | assumes the editable install the README describes | stands — verified from the parent folder: drivetrain MET 7/7 through the web API |

### Procedure-driven scenarios and checks (Dev-D step 2, `47483f2`)

| ID | Decision | Why | Status |
|:--|:--|:--|:--|
| S2 | Duration, logging interval, command schedule and stimuli come from the **test procedure**; procedure criteria are formalised at verify time against real columns, validated by evaluation, remembered for offline runs; the check language gains `during`, `max/min`, `approx`, `ratio`, `state`, `enters`, `elapsed`, `exclusive`, `&&` | three of four packets had extracted 0/0 checks and the wrong run length, so "inert" could not even be judged | stands (extended by PV-22, PV-23) |

---

## 7. Decisions that were later changed

So nobody revives the old version by accident.

| Original | Changed by | What changed |
|:--|:--|:--|
| C-06 keep-best, `break` on rejection | C-26, C-AI-2 | grounded fixes need only "not worse"; a rejection is recorded and the loop continues |
| Three-state gate (C10, 2026-09-24): `result.ok` is the headline | C-28, PV-19 | five levels; `result.verdict` is the headline; `.ok` still means compiles + simulates |
| C-AI-4 embedding rerank | measurement, 2026-09-24 | dropped: binding identical with BM25 + picker alone |
| Original plan: local 3B extracts first | A-07 | cloud first, local underneath |
| PV-18 fallbacks applied to every blocked step per pass | PV-13 | only the earliest blocked step per region |
| `enforce_connectable` domain-wide library vote | S1 family plan | vote retired |
| Two-file Modelica deliverable (`GeneratedPlant.mo` + `SpecAlive.mo`) | C-33 | one self-contained file |
| PV-01 `.env` searched from the current directory up | PV-24 | the repo root is searched too |
| PLAN.md: "commit `out/catalog.jsonl`" | C-02 / STATUS D26 | never committed — regenerated per machine |

---

## 8. Hand-offs still worth reading

| From → to | What |
|:--|:--|
| D → anyone touching `formalise()` | a fact added to the translator's context must also go into `VERIFY_PROMPT`, or the reviewer starts rejecting correct translations again (PV-23) |
| C → D | any new surface showing the gate must read `PipelineResult.verdict`, not `.ok` (C-28) |
| C → D | the Modelica artifact has no sibling file; nothing should assume a second `.mo` (C-33) |
| C → everyone | a green NaCl run exercises no repair (0 iterations); use the corrupted-IR probe or `specalive faults` |
| C → everyone | `num_gpu` is per-machine; the shared value OOMs a 2 GB card |
| D → C | the `BUSY` map in the web UI must track which tier runs in which stage |
| C → A | decide on the pdfplumber/pdfminer `Unexpected EOF` test: pin the dependency or relax the assertion |

---

## 9. Open items

Checked against later work; several items one log still lists as open were closed elsewhere.

### Still open

| Item | Owner | Since |
|:--|:--|:--|
| **CW_header unbound** — feeds three consumers, bound class has two ports, so NaCl reports INCOMPLETE (15/16 parts, 16/19 wires) | C | 2026-10-04 |
| **Prose-only sequences** — a controller described only in narrative text still yields no state machine (tables are solved) | A/B | 2026-09-25 |
| **Per-source authority** still the title-area heuristic (A-10 covers rows only) | A | 2026-09-23 |
| **Router**: it now waits for its own tracked per-minute window, but a 429 *returned by the provider* still disables that tier for the rest of the run (`router.py`, `quota.disable`) — no `retry_after` | D | 2026-09-25 (rechecked 2026-10-06) |
| **`t3_openrouter` missing** from the `catalog_pick` and `repair_modelica` chains | D | 2026-09-25 |
| **`--reference-ir` cannot reload an IR with fallbacks** (`unknown symbol 'dwell'`) | D/A | 2026-09-25 |
| **`_agent_bindings`** reports "declined to choose one" for router failures and partial answers too | C/D | 2026-09-25 |
| **`packet.json` `filename: None`** for every source — traceability empty on non-NaCl packets | A | 2026-09-25 |
| **D-2** — twelve `SP_*` guard symbols referenced but never declared in the SysML | B | 2026-09-24 |
| **D-3** — Python `False` leaks into the SysML; `useSupport` typed Real | B | 2026-09-24 |
| Freeze or promote the load-bearing SysML **comment forms** (`// @interlock`, `// @series` …) | B | 2026-09-24 |
| **`--from-sysml` not the default** until it runs on an unseen packet | C | 2026-09-24 |
| **Magnetic circuit**: 18 of 22 criteria unformalised this round (quota); two 50 Hz RMS voltages unreachable by a transient model | D | 2026-10-04 |
| **Tank AC-04** still rejected on independent review (plausibly a genuine catch, unproven) | D | 2026-10-04 |
| **IAQ AC-05** formalised as a `ratio` that divides by zero | D | 2026-10-04 |
| **HVAC benchmark** has no packet; **CI** not wired to `specalive bench` | D | 2026-09-24 |
| **STATUS.md** stale (catalog 1,402 not 1,529; retrieval 5/10 not 7/8; "51 fast" tests) and **duplicate IDs D27–D34** | D | 2026-09-24 |
| Pin the **OpenModelica version** (1.26.3) in the README | C | 2026-09-24 |

### Open by design (must stay)

- **OPEN-ISSUE-01** — NaCl B5 cannot reach 0.18 m from one B3 batch; BAT09-04 fails and the report says why.
- **OPEN-ISSUE-07** — NaCl Step7 waits for `< 0.01 m`, P1 stops at `> 0.02 m`.
- **GAP-MEDIUM-01** — WaterNaCl medium not reconstructible from the packet; the pump-start stall (REQ-MOD-003) cannot be reproduced.

### Closed since a log called them open

| Item (where it was raised) | Closed by |
|:--|:--|
| TwoTank `"state_machines": []` (C, 2026-09-25) | S2 — the transition table is read; controller 8/8 states; tank **MET** |
| TK_101/TK_102 read as "external boundary" (C, 2026-09-25) | B's scope-column fix (A-09) and C-27 |
| Surface `live`/`liveness` in the report (C, 2026-09-24) | PV-19/PV-20 "Model is live" card |
| Warm the replay cache, D3 (D, 2026-09-24) | `88123ed` — replay reaches the cache; cache kept in git |
| D-1 port id/name mismatch in SysML (C, 2026-09-24) | B's `_port_ref`; residual solved on C's side |
| Undriven `K1.cw_flow`; B6/B7 never charged (D, 2026-09-24) | PV-11 and PV-12 |
| IAQ zone cannot bind (Dev-D step 2) | S3 templates — IAQ runs, peak CO₂ 996.5 ppm |
| Magnetic circuit 0/10, wrong flux sign (Dev-D step 2) | C-30–C-32 — within 0.01% of the packet's data |
| Two `.mo` files per run (2026-10-04 request) | C-33 |
| UI refuses runs when started outside the repo (2026-10-06) | PV-24 |

---

## 10. Bugs worth remembering

The ones whose *shape* will recur, grouped by lesson.

**A safety net that passes the gate is not a fix.**
- The strand/omit/idealise passes let models compile with their leakage branch, flux sensor
  and cooling header removed (C-28).
- "HARD GATE MET" printed above 0/10 acceptance (C10).

**Two code paths answering one question differently.**
- `_emit_plant` declared parts by one predicate and connected them by another, so it wrote
  `connect()` to undeclared parts (`eeb38aa`).
- SysML ports were declared by name and referenced by id (D-1).
- SysML was emitted once while the IR changed every pass (C-25).

**The ruler was broken.**
- `ir-diff` scored spelling, not structure: 0% connections on an identical graph (PV-14).
- D's own picker benchmark penalised correct answers that shared a description.

**Silent degradation.**
- `.env` never loaded (PV-01).
- `config/models.yaml` not found and the exception swallowed (PV-24).
- A transparent diagram became a black rectangle (A-05).
- An `AssumptionLog` merge dropped both blocking questions.

**A token means two things.**
- *Tag / Scope* read as an id (A-09).
- `B1.m` (mass) paired with `B1_level_m` (metres) (PV-22).
- `_w_` matched salt's mass fraction as a rotational speed.
- `start`/`end` read as connection endpoints in a schedule (A-09).

**The reviewer knew less than the work it reviewed.**
- The criterion reviewer flagged the scan-period time shift and an undescriptive column name as
  mismatches, because it lacked the translator's context (PV-23).

**Measured, not assumed.**
- The Groq `tpm` was 8,000, not the 12,000 in config.
- The first structural prompt was 35,883 characters against that limit; factored to 7,955.
- `saveTotalModel` renames its class (C-33).
- Ollama left a third of the GPU unused (PV-06).

---

## 11. Housekeeping

- **Duplicate IDs in STATUS.md §3**: D27–D34 appear twice — once under *Operations* (`num_gpu`,
  `think`, picker, cache latency, `.env`, fallbacks, 502/503, model ids) and once under *IR
  assembly* (B's rows). This file calls B's set `B-D27…B-D34`; STATUS should renumber one block.
- **No Decisions entries for Dev-D steps 1–3**; their decisions are summarised here as S1–S3 from
  the commit messages.
- **A.md was empty** until 2026-10-06; it is now reconstructed from shreedhar_cctech's commits
  (`46843db`, `0d1b294`, `7fba7fe`) and later extraction work.
- When a decision changes, edit its row here and in its workstream file, and note the date —
  do not add a second row saying the opposite (C.md's rule, adopted for this file).
