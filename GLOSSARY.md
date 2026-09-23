# SpecAlive — glossary and plain-English guide

Written for anyone joining the team who has not worked with Modelica, SysML or compilers
before. You do not need any of this to *use* the project, but you will hear all of it in
stand-ups.

[README.md](README.md) is how to run it · [PLAN.md](PLAN.md) is the architecture and who owns
what · [STATUS.md](STATUS.md) is where we are.

---

## 1. IR — "Intermediate Representation"

**One line:** a single clean description of the system that sits in the middle, so the messy
input side and the code-generating side never have to know about each other.

**Why it exists.** We read about ten input formats (PDF, Excel, Word, email, drawings…) and
produce two outputs (SysML, Modelica). Without a middle layer you would need a translator for
every combination — 10 × 2 = 20 of them. With a middle layer it is 10 in + 2 out = 12, and
each one is simple.

It is like currency exchange at an airport. There is no rupee→yen desk and no pound→yen desk.
Everything converts to dollars, then dollars convert to everything. **The IR is our dollars.**

**What is actually in it.** A plain structured record — literally a JSON file at `out/ir.json`:

> There is a **block** called B5. It has **ports** inlet, outlet, vapor. It has **parameters**:
> area = 0.06 m². It is **connected** to K1. It satisfies **requirement** REQ-THM-001. There
> is a **state machine** whose state Step6 has the **guard** `QIS_502 >= 0.18`.

**The important part: it is domain-neutral.** The IR has no idea what a "tank" is. It only
knows "a block with ports and parameters". That is deliberate, and it is why the same IR works
for a gearbox or a battery circuit. If the IR had a `Tank` class in it we would be rebuilding
everything the moment they hand us a drivetrain packet.

**Why the team cares:** the IR is the *contract*. Person A's job finishes when the IR is
filled in; B's and C's jobs start from it. Neither has to read the other's code. That is what
lets four people work at once instead of in a queue.

Defined in [`src/specalive/ir/system.py`](src/specalive/ir/system.py).

---

## 2. FSM and reachability

### FSM = Finite State Machine

A controller that is always in **exactly one** step, and moves on only when a condition is met.

A traffic light is the classic example: Red → Green → Amber → Red. It is never half-red. It
moves on a condition (a timer).

Our plant controller is the same idea, just longer:

```
Initial → Step1 (open V8, fill B3 with water)
        → Step2 (open V9, add brine)
        → Step3 (drain B3 into B4)
        → ...
```

The condition to move on is a **guard**. Step1's guard is `LIS_301 >= 0.13` — *stay here until
the level sensor in B3 reads 0.13 metres.*

**Parallel regions** means the machine runs two chains side by side (our plant cools B6 and B7
at the same time) and a **join** waits for both to finish.

### Reachability, sense 1: can you *get* to every state?

Draw the states as boxes and transitions as arrows, start at the beginning, follow the arrows.
Any box you can never land on is **unreachable** — dead code. Usually a typo or a missing
arrow. Our validator walks the graph and flags it.

### Reachability, sense 2: *guard* reachability — the interesting one

A state can be reachable on the diagram and still impossible in real life, because the guard
can never become true.

> *"Wait here until the bathtub has 100 litres in it."*
> But the only bucket you have holds 80 litres.

The doorway exists. You will just stand there forever.

**This is exactly the defect we found in the organisers' data.** Step5's guard is *wait until
B5 reaches 0.18 m*, but the mass balance says the most that can ever arrive from one batch is
about **0.145 m**. The plant would sit in Step5 forever.

Why it matters practically: without the check you would run the simulation, watch it hang, and
spend three hours hunting a bug **in your own code** — when the real problem is that two
numbers in the customer's spec contradict each other. `check_guard_reachability` catches it
*before* any code is generated and says so out loud.

Defined in [`src/specalive/ir/validate.py`](src/specalive/ir/validate.py).

---

## 3. omc, compile, simulate

### Modelica

A language for describing physical systems by writing **equations**, not instructions.

Normal programming is a recipe: *do this, then do that.* Modelica is a statement of truth:
*mass flowing in, minus mass flowing out, equals the rate of change of mass stored.* You
describe the physics; the tool works out how to solve it. Files end in `.mo`.

### omc = **O**pen**M**odelica **C**ompiler

