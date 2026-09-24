# C — Modelica, catalog, repair

Decisions, open questions and hand-offs from workstream C. Companion to [PLAN.md](../PLAN.md)
(what we are building) and [STATUS.md](../STATUS.md) (where we are).

**What goes here:** anything a teammate could trip over, re-litigate, or reasonably have
decided differently. Not a changelog — the git log is the changelog.

**Format:** `C-nn | decision | why | what it costs us`. Open questions live in §3 and get
promoted to §2 once someone answers. If you change a decision, edit the row and note the date;
do not add a second row saying the opposite.

**Gate C owns:** the generated Modelica compiles and simulates. It is binary, it is checked
live on a judge-supplied spec, and it is the one thing in this repo that cannot degrade
gracefully.

---

## 1. Verified environment (2026-09-24)

Reproduced from a clean venv on the second dev machine, so these are facts, not claims.

| | |
|:--|:--|
| OpenModelica | v1.26.3 (64-bit), winget `OpenModelica.OpenModelica.Official` |
| Install path | `C:\Program Files\OpenModelica1.26.3-64bit\bin` — note the version is **in the folder name** |
| MSL | 4.1.0 (auto-installs from `share/omlibrary/cache` on first `loadModel`) |
| Catalog harvest | **1,402 classes**, ~200 s (1,529 before C-07 dropped 127 partials) |
| `pytest -m slow` (the gate) | **2 passed**, 108 s |
| `pytest` (fast) | 21 passed, 1 failed — **not ours**, see §4 |
| Full pipeline `--provider none` | runs end to end, **HARD GATE MET**, 11/12 acceptance |

Pin the OpenModelica version in the README. Four machines on three versions is how the
compile gate dies at demo time, and a version mismatch also invalidates the catalog (C-02).

---

## 2. Decisions taken

### Generation

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| **C-01** | Tier 1 emits a **causal directed-flow abstraction** (`SpecAlive.Interfaces.Outlet/Suction/Discharge/Inlet`), not `Modelica.Fluid` | No pressure network means no nonlinear algebraic systems, so generated models integrate reliably. The packet itself warns the acausal variant stalls at pump start (REQ-MOD-003) | REQ-MOD-004/005/006 have **no numerical effect** in Tier 1. Declared as OPEN-ISSUE-04, never hidden. C-09 is the fix |
| **C-02** | The harvested catalog is **regenerated per machine and never committed** | It must match the MSL actually installed. A catalog built against 4.1.0 and used on 4.0.0 names classes that do not exist there — which breaks the single guarantee the whole design rests on | 200 s setup per machine. `specalive doctor` prompts for it |
| **C-03** | Bind **before** emitting, and only to a class the catalog verified exists with parameters it verified it has | Makes wrong class paths, invented parameters and mismatched connectors *structurally impossible* rather than merely unlikely | The harvest step, and the emitter cannot improvise |
| **C-04** | Ports carry both an IR **id** and a Modelica **connector name** | The id is a stable handle; the name is what the bound class actually calls the connector | The emitter must resolve one to the other. We already shipped this bug once (`B1.out not found in scope Plant`) |

### C-08 — the Modelica is generated **from the SysML**, not in parallel with it

**Decided. This supersedes PLAN.md §3, which shows IR → {SysML, Modelica} as two parallel
emitters.** The new chain is:

```
IR  ──►  SysML v2  ──►  Modelica
         (B owns)       (C owns)
```

**Why.** The briefing's outcome ladder puts the top band at *"Modelica **derived from** the
SysML, correspondence shown."* Parallel emission from a shared IR is defensible against
divergence, but it is not literally a derivation, and a judge can ask us to show one. Under
C-08 the derivation is the code path, so the answer is a demo rather than an argument.

**Why it is feasible.** The emitted SysML already carries nearly everything the Modelica
emitter needs: part defs and part usages, `port def`, `interface … connect … to …`,
attributes, the full `state def` with `parallel` regions and guarded transitions, and
`allocation … to Modelica::<class>; // tier L1` naming the bound class and its tier.

**The work.** `parse_back()` today recovers only *names* — sets of strings, enough for the
round-trip check and nothing more. It has to become a real reader returning a typed
`SysMLModel` carrying attribute values, guard expressions, modifiers and scan period. Then
`emit_modelica` consumes that instead of `SystemModel`, with the IR retained only for
provenance.

