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

## 2026-09-25 (latest) — C6 done: OPEN-ISSUE-04 closed with numbers. C's list is finished.

**Status: implemented.** 105 fast tests, **9 slow** (gate + 7 new Tier-2 evidence tests), both
benches green. `modelica/SpecAliveFluid.mo` is a new file; nothing existing changed.

Tier 1 stays the default. This is not a replacement — it is the evidence that the three
requirements C-01 could only honour on paper are real in equations.

### The evidence, which is the point

| Requirement | Claim | Measured |
|:--|:--|:--|
| **REQ-MOD-004** regularized asymmetric port loss with hysteresis | the treatment is active, not decorative | `B3.ports_penetration[1]` goes **0.00100 → 1.00000**, and it switches at level **0.099–0.115** against a port at 0.100 m |
| **REQ-MOD-005** junction volumes | the junction is a state, not a pass-through | `J1.medium.p` solves 101325 → 117339 → 116608 Pa, distinct from both endpoints |
| **REQ-MOD-006** static head on non-horizontal pipes | gravity is in the momentum balance | Δp = **−12 907 Pa** against ρgΔz = 998 × 9.81 × (−1.32) = **−12 927 Pa**, 0.2% |
| calibration | fitted to evidence, not guessed | Step1 completes at **159 s**; the supplied trace runs it 20 s → 180 s |

258 equations / 258 variables, compiles, simulates.

### The counterexample that failed, and what replaced it

My first demonstration of REQ-MOD-005 was to shrink `ChargeLeg`'s junction towards zero and
show the solve degrade. **It made no difference** — 1.56 s against 1.38 s, which is noise.

The requirement says why, and I had not read it closely enough: it asks for a junction wherever
**multiple** pressure-drop-only elements can be isolated *simultaneously*. The charge leg has
one valve, and B1 upstream of the pipe carries a state, so the node is never orphaned.

The condition it actually protects against needs two isolating elements bracketing one node.
`Examples.IsolatedNode` / `IsolatedNodeNoJunction` is that pair, and the difference is
unambiguous — at exactly the instant both valves shut:

```
without the junction:  LOG_STDOUT | warning | The default linear solver fails, the fallback
                       solver with total pivoting is started at time 1.000000
with the junction:     (nothing)
```

Both runs still *complete*, because the fallback solver rescues them. That is precisely why it
is worth demonstrating rather than trusting: **the failure is silent unless someone reads the
log**, and on a plant with several isolating groups it is what turns into a stall.

### GAP-MEDIUM-01 — WaterNaCl is not reconstructible, and that is the finding

`13_water_nacl_medium_notes.pdf` specifies
`PartialMedium → PartialMixtureMedium → PartialMixtureTwoPhaseMedium → WaterNaCl`.
MSL 4.1.0 has no `PartialMixtureTwoPhaseMedium` — enumerating `Modelica.Media.Interfaces` gives
`PartialMixtureMedium` and `PartialTwoPhaseMedium` as separate branches. That alone is work,
not a blocker.

The blocker is that the same note says the coefficients are *"intentionally absent from this
benchmark evidence"* for four of the five required properties. Only viscosity is given in full,
so `Media.dynamicViscosity_WaterNaCl` implements it with the packet's coefficients verbatim,
and ρ(T,p,w), h(T,p,w), cp(T,w) and p_sat(T,w) are declared rather than invented. Making them
up would produce a model that compiles, simulates, and is wrong — standing rule 4.

**Consequence for REQ-MOD-003, stated plainly:** the pump-start convergence defect the packet
asks us to document **cannot be reproduced**, because reproducing it needs the medium that the
evidence deliberately withholds. We can document that it is reported, and that the acausal
topology it concerns now exists and runs on StandardWater. We cannot show the stall. Saying so
is the honest answer; a reproduction built on invented coefficients would prove nothing.

### ⚠ Affects you