The free tool that reads `.mo` files. Already installed here at
`C:\Program Files\OpenModelica1.26.3-64bit\bin\omc.exe`.

Three jobs, in order:

| Step | What it means | What ours prints |
|:--|:--|:--|
| **check** | Do these equations make sense together? Fast. | `249 equation(s) and 249 variable(s)` |
| **compile** | Turn the equations into a C program and build an `.exe`. Slower. | silence, or a pile of errors |
| **simulate** | Run it and produce numbers over time | `results.csv` |

People say "compile" loosely to mean all three.

### The one concept worth knowing: **balanced**

Equations must exactly equal unknowns. School algebra:

- 2 unknowns, 2 equations → one answer ✓
- 2 unknowns, 1 equation → infinitely many answers; omc refuses
- 2 unknowns, 3 equations → usually no answer; omc refuses

That is why the check prints `249 equations and 249 variables`. Those numbers matching is the
system saying *this is solvable*.

### Why it is called the "hard gate"

The hackathon rules say the Modelica **must compile**. Not "should". A beautiful SysML model
and a gorgeous report score **zero on that gate** if omc will not build the thing. So we run
`specalive gate` before every push, and two tests do a real compile-and-simulate.

Defined in [`src/specalive/verify/omc.py`](src/specalive/verify/omc.py).

---

## 4. Everything else, briefly

| Term | Plain meaning |
|:--|:--|
| **SysML v2** | A standard language for describing system architecture — parts, ports, connections, requirements. The "blueprint". |
| **The catalog / harvest** | We asked `omc` to list every component in the Modelica library — 1,529 of them — with settings and plug types. Like scraping a parts catalogue so we only ever order a part number that exists. |
| **L0 / L1 / L2** | Three ways to build a component, cheapest first. **L0** = off-the-shelf catalogue part. **L1** = one of our own reusable templates. **L2** = the AI writes the equations (last resort). |
| **Retrieval / BM25** | Searching that catalogue by plain description: "gearbox with fixed ratio" → `Rotational.Components.Gearbox`. BM25 is a classic keyword-ranking formula — no AI involved. |
| **Claim** | One fact pulled from one document, with a note of exactly where it came from (file, sheet, cell). We extracted 501. |
| **Provenance** | The paper trail. Every number in our output traces back to the exact cell it came from. |
| **Precedence** | The rulebook for "two documents disagree — who wins?" An approved change record beats an old email, always. |
| **Deterministic** | Plain code, no AI. Same input → same output, every time, free and instant. We use it wherever possible. |
| **The repair loop** | When omc rejects our code we fix it and retry, up to 6 times. Mechanical errors are fixed by code; only genuinely tricky ones reach the AI. |
| **Acceptance check** | One testable line from the customer's test document, e.g. *"B6 must cool to 20 °C before the pump starts."* We score 11/12. |
| **Hard gate** | The one pass/fail rule: the Modelica must compile. |
| **Router / tier** | The thing that decides *which* AI model answers a question — local 3B first, free cloud only if needed. |
| **Schema-constrained** | Forcing the model to reply in a fixed JSON shape, so it cannot ramble. The single biggest quality lever for small models. |

---

## 5. The commands

### `specalive doctor` — pre-flight check

One command that answers *"can this machine run the project, and if not, what exactly is
missing?"*

```
| Component            | Status    | Detail                            |
| OpenModelica         | found     | OpenModelica v1.26.3 (64-bit)     |
| Python               | ok        | 3.12.10                           |
| Modelica catalog     | built     | 1529 classes                      |
|   t1_local_small     | down      | qwen3:4b  (no key, or daemon…)    |
```

**Why it exists.** The project depends on things that live outside the repo — OpenModelica,
Ollama, two API keys, a generated catalog. On a teammate's laptop any of those can be missing,
and the failure otherwise shows up hours later as a confusing crash deep inside the pipeline.
`doctor` turns *"it crashed, no idea why"* into *"line 3 says the catalog is not built."*

Named after `brew doctor` and `flutter doctor`. It only reports; it never installs anything.
It exits with an error **only** if OpenModelica is missing, because nothing else matters
without it — everything else can be missing and you can still run `--provider none`.

**Use it:** first thing on a new machine, and first thing when someone says "it does not work
on mine".

### `specalive bench` — the generality proof