**Two things fall out for free:** the derivation becomes literal, and `round_trip_check` stops
being a name check and becomes a genuine structural gate — if the SysML loses something, the
Modelica cannot be built from it, so we find out immediately instead of at review.

**Risk management, and this part is not negotiable.** This puts a new parser directly in front
of the hard gate, and standing rule 6 says the gate is sacred. So it lands behind
`--from-sysml`, with the IR path kept as the default and the fallback, until the SysML path is
green on the bench. It becomes the demo path only once it is. That is a sequencing
constraint, not a hedge against C-08 itself.

### C-08 audit — what the emitted SysML actually carries

Done against `out/nacl/NaClEvaporationPlant.sysml` (618 lines) by enumerating every field
`ModelicaEmitter` reads from `SystemModel` and looking for it. Four verdicts: **OK** (real
syntax, parser just reads it), **COMMENT** (present but as a `//`, so it is a contract we have
to freeze), **LOSSY** (present but mangled beyond unambiguous recovery), **ABSENT**.

| Field the Modelica emitter needs | Carried as | Verdict |
|:--|:--|:--|
| block id, kind, description | `part B1 : tank { doc /* … */ }` | OK |
| block parameters → Modelica modifiers | `attribute redefines area = 0.07; // m2` | OK |
| `modelica_class` | `allocation B1_impl allocate B1 to Modelica::SpecAlive.Vessels.Reservoir` | OK |
| connections | `interface C_L_V8_a connect B1.out to L_V8.port_a;` | OK *(but see D-1)* |
| states, regions, transitions, guards | `transition T1 first Step1 if LIS_301 >= SP_B3_LVL_WATER then Step2;` | OK |
| acceptance checks | `verification def BAT09_01 { attribute expression : String default "…"; }` | OK |
| signal name + datatype | `attribute LIS_301 : Real;` | OK |
| `binding_tier` | `// tier L1` | COMMENT |
| `Connection.series_elements` | `// @series V8` | COMMENT |
| `Signal.role` (sensor/actuator) | `// sensor` | COMMENT |
| `Signal.binding` | `// bound to B3.level` | COMMENT |
| **interlocks** | `// @interlock permissive on cmd_heater: …` | COMMENT |
| state action values | `do action set_cmd_V8 { /* cmd_V8 := true */ }` — name real, value in comment | COMMENT |
| `provenance.requirement_ids` | `// @trace satisfies REQ_THM_001` (was `REQ-THM-001`) | COMMENT + LOSSY |
| **port name vs port id** | see D-1 below | **BROKEN** |
| `StateMachine.scan_period` | — | ABSENT |
| `Scenario.stop_time / interval / tolerance / solver` | — | ABSENT |

**Verdict: C-08 is feasible, and the audit was worth doing first — it found a live defect.**

#### D-1 · The SysML connects ports it never declares *(defect, independent of C-08)*

`_emit_part_defs` declares ports using `_ident(p.name)`; `_emit_connection` references them
using `_ident(p.id)`. For the 15 ports in the reference IR where `id != name`, those are
different strings:

```
part def tank {
    port inlet_1_  : FluidInPort;      <-- declared from p.name "inlet[1]"
    port outlet_1_ : FluidOutPort;
}
...
interface C_L_V8_a connect B1.out to L_V8.port_a;   <-- references p.id "out"
```

`B1.out` is not a declared port of `tank`. The SysML is internally inconsistent today and
would fail validation in a real SysML v2 tool. `round_trip_check` does not catch it because it
renders the expected pair with the same id-based function it is checking against.

This is C-04 resurfacing one layer up, and it is a **hard blocker for C-08**: a reader cannot
resolve `B1.out` to a Modelica connector, because the mapping `out → outlet[1]` exists only in
the IR.

It is also **LOSSY in the other direction**: `_ident("inlet[1]")` → `inlet_1_`, and
`inlet_1_` cannot be mapped back to `inlet[1]` unambiguously — a component could legitimately
have a connector called `inlet_1_`. So even fixing the id/name confusion is not enough; the
subscript has to survive.

**What C needs from B** (→ `Decisions/B.md`), in priority order:

1. **Fix D-1.** Declare and reference the *same* thing. My suggestion: declare ports by IR
   **id** (stable, already what interfaces use) and carry the Modelica connector name
   explicitly, e.g. `port out : FluidOutPort; // @connector outlet[1]`. That keeps the SysML
   self-consistent and makes the id→name mapping recoverable. Worth fixing on its own merits
   even if C-08 slipped.
2. **Freeze the COMMENT forms** listed above, or promote them to real syntax. Seven fields ride
   in comments and four of them are load-bearing: `// @series`, `// sensor`, `// bound to` and
   `// @interlock`. The interlocks are the ones that worry me — they carry REQ-SAF-001/003/004/005,
   and a reader that misses them produces a model with the **safety interlocks silently
   removed**, which compiles and simulates perfectly.
3. **Decide where ABSENT fields live.** `scan_period`, `stop_time`, `tolerance`, `solver` are
   simulation concerns, not system-model ones, so I am happy for these to stay on the IR side
   and be passed to the emitter separately — but that must be a stated decision, not an
   accident, or C-08 is not a clean derivation.
4. **Reader ownership.** It belongs next to your emitter, since they change together. Tell me
   if you want it; otherwise I write it and you review.
5. Once C-08 lands, an emitter change that drops a field breaks the Modelica build. Emitter
   changes want a test.

### Repair

| # | Decision | Why | Cost we accepted |
|:--|:--|:--|:--|
| **C-05** | **Deterministic fixers run first**; a model is called only for semantic failures | Most Modelica errors are mechanical, and mechanical errors should be fixed by code, not tokens. This is what makes free/local models sufficient | A fixer library to maintain. Worth it: every fixer is an LLM call we never make |
| **C-06** | Repair loop is **keep-best-so-far and bounded at 6** | A patch that raises the error count is discarded, never applied. Better to stop and declare a gap than thrash or burn quota | May stop before fixing everything — and says so, loudly |
| **C-07** | Partial classes are excluded from the catalog using **omc's `isPartial()`**, at emit time only | Name heuristics caught **0 of the 127** partial classes actually present. A partial class cannot be instantiated, so binding to one is an unconditional build failure — and `checkModel` does not catch it (see below), so it escapes the repair loop and detonates at simulate | One extra omc call per class in the probe; no measurable harvest slowdown (1402 classes, same ~200 s) |

**C-07 detail, because the failure mode is non-obvious.** Binding a partial class produces
this, and only at build time:

```
$ checkModel(PartialBind)
Check of PartialBind completed successfully.
Class PartialBind has 5 equation(s) and 6 variable(s).   <-- unbalanced, but NOT an error

$ simulate(PartialBind)
Error: Component 'wall' has partial type 'Element1D'.
messages = "Failed to build model: PartialBind"
```

The repair loop gates on `check()`, which **passes**. So this class of defect bypasses repair
entirely and surfaces at the last stage, which on demo day is the worst possible place. The
catalog promise in C-03 is "only classes that exist *and can be used*"; before C-07 the second
half was not true for 127 of 1,529 entries.

---

## 3. Open questions — need an answer from another workstream

*C-Q1 was here. It is now a decision — see **C-08** in §2.*

### C-Q2 → **D** · Which router tier do I target, and can `nomic-embed-text` be prioritised?

**Upgraded from a question to a request after the C-07 measurement.** Nothing in `llm/` has met
a live endpoint yet — no Ollama binary and no keys on either dev machine, so all six tiers
report `down` in `doctor`. I can write and test the call sites against a fake router returning
canned JSON, but I cannot verify escalation behaviour.

Retrieval is 5/10 top-1 on full MSL and no deterministic fix will move it (see §5), so
`t1_local_embed` is now the single highest-value tier for C. If only one thing gets stood up
before the freeze, make it that one — it is a local embedding model, needs no API key and no
quota, and it is the cheapest of the six to run.

If the answer is "none before the freeze", say so plainly and I will ship with model calls
disabled, the tier table declared as L0/L1 only, and the retrieval number stated as measured.
That is an honest result, not a failure — but we should choose it deliberately rather than
discover it on day three.

### C-Q3 → **everyone** · PLAN.md backlog C1 says "Commit it"; D26 says never commit it