**D — `SpecAliveFluid.mo` is deliberately NOT in `PipelineConfig.library_files`.** Tier 1
remains the only library the generated model loads, so every run stays as fast and as reliable
as before. Tier 2 is exercised by `pytest -m slow` and is a demo artefact, not a code path.
Worth a slide: it is the difference between claiming a requirement and measuring it.

**Everyone — C's backlog is now empty.** C1, C5, C6, C7, C8, C10 and C-AI-1..5 are done; C2 and
C3 were dropped on measurement. The highest-value work left anywhere is extraction recall — see
the C10 entry: `main=1/8` without a reference IR, and that number is A and B's to move.

---

## 2026-09-25 — C5 done: four more fixes that no longer cost a model call

**Status: implemented, not committed.** 105 fast tests green, gate green, both benches green.

```
                    before C5      after C5
no model at all        2/8           6/8
with the agent         5/8           7/8
```

Four of the eight faults moved out of the model's hands entirely, and the agent's own score
went up too — because it now spends its budget on the one thing left that is genuinely
semantic instead of on renames.

| Fault | Was | Now |
|:--|:--|:--|
| F02 renamed connector | model | **catalog** |
| F06 dropped semicolon | unfixed | **deterministic** |
| F07 unknown class | model | **catalog** |
| F08 wrong parameter | model | **catalog** |
| F04 partial type | gap | model, 3 iterations |
| F09 dropped connection | gap | gap — correctly |

F09 stays a gap and should: a deleted `connect()` leaves nothing to infer the intent from.

### A new fixer family: catalog-grounded

`CATALOG_FIXERS` run after the plain ones and take the harvested catalog as a third argument.
The reason they belong in code rather than a prompt: **the compiler names the thing it could
not find, and the catalog holds the verified list of what does exist.** A lookup against ground
truth is exact, free and offline; a model asked the same question can only recall the list,
which is the one thing it is worst at.

### Three things that did not work, and what replaced them

**Edit distance is the wrong instrument for renames.** `surfaceArea` and `area` score **0.53**
on difflib — below any cutoff worth trusting — yet one name contains the other and the intent
is unmistakable. `_closest` now tries exact-ignoring-case, then containment, then the ratio.
Checking containment first is what lets the cutoff stay strict instead of being lowered until
it starts producing wrong renames.

**Fuzzy matching cannot resolve a connector at all.** `nonexistent_port` resembles neither
`inlet` nor `outlet`; any similarity threshold either guesses or gives up. What works is
**type compatibility learned from the model's own working connects**: read the connector types
off both ends of every `connect()` that does compile, which gives the mating relation for
whatever domain this is, then intersect with the broken component's connectors. On the NaCl
plant that leaves exactly one candidate — `B1.outlet` — and it is not a guess. Nothing in the
fixer knows what a fluid is; the relation is read off the model. Documented limitation: it
needs at least one intact example of the pair, which is why the unit-test fixture has two
transfer legs rather than one.

**A correct fixer is useless if the loop never reaches its diagnostic.** `fix_missing_semicolon`
worked from the first attempt and F06 still failed, because omc words that error
`Missing token: SEMICOLON`, which matched no pattern and was classified `other` — **last** in
the repair priority. The loop kept picking an `undeclared` error that the missing semicolon
had *caused*. Everything after an unparseable line is a symptom, so `Missing token` is now
classified `syntax`, which sorts first. One word in a regex, and the fault went from unfixable
to fixed in one iteration.

### ⚠ Affects you

**D — `RepairStep.method` has a third value, `"catalog"`,** alongside `deterministic` and
`model`. Worth splitting out in the report: it is the tier that costs nothing and is not a
regex, and the three-way breakdown is a better architecture slide than a two-way one.

---

## 2026-09-24 — C10 done: the gate now says when a model runs but does nothing

**Status: implemented.** 99 fast tests green, gate green, both benches green.

The gate has three states now, not two:

```
with the fixture IR      226/262 variables moved (86%), controller A=3/3, B=5/5, main=8/8
                         HARD GATE MET - compiles, simulates and runs its sequence

without the fixture IR    21/268 variables moved (7%),  controller A=3/3, B=5/5, main=1/8
                         HARD GATE MET, BUT THE MODEL IS INERT
                           the controller did not finish its sequence (main stopped at 1 of 8)

drivetrain (no FSM)       37/37 variables moved (100%)
                         HARD GATE MET
```

### The test that works, and the two that do not

My first attempt screened for *movement* — did any variable change? It passed the failing run,
because 7% of variables do move and the controller does leave state 0. A did-anything check is
too weak for exactly the failure it was written to catch.

A percentage threshold would have worked on these two runs and is a magic number that means
nothing on an unseen packet.

What discriminates honestly is **sequence completion**: `liveness()` takes the IR, counts the
states in each region, and compares against the highest index the simulation reached.
`main=1/8` is unambiguous and explains itself in the message. When a model has no state
machine the test does not apply — the drivetrain is purely continuous and would fail any
sequence requirement while working perfectly.

### Why this is C's, and why it mattered

`compiles` and `simulates` is the PRD's hard gate and it is unchanged — `result.ok` still means
exactly that, and `--from-sysml`, the bench and the exit code all behave as before. What
changed is that the *report* no longer implies the model works when it only ran.

Printing `HARD GATE MET` above `0/10 acceptance checks passed` was the one place this repo
read as a silent pass, and standing rule 4 says a declared gap beats that. A judge supplies a
spec; there is no reference IR for it; this is the message they would have seen.

### ⚠ Affects you

**A and B — this is a reporting fix, not a cure.** The root cause is extraction recall: 83%
overall, but the missing 17% includes `cmd_heater`, `cmd_coolB6`, `cmd_coolB7` and four
`Bn.out -> L_Vn.port_a` connections. No heater command, no evaporation, so `main` never leaves
Step1. Recovering those four signals is probably the highest-value work left anywhere on the
project — it is the difference between 0/10 and something defensible on a judge's packet.
`main=N/8` is now a one-line progress meter for it.

**D — `gate` carries two new keys**, `live` (bool) and `liveness` (string), already passed to
`build_report`. Worth surfacing in `report.html` next to the compile/simulate badges.

---

## 2026-09-24 (earlier) — what is left in C, and what I propose we drop

**Two tasks measured their way off the list, two stay, one is new and urgent.**

### ⚠ The finding that matters most — for everyone, not just C

The pipeline now runs **without `--reference-ir`** and reports `HARD GATE MET`. That is true
and it is hollow:

```
specalive run <packet> --provider none            (no fixture IR)
  ok   modelica  L0=9, L1=6
  ok   compile   + simulate
  HARD GATE MET
  warn verify    0/10 acceptance checks passed     <- nothing actually happens
```

83% IR recall is enough to build a model that compiles and **not** enough to build one that
runs a batch. The missing 17% is load-bearing: `cmd_heater`, `cmd_coolB6`, `cmd_coolB7` and
four `Bn.out -> L_Vn.port_a` connections. No heater command means no evaporation, so every
threshold check fails.

With the fixture IR it is 11/12. Without it, 0/10.

**This is a demo risk, not a scoring detail.** A judge supplies a spec; we will not have a
reference IR for it. And "HARD GATE MET" printed above "0/10" is the one thing in this repo
that currently reads as a silent pass. C owns the gate's meaning, so I am taking it.

### Dropping C2 (embeddings) — measured, not assumed

Binding is **identical** with the picker live and with it off, on both packets:

| | BM25 only | picker live (Groq) |
|:--|:--|:--|
| NaCl, no fixture IR | L0=9, L1=6 | L0=9, L1=6 |
| drivetrain | L0=6 | L0=6 |

The 5/10 I measured earlier was on hand-written *probe* queries, not on blocks the pipeline
actually binds. On real blocks BM25 and the picker agree every time. Embeddings would also
need Ollama, which is not on this machine. **Unproven value, real cost — dropped.**
`scripts/retrieval_probe.py` stays as the scoreboard if anyone wants to revisit it.