Runs the full pipeline on **every** benchmark packet and prints a matrix:

```
| Packet              | Compiles | Simulates | Acceptance | Verdict   | Domain          |
| drivetrain          | -        | -         | -          | NO PACKET | rotational      |
| hvac_heat_exchanger | -        | -         | -          | NO PACKET | thermal + fluid |
| nacl_evaporation    | yes      | yes       | 11/12      | PASS      | fluid + control |

2 of 3 benchmark(s) have no packet yet. Generality is not proven until they do.
```

**Why it exists.** At evaluation they hand us an **unknown domain**. We cannot test on that
packet. The next best thing is to test on several domains we did not design for and show the
pass rate. That table is the most persuasive slide we have for the AI-architecture score.

**Adding a packet:** drop files into `benchmarks/<name>/sources/` and write a small
`expectations.yaml`. No code changes.

**Two things it deliberately does:**

1. **An empty packet reports `NO PACKET`, never a pass.** An empty folder produces an empty
   model, and an empty model compiles perfectly. Before this was fixed the matrix showed three
   greens, two of which meant nothing. A meaningless green is worse than a red.

2. **It checks each packet against its own declared expectations:**

   ```yaml
   expect:
     compiles: true
     acceptance_min: 11
     acceptance_total: 12
     known_failures: [BAT09-04]   # the unreachable-guard defect
   ```

   | What changes | What bench says |
   |:--|:--|
   | Everything as expected | clean |
   | A new check fails | `unexpected acceptance failure BAT09-07` |
   | **A known failure starts passing** | `BAT09-04 was listed as a known failure but passed — confirm why` |
   | Compile breaks | `expected to compile, did not` |

   That third row is the subtle one. If BAT09-04 suddenly passes, it is **not automatically
   good news** — either we fixed the physics, or the check quietly stopped testing what it
   used to. Both need a human look.

### The rest

| Command | What it does |
|:--|:--|
| `specalive harvest` | Index the installed Modelica libraries into the catalog. Once per machine, ~200 s. |
| `specalive run <packet>` | The whole pipeline: evidence in, SysML + Modelica + results + report out. |
| `specalive gate <Model> <files>` | Just the hard gate. Fast feedback while hacking on Modelica by hand. |
| `specalive ir-diff a.json b.json` | Score an extracted IR against the hand-written reference. Turns "did extraction work?" into a number. |
| `specalive models` | Bench the installed local models on our real tasks and recommend one (see below). |
| `specalive serve` | The web app on :8000. |

### `specalive models` — pick a local model on evidence

Public leaderboards rank *general* ability. We do not need general ability. We need two narrow
things, and we can measure both:

1. **Extraction** — read a real sentence from the packet and fill a fixed JSON schema.
   Scored on: right value, right subject, **and the quote is genuinely from the text**. That
   last check is the one that catches a model inventing a plausible-sounding source.
2. **Catalog pick** — choose the right Modelica class out of eight candidates.

Ground truth is generated automatically — the query is a class's own description and the
correct answer is that class — so there is nothing to hand-label. The shortlist is **shuffled
with a fixed seed**, because otherwise the right answer is always first and a model could
score 100% by always replying "0". A benchmark a constant answer can win measures nothing.

```
$ specalive models

| Model                       | Fits 4GB | Extraction | Catalog pick | tok/s | Latency |
| qwen3:4b                    | yes      | 5/5        | 5/6          |    41 |    2.4s |
| qwen2.5:3b-instruct-q4_K_M  | yes      | 4/5        | 4/6          |    58 |    1.7s |
| qwen2.5:7b-instruct-q4_K_M  | no       | 5/5        | 6/6          |     9 |   11.2s |
```
*(illustrative shape — run it to get your own numbers)*

Note what that table makes visible: the 7B is the most accurate **and** the worst choice,
because it does not fit in VRAM and runs four times slower. For a workload of hundreds of
short batched extractions, fitting on the GPU beats parameter count.

---

## 6. The work split, in words you can say out loud

> **The big picture:** we are building a translation factory. Messy paperwork goes in one end,
> a working simulation comes out the other. Four of us own four stations on that line.