Direct contradiction about `out/catalog.jsonl`. **D26 is right** (see C-02) and PLAN.md's
trailing instruction should be struck. Flagging rather than silently editing someone else's
plan. `.gitignore` already excludes `out/`, so the current behaviour is correct.

---

## 4. Notes for other workstreams

**→ A:** `test_every_file_in_the_packet_parses` fails on this machine. A newer
`pdfplumber`/`pdfminer.six` throws `Unexpected EOF` on `13_water_nacl_medium_notes.pdf` and
`09_batch_acceptance_test.pdf`; the `pypdf` fallback then succeeds, so ingestion is fine and
the assertion (zero adapter warnings) is what fails. Environment drift, not a regression —
but decide whether to pin the dependency or relax the assertion to "no *unrecovered*
warnings", because right now a clean clone looks broken.

**→ D:** the one failing acceptance check is `BAT09-04: B5.level never crossed 0.18, extreme
reached was 0.1431`. That is OPEN-ISSUE-01 behaving exactly as designed. It must stay failing,
and the report must say *why* it is failing, or we lose the honesty points it exists to earn.

---

## 5. Backlog — C's ordering, and why

Reordered from PLAN.md §10 to put the LLM-dependent work last, because four of the six items
need no model at all and the LLM tier is the one genuine gap (C-Q2).

| | Item | Needs a model? |
|:--|:--|:--|
| ✅ | ~~**C7** exclude partial classes via `isPartial()`~~ — **done**, see C-07 | no |
| 1 | **C8** SysML → Modelica reader behind `--from-sysml` (C-08) | no |
| 2 | **C2** embeddings in retrieval — **promoted, see below** | yes (`nomic-embed-text`) |
| 3 | **C5** more deterministic fixers, mined from real `omc` output | no |
| 4 | **C3** L1 templates for rotational / thermal / electrical — unblocks the drivetrain bench, which is our generality proof | no |
| 5 | **C4** L2 synthesis — write the connector-balance check now, wire the prompt when a tier is live | yes |
| 6 | **C6** Tier-2 acausal `Modelica.Fluid` + WaterNaCl, shipped with the pump-start defect documented | no |

### Retrieval: measured, and worse than STATUS.md records

I claimed here yesterday that C7 might make embeddings a skippable refinement. **That was
wrong, and the measurement says so.** `scripts/retrieval_probe.py` is now the repeatable
scoreboard — the eight STATUS.md queries plus the two from PLAN.md's C2 note.

| | top-1 | partial classes in catalog |
|:--|:--|:--|
| pre-C7 (1,529 classes) | **5/10** | 127 |
| post-C7 (1,402 classes) | **5/10** | 0 |

C7 moved **no query into first place**. It was never going to: `TLine`, `Mass` and
`MultiStarResistance` are ordinary instantiable classes, not partials. What C7 fixed is a
correctness hole (C-07), not ranking.

The misses that remain are plain BM25 failures on a 1,402-class corpus:

```
'gearbox with fixed transmission ratio'  -> Electrical.Analog.Lines.TLine   (Gearbox rank 4)
'flywheel rotating mass ...'             -> Translational.Components.Mass   (Inertia rank 4)
'electrical resistance element'          -> Polyphase.MultiStarResistance   (Resistor >5)
'heat conduction through a wall'         -> Fluid.Pipes.DynamicPipe.HeatTransfer   (>5)
'thermal conduction between two ports'   -> Analog.Basic.Transformer        (>5)
```

**Where STATUS.md's 7/8 came from:** almost certainly the 239-class subset PLAN.md mentions
under C1. BM25 degrades sharply at full-MSL scale — `TLine` outranking `Gearbox` is lexical
noise, nothing to do with partials. STATUS.md §2.3 needs correcting; I have not edited it
because it is a shared file and the number is D's to re-state.

**Consequence, and it is a real one: C2 moves from refinement to dependency**, and with it
D's `ollama pull nomic-embed-text` (backlog D1) moves onto C's critical path. Two of the five
misses have the right answer at rank 4, which is exactly what an embedding rerank or the LLM
picker is for; three are outside the top 5, where retrieval has to improve before a picker
can help at all.

**Fallback if no tier is live before the freeze:** hand-written `aliases` on the entries the
bench packets actually need. Cheap, deterministic, but case-specific — it buys the demo and
costs us the generalisation argument, so it is the last resort, not the plan.