### Dropping C3 (L1 templates for rotational / thermal / electrical)

The drivetrain binds **6 of 6 at L0**, straight to harvested MSL classes. The templates were
insurance against catalog gaps in those domains and the gap has not appeared. Writing them now
would be work whose only evidence is that it might help on a packet we have not seen — and the
L0→L1→L2 cascade already degrades safely if it does. **Dropped.**

### What stays

| # | Task | Why it stays |
|:--|:--|:--|
| **C10** | Make the gate honest: a model that compiles but does nothing must not read as a pass | The 0/10 finding above. Highest priority in C |
| **C5** | More deterministic fixers, aimed at the three faults still reaching the model | Each one is a model call never made — the thesis, literally. And the fault matrix names the targets |
| **C6** | Tier-2 acausal `Modelica.Fluid` + WaterNaCl | Stretch. Closes OPEN-ISSUE-03 and -04, and REQ-MOD-003 explicitly asks for the pump-start defect to be documented. A working prototype already exists |

---

## 2026-09-24 (earlier) — C-AI-1..5 built and measured, plus a diagram layout

**Status: implemented.** Groq is live (`t3_cloud_reasoning: up, openai/gpt-oss-120b`).
94 fast tests green, gate green, both benches green.

### The headline number

`specalive faults` breaks a working model in eight documented ways and measures what comes back:

```
deterministic only   2/8 recovered,  6 declared as gaps
with the agent       5/8 recovered,  3 declared as gaps
```

Reproduce:
```
specalive faults out/diagram/GeneratedPlant.mo -m GeneratedPlant.BAT09 --stop-time 50 --provider none
specalive faults out/diagram/GeneratedPlant.mo -m GeneratedPlant.BAT09 --stop-time 50 --provider cloud
```

The three that stay gaps are the right answer, not a shortfall. A deleted `connect()` and a
component bound to a partial class have no correct *local* edit — inventing one would put a
plausible, wrong model in front of an engineer, which standing rule 4 exists to prevent.

### What changed

**C-AI-1 · the simulate gate.** `RepairLoop` gated on `checkModel`; the pipeline never passed
a stop time, so the simulate branch was dead code. Now the gate is `check` **then**
`build + simulate`, and the candidate probe uses the same bar — otherwise a patch that fixes
`check` while breaking the build gets accepted and the loop congratulates itself on a model
that does not run. Visible in the matrix: F04 reported `undetected` before, `build` after.
Two new deterministic fixers for this stage: `fix_partial_type_binding` (C-07's failure, no
valid local fix, so it removes the component and declares a gap) and
`fix_missing_initial_condition`.

**C-AI-2 · the loop is now an agent.** Three additions:
- *Diagnose before editing.* `diagnosis` and `strategy` are required schema fields, ordered
  ahead of `replacements`. The compiler points at the symptom; the cause is often three lines
  above. Real output: `"The class name SpecAlive.Vessels.Resevoir is misspelled"` → then the edit.
- *Memory.* Rejected attempts are fed back — `[rejected] renamed the port: errors 1 -> 3,
  discarded` — so the next pass refines instead of re-guessing. Also changed the rejection
  path from `break` to *continue with the rejection recorded*: keep-best still holds, but one
  bad guess no longer ends the run.
- *Tool use.* The agent may return `lookup: ["SpecAlive.Vessels.Reservoir"]` with no edit; the
  loop answers from the harvested catalog and asks again, bounded at one round. **Honest note:
  on these eight faults it never used it** — the model solved them from the window alone. The
  path is proven by test, not by the matrix.

**C-AI-3 · L2 with self-critique.** Was a `return None` stub. Now: generate equations inside a
skeleton we write (ports, connector types, parameters, class name are ours) → a second pass
criticises the draft against a fixed six-point checklist → revise → `omc` judges. Emitted into
the package under a banner saying which equations a model wrote.

**C-AI-4 · retrieval.** The picker is live via Groq and answers by class name, so a fabricated
answer is detectable. Embedding rerank still needs `nomic-embed-text`, which needs Ollama,
which is not on this machine.