| | Nickname | What they do | Their one job |
|:--|:--|:--|:--|
| **A** | **The Reader** | Reads every document — PDFs, spreadsheets, emails, drawings — and writes each fact on an index card, noting exactly which page and cell it came from | *Any file type in → facts out* |
| **B** | **The Judge & Architect** | Takes the pile of cards. Where two disagree, decides which wins and writes down why. Builds one clean master description, then draws the SysML blueprint | *Facts in → one trustworthy blueprint out* |
| **C** | **The Engineer** | Turns the blueprint into real simulation code and makes it run | *Blueprint in → working simulation out* |
| **D** | **The Plumber & Presenter** | Provides the AI plumbing everyone uses, then checks the results and builds the report, the web app and the proof | *Nothing breaks, and we can show it* |

### One sentence each

- **A:** *"I turn documents into facts."*
- **B:** *"I turn facts into one agreed truth, and draw the blueprint."*
- **C:** *"I turn the blueprint into code that compiles and runs."*
- **D:** *"I make the AI cheap and reliable, and I prove the whole thing works."*

### The two things that make this work in parallel

**1. We agree the master description format in the first hour.** That is the IR. After that, A
does not need to know how C writes Modelica, and C does not need to know how A reads a PDF.
One hour of agreement buys three days of not waiting for each other.

**2. We hand-wrote a fake master description up front** — the **reference IR**. B, C and D can
start on day one without waiting for A to finish reading documents. It has a second use, which
is quietly the clever bit: once A's reader works, we compare what A extracted against the
hand-written version and get a **score**. "Did extraction work?" stops being an opinion.

### Who owns the risky part

**C does.** The hackathon has one hard rule — the Modelica must compile — and C owns it.
Everyone else's work is worth zero on that gate if C's is not done. That is also why it was
built first and proven to compile before anything else was written.

---

## 7. Person D in detail

D is the hardest role to describe because it is not one job, it is **four things nobody else
can do their job without**.

> **A, B and C build the product. D builds the things the product runs on, and the things that
> prove it works.**

### Job 1 — the AI plumbing (`llm/`), the big one

Everyone needs to call an AI model. Nobody else should have to think about *which* one. D
builds one function everybody calls:

```python
router.run("extract_claim", prompt, schema=...)
```

Behind that single line:

| Problem | What D's code does |
|:--|:--|
| Which model? | Tries the cheapest that can do the job — local first, free cloud only if needed |
| Model returns garbage | Validates against a schema; retries, then escalates to a bigger model |
| Free quota runs out | Notices, backs off, falls back to local |
| No internet | Falls back to local, then to plain code |
| Same question twice | Serves it from cache — free and instant |
| "How much did the AI actually do?" | Logs every call: which model, how many tokens, how long |

**Why it is not just plumbing:** our whole pitch is *"this runs on free and local models."*
D's layer is what makes that claim true rather than aspirational, and the call log is the
*evidence* — it lets us put a number on how little cloud we needed.

### Job 2 — checking the answers (`verify/`)

C's job ends at *it compiles and runs*. That is not the same as *it is right*. D turns each
line of the customer's test document into a machine-checkable expression:

> *"B6 must cool to 20 °C or below before the return pump starts"*
> → `crosses(B6.T, 293.15, falling)` → **PASS at t = 1630 s**

D also owns the **reference-data screen** — the check that caught the organisers' own trace
creating salt out of nowhere.

### Job 3 — the report and the web app

The report is one self-contained HTML file: gates, scorecard, traceability matrix, every
conflict and how it was resolved, and the honest gap list. **This is literally what the judges
read.** A correct system with an illegible report scores badly. The web app is the extra on
top: upload files, watch the pipeline run live.

### Job 4 — `doctor` and `bench`

The toolchain check and the generality proof (section 5 above).

### Why D is a separate role

**Shared infrastructure needs one owner.** If A, B and C each wrote their own AI-calling code
we would have three caches, three retry policies and three ways of failing.

**Someone has to own "does it actually work and can we show it?"** A, B and C are each deep in
their own stage and will each believe their part works. D is the one running the whole thing
end to end on a clean machine and saying "no it does not".

### If someone says D is support work

D owns roughly **half the judging rubric**:

- **AI architecture (30 pts)** — the tier router, caching, fallbacks, the call log
- **Product and design thinking (20 pts)** — `doctor`, `bench`, the report, the web app,
  degrading instead of crashing

C owns the hard gate. **D owns most of the score.**