**C-AI-5 · `specalive faults`.** The harness above. Eight faults, each a defect we have hit or
proved reachable. F01 reports `n/a` on our Tier-1 causal models because they have no `inner` —
left honest rather than tuned until it always fires.

**Diagram layout (not in the plan, added because a model you cannot look at is hard to review).**
The generated Modelica now carries `Placement` and `Line` annotations, so OMEdit draws a block
diagram instead of an empty canvas. Layout is derived from the connection graph, not from any
packet's coordinates, so it works on an unseen domain. A process plant is **not** a DAG — this
one recycles B6→B1 and B7→B2 — and both obvious ranking schemes collapse on that: relaxation
pushes every rank up together, Kahn never starts because nothing has indegree zero. Fixed by
stripping DFS back-edges from the *layout* graph only. Result is the real process order:
`cw → K1 → B6 → RET_A → B1 → V8 → B3 → V11 → B4 → V12 → B5 → V15 → B7 → RET_B → B2`.

### ⚠ Affects you

**D — the router got its first sustained real use and held up.** 28 cached responses across
the fault runs, schema validation clean, no escalation failures. `--provider replay` should
now reproduce a repair sequence offline; the cache is warm with something worth caching.

**Everyone — the default path is unchanged.** `--provider none` still runs the whole pipeline
and still meets the gate. AI is the fallback when deterministic work runs out, never the first
move. Both benches pass with no model calls at all.

---

## 2026-09-24 (earlier) — the agentic plan for C: making the `.mo` recover when it goes wrong

**Status: plan, not yet built.** `.env` created and loaded (`doctor` shows `Env file loaded`);
waiting on the Groq key. Everything below is C's AI surface and the order I propose to build it.

### The gap that matters most

**If the model compiles but fails to build or simulate, nothing is repaired at all.** The
pipeline gates repair on `omc checkModel`, and on a simulate failure it stops:

```python
if not sim.ok:
    yield from self._finish(t0, runner)   # <- pipeline.py: no repair, no retry
    return
```

That is exactly the class of failure C-07 already proved is real: binding a partial class
**passes** `checkModel` and dies at build with `Component 'wall' has partial type`. The same
is true of structurally singular systems, failed initialisation, division by zero at t=0 and
index-reduction failures — the errors where the *physics* is wrong rather than the syntax, and
precisely the ones a model is most useful on. Today they get no AI support whatsoever.

### The principle, and why this is agentic rather than decorative

> PRD §10: *"Planning, tool use, self-critique and multi-pass refinement are all in scope.
> Using an agent where a single call would do is not automatically better."*

So each AI touchpoint gets the **smallest shape that fits the problem**, and we should be able
to say why:

| Touchpoint | Shape | Why not more, why not less |
|:--|:--|:--|
| Catalog pick | **one call**, multiple choice | It *is* multiple choice. An agent loop here buys nothing and costs latency |
| L2 synthesis | **generate → critique → verify** | Free generation is the risky one; a critique pass is cheap next to a failed compile |
| Repair | **full agent loop** | The environment answers back. `omc` returns a different error after every patch, so the next action genuinely depends on the last result. That is the definition of an agent, and here it is justified |

The thing that makes an agent *safe* in this repo: **it never declares its own success.** `omc`
does. Every action is graded by a real compiler, so a confident wrong answer is caught by the
environment rather than believed.

### The degradation ladder — the whole story on one line

```
L0 catalog  →  L1 template  →  L2 synthesis  →  deterministic repair  →  agentic repair  →  declared gap
  grounded      grounded        AI + critique     code, no tokens         AI + omc loop      honest
```

Every rung is verified before the next is tried, and the last rung is *telling the user* rather
than guessing. "A declared gap beats a silent guess" is standing rule 4; this is it in code.

### Plan

**C-AI-1 · Close the simulate gap.** *Highest value; it is the literal answer to "what if
something goes south making the .mo".* Repair currently ends at `checkModel`. Extend it to a
two-stage gate — `check`, then `build + simulate` — and feed simulate-stage diagnostics into the
same loop. Add deterministic fixers for the cheap ones first (partial-type binding, missing
`fixed=true` on an initial condition, a zero denominator at t=0); the model handles the rest.

**C-AI-2 · Turn the repair loop into a real agent.** It is 70% there: observe (`omc`) → act
(patch) → verify (`omc`) → revise, bounded, keep-best. Three things missing, all of which are
what a judge means by "agentic":

- **Memory.** Each iteration currently starts blind. It should see its own rejected attempts
  and *why* they were rejected — "patch raised errors 1→3, discarded" — so it stops proposing
  the same fix twice. This is the cheapest of the three and probably the highest-value.
- **Tool use.** `catalog_note` is pre-baked into the prompt today. Let the agent *ask*:
  `catalog_lookup("SpecAlive.Vessels.Evaporator")` returns the verified parameter and connector
  list. The model stops guessing an API and starts querying ground truth — the same
  replace-a-guess-with-a-lookup move as C-07 and the D-1 residual.
- **Planning before patching.** One classification call that names the strategy, then execution.
  Only for errors the deterministic table does not recognise, so we never pay for planning on
  something a regex already fixes.

**C-AI-3 · L2 synthesis with self-critique (= C4).** The model writes *equations only*, inside a
skeleton whose ports, units and connector balance we fixed. Then a second pass criticises its
own output against connector balance and unit consistency before `omc` ever sees it. Cheap
relative to a failed compile, and it is "self-critique" literally.

**C-AI-4 · Retrieval escalation (= C2).** BM25 shortlist → embedding rerank → model picks *by
class name* (D already made it answer by name so a fabricated answer is detectable) → validated
against the catalog. Retrieval is 5/10 top-1 and two of the five misses sit at rank 4, which is
exactly the rerank-then-pick case.

**C-AI-5 · The evidence — a fault-injection harness.** This is the demo, and the number for the
deck. Take a known-good generated `.mo`, break it in N documented ways — delete an `inner`,
rename a connector, bind a partial class, remove an initial condition, introduce a discrete
algebraic loop — and measure recovery **with AI off vs on**. Two honest numbers, e.g.
"deterministic alone recovers 6/12; with the agent, 11/12; the twelfth is declared as a gap."
Fault injection also exercises the paths that never fire on a packet that happens to work, and
an untested fallback is not a fallback.

### ⚠ Affects you

**D — the router is about to get its first sustained real use, and `repair_modelica` is the
task chain it will hit** (`[t0_deterministic, t3_cloud_reasoning, t4_cloud_vision]`). Two asks:
the quota accounting should survive a 6-iteration loop without exhausting the tier mid-run, and
`--provider replay` needs to reproduce a repair sequence offline for the demo. C-AI-5's harness
is a good way to warm that cache with something worth caching.

**Everyone — nothing here changes the default path.** The gate is `--provider none` today and
stays that way. AI is the *fallback* when deterministic work runs out, never the first move.

---

## 2026-09-24 (earlier) — C8 done: the Modelica is now derived from the SysML

**Status: C-08 implemented and measured.** `specalive run … --from-sysml` re-reads the SysML
it just emitted and builds the Modelica from that text alone. Both benches pass on the new
path. Off by default; the IR path remains the fallback.

```
--from-sysml   nacl        L0=1 L1=15   compiles   simulates   11/12   HARD GATE MET
--from-sysml   drivetrain  L0=6         compiles   simulates    7/7    HARD GATE MET
```

**The measurement, which is the artefact worth showing.** Emit SysML from the IR, read it back
with no access to the IR, emit Modelica from what came back, and compare against the Modelica
the IR produces directly — through the *same* emitter, so any difference can only be a reader
loss:

| | |
|:--|:--|
| Structural differences | **0** — byte-identical once string literals are blanked |
| Differences that remain | 56 lines, all docstrings (see below) |
| Statements the reader could not parse | **0** of 759 lines |

That is "correspondence shown" as a test rather than an argument:
`tests/test_sysml_read.py::test_sysml_is_a_lossless_carrier_for_the_modelica`.

**New file only.** `emit/sysml_read.py`. B's `emit/sysml.py` is untouched — the reader re-uses
B's `_PATTERNS` and adds its own line splitter so trailing comments survive.

### ⚠ Affects you

**B — C8 found three defects in the emitted SysML. None of them are mine to fix.**

- **D-2 · twelve guard symbols are referenced but never declared.** Transitions say
  `if LIS_301 >= SP_B3_LVL_WATER then Step2`, and `SP_B3_LVL_WATER` — along with `SP_B3_COMP`,
  `SP_B3_EMPTY`, `SP_B5_BATCH`, `SP_B5_COMP`, `SP_B5_IDLE`, `SP_B6_COOL`, `SP_B7_COOL`,
  `SP_HEATER_LVL`, `SP_K1_CW`, `SP_PUMP_LVL`, `SP_RESTART` — appears nowhere as a declaration.
  `grep -c 'attribute SP_' → 0`. The SysML is not self-contained: a model built from it alone
  has guards over undeclared identifiers. Same defect *class* as D-1, one level up.
  Worked around by carrying them in `SimulationProfile`; the fix is `m.parameters` becoming
  system-level attributes.
- **D-3 · Python bool repr leaks into the SysML.** `attribute redefines useSupport = False;`
  — `False`, not `false`. Valid in neither SysML v2 nor Modelica. The IR path never sees it
  because `modelica_modifiers` carries the correct string `'false'`; only the round-trip does.
  **This is why the drivetrain did not compile on the SysML path until I normalised it.**
  Line 227 of `emit/sysml.py` interpolates `{q.value}` straight into an f-string.
  Related: the same parameter is declared `attribute useSupport : Real;` — a Boolean typed
  as Real.
- **D-1 residual · `_ident("inlet[1]")` → `inlet_1_` is not reversible.** Solved on C's side
  without touching your code, and I think the solution is better than a comment would have
  been: the allocation names the Modelica class, so the *catalog* is asked whether that class
  really has a connector called `inlet`. Guess replaced by a lookup against ground truth, the
  same move as C-07. No change needed from you unless you prefer to carry it explicitly.

**Everyone — what the SysML legitimately does not carry**, now enumerated in
`SimulationProfile`: scan period, stop time, interval, tolerance, solver, scenario id/name.
These are properties of a *simulation run*, not of a system; C.md item 3 said this had to be
a stated decision rather than an accident, so here it is stated. `parameters` also lives
there today, but only because of D-2, and it leaves once that is fixed.

**Cosmetic losses, declared rather than hidden.** 56 docstring differences, none reaching the
compiler: part defs share one `doc` per *kind*, so B4 inherits B1's "Charging tank"; signal
units are not emitted, so `input Real LIS_301 "m"` becomes `""`; state labels become state ids.

### Still open

- `--from-sysml` is not the default and should not become one until it has run on a packet
  nobody has seen. Standing rule 6.
- The fork survives only because it rides in `// fork -> Step12, Step7`. That comment is now
  load-bearing — if it changes shape the parallel split silently stops firing, the model still
  compiles, and the batch deadlocks after evaporation. There is a test pinning it.

---

## 2026-09-24 (later) — C's eight tasks, ordered; C7 done; C8 re-scoped after reading B

**Status:** C1 and C7 complete. C8 is smaller than the audit suggested, because B has already
built most of the reader. Two of C's three AI touchpoints are already wired and now have a
live tier to run against.

### ⚠ Affects you

**B — thank you, you fixed D-1 before I reported it.** `_port_ref` now resolves `p.id → p.name`
so declarations and references agree. One residual: `_ident("inlet[1]")` → `inlet_1_` is not
reversible, so a reader still cannot recover the Modelica connector name from the SysML alone.
Under C-08 that matters. Cheapest fix is to carry it explicitly —
`port out : FluidOutPort; // @connector outlet[1]`. Small ask, tell me if you would rather I did it.

**B — your `parse_back` is ~70% of the C8 reader and I would rather extend it than duplicate it.**
Your 26 patterns already *capture* the right groups; `ParsedSysML` just doesn't keep the
values. `redefine` captures name and value but stores neither; `transition` captures source,
guard and target but stores only the id; `allocation` captures the Modelica class but stores
only the block id. C8 adds retention plus a typed view. I will not change your patterns or
emitter without asking.

**D — STATUS.md §1 and §2.3 have two stale C numbers.** After C-07 the catalog is **1,402**
classes, not 1,529. And retrieval measured on full MSL is **5/10 top-1**, not 7/8 — the 7/8
looks to have come from the 239-class subset. `scripts/retrieval_probe.py` is the repeatable
scoreboard. Yours to restate, not mine.

**Everyone — `out/catalog.jsonl` must be rebuilt.** C-07 changed what the harvest emits. Run
`specalive harvest` again or your catalog still contains 127 uninstantiable classes.

### The eight tasks

| # | Task | State | Needs AI? | Blocked on |
|:--|:--|:--|:--|:--|
| C1 | Full MSL catalog harvest | **done** — 1,402 classes, ~200 s | no | — |
| C7 | Exclude partial classes via `isPartial()` | **done** — see C-07 | no | — |
| C8 | Modelica generated **from** the SysML (C-08) | **done** — both benches green | no | — |
| C2 | Embeddings in retrieval | ready to start | yes — `nomic-embed-text` | nothing, tier is live |
| C5 | More deterministic fixers | ready to start | no | — |
| C3 | L1 templates: rotational / thermal / electrical | ready to start | no | — |
| C4 | L2 synthesis (`_try_l2`) | stub | **yes** — the only unwritten AI path | a live tier |
| C6 | Tier-2 acausal `Modelica.Fluid` + WaterNaCl | **done** — OPEN-ISSUE-04 closed | no | — |

### C's three AI touchpoints

C is not AI-free, and two of the three are already wired — they were just never run, because
no tier was live:

| Touchpoint | Where | State |
|:--|:--|:--|
| **L0 catalog picker** | `Binder._try_l0` | wired; D made it answer by class name rather than list index, so a fabricated answer is detectable. Never exercised against a live model |
| **Repair, semantic branch** | `RepairLoop._attempt` | wired; 5 deterministic fixers run first, the model only sees what they cannot fix. Never exercised |
| **L2 equation synthesis** | `Binder._try_l2` | **stub — C4.** The one genuinely unwritten piece |

The thesis is *"ground the small model, don't grow the model"*, not *"avoid the model"*. Every
one of these gives the model a bounded multiple-choice or a minimal-diff task, never free
generation — and each is validated before anything reaches the IR or the emitter.

### Ordering, and why

1. **C8** — it is the top scoring band (*"Modelica derived from the SysML, correspondence
   shown"*) and it is cheaper than it looked. Behind `--from-sysml`; the IR path stays the
   default until the bench is green on it. Standing rule 6.
2. **C2** — retrieval is 5/10 and the embed tier is live. Re-measure with embeddings before
   assuming anything; the probe script makes that a one-liner.
3. **C4** — the last unwritten AI path, and the most defensible thing to demo: the model
   writes equations *only*, inside a skeleton whose ports, units and connector balance we fixed.
4. **C5** — every fixer added is a model call never made. Pure code, no dependencies.
5. **C3** — L1 templates. Lower priority than it looks: the drivetrain bench already binds
   **6/6 at L0**, so the catalog is covering rotational mechanics without templates.
6. **C6** — stretch. A working acausal prototype already exists (`../modelica/NaClEvap.mo`,
   built outside the repo): `OpenTank` with `use_portsData`, `ClosedVolume` junction,
   `StaticPipe` head, verified against the reference trace to 1 s. It closes OPEN-ISSUE-03
   and -04 if there is time.

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
