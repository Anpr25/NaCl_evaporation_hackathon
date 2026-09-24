# D — platform, verification, proof

**Owns:** `src/specalive/llm/` · `src/specalive/verify/` · `src/specalive/web/` ·
`src/specalive/cli.py` · `src/specalive/settings.py` · `benchmarks/`
**Gate:** nothing breaks, and we can show it.

Newest entry at the top. Anything under **⚠ Affects you** is a change other people need to
know about; everything else is FYI.

---

## 2026-09-24 (latest) — rules 6.2/6.3 compliance: assumptions and questions are first-class

Read the input-handling rules against what we actually do. Two of the three clauses were
already met; one was not, and the fix turned out to be worth more than compliance.

**Where we stood.** Contradictions were flagged with a precedence rule id and a rationale
(6.3b, met). Nothing reached the output without provenance — zero blocks with an empty
provenance record (6.3c, met). But 6.3a says missing information must be *"inferred with a
stated assumption, or surfaced as a question"*, and we had neither concept: everything was an
undifferentiated `Gap`, the report had no questions section at all, and an inference made
during emission was a source comment nobody reads.

**What changed.**

| | |
|:--|:--|
| `ir/evidence.py` | new `Assumption` and `Question` records, separate from `Gap` on purpose — a gap is something we could not do, an assumption is something we *did* on our own authority |
| `config/assumptions.yaml` | **the register**: five named conventions (SA-01..SA-05), each with `applies_when`, `rule`, `basis`, `challenge`, `risk` |
| `ir/assumptions.py` | `AssumptionLog`. `assume()` **raises** on a basis that is not in the register, so a convention cannot be invented at the call site to excuse whatever the code just did |
| `verify/diagnose.py` | classifies every red check: `unreachable` (plateaued short — the spec contradicts itself), `stalled` (never moved — a knock-on), `unsettled` (stop time too short) |
| `verify/report.py` | *Questions for the customer* and *Stated assumptions* sections, ahead of the gaps table, plus two gate cards |

**The register is the part that matters.** An entry is written *before* the code that spends
it, and is domain-general — if you cannot state it without naming this week's packet, it is
not a standard assumption. `basis: null` is still allowed, because forbidding it just pushes
people back to guessing silently; it is counted instead, as `assumptions_unfounded`, and the
report prints that number whether or not it flatters us. It is currently **0**.

**Two things fell out of it that are not compliance.**

1. The unreachable-guard diagnosis makes the autonomous run rediscover **OPEN-ISSUE-01** on
   its own, from the trace rather than from static analysis: *"B5.level settled at 0.1476
   against a required 0.18, having travelled 0.1426 of the 0.175 needed (18.5% short) and
   then stopped changing."* Static reachability never caught this — it needed upstream
   geometry the extractor does not find. A plateau needs no such inference.
2. It also separates root cause from noise. Seven checks were red; **two** are real
   contradictions and **five** are downstream of them. Reporting seven would have been as
   misleading as reporting none.

**Bug worth knowing about.** Every `AssumptionLog` numbers from 1, and a run uses two
(emission, then diagnosis). `attach()` merged by id, so the second log's records looked like
duplicates and were dropped — losing both blocking questions about a contradiction the run
had just proved. It now renumbers and carries the assumption→question back-references
across. Tested, because a silent-drop bug in the honesty machinery is the worst kind.

**Still open, needs a call.** SA-05 is *registered but not implemented*: when a guard is
proved unreachable, we currently leave the sequence dead and report it. The register entry
describes the alternative — keep the customer's guard exactly as written and add a second,
clearly marked fallback transition — which is permissible under 6.3b because the
contradiction is flagged and the resolution is not arbitrary. It would take the autonomous
run from 3/10 to roughly 11/12. I have deliberately not done it without a decision, because
it edits the customer's control logic.

**Numbers.** 90 tests green (10 new). `bench`: drivetrain 7/7, nacl 11/12, hvac NO PACKET.
Autonomous run: compiles, simulates, 3/10, 6 stated assumptions (0 unfounded), 4 questions
(2 blocking).

---

## 2026-09-24 (later) — drivetrain bench green, screens generalised, plots in the report

**Status: D4, D5, D6 done.** 51/51 tests green. Two domains now pass end to end.

### ⚠ Affects you

**Everyone — we have a second domain, and it works.** `benchmarks/drivetrain/` is a geared
drive rig: constant torque -> motor inertia -> reduction gear -> load inertia -> damper ->
frame. It shares **nothing** with the NaCl packet:

| | NaCl | drivetrain |
|:--|:--|:--|
| domain | fluid + thermal | rotational mechanics |
| connectors | our causal stream ports | acausal `Flange_a`/`Flange_b` |
| controller | parallel-region state machine | none, continuous only |
| bindings | L1=15, L0=1 | **L0=6, L1=0** |

Every block binds straight to a harvested Modelica class. **7/7 acceptance checks pass, and
the steady state matches the analytic solution to 0.000%** (`w_load = ratio*tau/d =
5*2/0.8 = 12.5 rad/s`, simulated 12.500). The acceptance numbers are derived, not fitted.

That is the generality proof. The architecture is not NaCl-shaped.

It carries its own precedence trap in a different shape: the archived model says the gear
ratio is 4.0, approved change record CR-114 says 5.0. Same failure mode as CR-017, different
domain and different document types.

**B — the screens can now ask the IR questions.** `screen_reference(path, model)` takes an
optional `SystemModel`. If you add facts to the IR that a screen could use, tell me.

### What I did

**D6 — drivetrain bench.** Packet is five heterogeneous files (markdown datasheet, xlsx
parameter register, a change note, a legacy `.mo` with the stale ratio, a markdown acceptance
test), so it exercises multi-format ingest as well as the emitter.

**D4 — conservation screens generalised.** Was one solute check; now three, each opt-in by
what the trace actually contains:

| Screen | Asks |
|:--|:--|
| conserved species | during a concentration phase, does solute inventory stay put? |
| first-order spin-up | a constant torque into an inertia with linear damping cannot overshoot |
| energy direction | does a vessel warm while its cooler is commanded on? |

A trace with nothing screenable is reported as "neither endorsed nor rejected" — never as a
silent pass.

**D5 — plots in the report.** Inline SVG, hand-written, no matplotlib: the report has to stay
one self-contained file that survives being emailed, and it has to be readable in dark mode.
Acceptance thresholds are drawn as dashed lines **on the same axes as the signal**, so a
reader sees the criterion being met rather than trusting a PASS in a table. NaCl gets 6
panels / 8 thresholds at 56 KB; drivetrain 4 / 7 at 35 KB.

### Three bugs I made and fixed, worth knowing about

**A speed detector that matched a salt concentration.** My rotational screen used the pattern
`_w_`, which matches `B5_w_NaCl` — a NaCl mass fraction — and duly reported a chemical
composition as an impossible rotational overshoot. Patterns over column names are fragile;
the fix narrows to `[._]w$` and excludes anything that also looks chemical.

**A screen that skipped itself on our own data.** The spin-up check only applies when the
drive is constant, which I tested by looking at `torques[0]`. That happened to be `D1.tau`,
an internal flange torque that varies throughout a transient by definition, so the screen
quietly declined to run. Worse, the *real* answer was not in the trace at all: omc eliminates
`M1.tau` as an alias of a parameter. Fixed by asking the IR instead of the columns —
`_system_facts(model)` returns tri-state `constant_drive`, where `None` means "unknown, screen
decides for itself".

**Plots that ranked noise highest.** Filling panels by "how much does it move" surfaced
`der(J1.w)`, `J1.a`, `D1.flange_a.tau` — solver bookkeeping. Now the criteria decide what is
plotted, fillers are capped at two, and derivative/connector internals are excluded.

### Bench matrix

```
| Packet              | Compiles | Simulates | Acceptance | Verdict   | Domain          |
| drivetrain          | yes      | yes       | 7/7        | PASS      | rotational      |
| hvac_heat_exchanger | -        | -         | -          | NO PACKET | thermal + fluid |
| nacl_evaporation    | yes      | yes       | 11/12      | PASS      | fluid + control |
```

### Still open on D

| | |
|:--|:--|
| **D3** warm the replay cache | still blocked: the pipeline makes zero model calls with a reference IR. Unblocks when A1 lands. |
| **D6b** HVAC packet | the third domain. Lower value than the drivetrain — it is the near neighbour of NaCl — so it waits for the organisers' real packets. |
| CI | `specalive bench` is ready to wire up whenever we have somewhere to run it. |

---

## 2026-09-24 — local + cloud model tiers are live

**Status: D1 and D2 done.** 45/45 tests green, `specalive doctor` all green except the two
optional local models nobody has pulled.

### ⚠ Affects you

**1. `.env` was never being loaded.** `python-dotenv` was a declared dependency and nothing
called `load_dotenv()`. Keys sat in `.env`, the app could not see them, `doctor` said both
cloud tiers were down, and the router silently degraded to local-only. Nothing failed loudly.

Fixed in the new `src/specalive/settings.py`; `load_env()` now runs at CLI and web startup.
**If you add a new entry point, call `load_env()` before anything reads `os.getenv`.**

**2. The model names in `config/models.yaml` were stale.** `llama-3.3-70b-versatile` 404s on
a current Groq key. Verified against the live `/models` endpoints and updated:

| Tier | Now | Fallbacks |
|:--|:--|:--|
| `t3_cloud_reasoning` | `openai/gpt-oss-120b` | `qwen/qwen3.8-27b`, `openai/gpt-oss-20b` |
| `t4_cloud_vision` | `gemini-flash-latest` | `gemini-3.8-flash`, `gemini-3.5-flash` |
| `t1_local_small` | `qwen3:4b` | `qwen2.5:3b-instruct-q4_K_M`, `llama3.2:3b` |

`fallback_models` is now actually implemented — it was in the config and no provider read it.

**3. C — the catalog picker now answers by class name, not list index.** I changed
`PICK_SCHEMA` / `PICK_PROMPT` in `catalog/retrieve.py` and the validator in
`emit/modelica.py`. Measured reason: with an index, a 4B model falls back to `"0"` whenever
it is unsure, and that was two of its three errors. A name has to be copied from the list,
and a name that was never offered is detectable as a hallucination — an out-of-range index
is not always. Binding accuracy went 3/6 → 6/6. Shout if this cuts across anything of yours.

**4. A — your extraction prompt needs field descriptions, not just a schema.** This is the
single biggest quality lever I found, and it is free. See the numbers below.

### What is live

| | |
|:--|:--|
| Local | `qwen3:4b` + `nomic-embed-text`, **100%** on the task bake-off, **43 tok/s** |
| Groq | `openai/gpt-oss-120b`, 2.2 s for a conflict adjudication, correct |
| Gemini vision | read the P&ID: **10/10 equipment**, **15/15 automated valves**, 17 instruments |

### Findings worth your time

**Ollama leaves a third of a 4 GB card unused by default.**

| Config | GPU residency | Throughput |
|:--|:--|:--|
| default | 67% | 13.3 tok/s |
| `num_gpu: 99` | **100%**, 3.18 GB | **43.1 tok/s** |

A 3.2× speedup from one setting. Already in `config/models.yaml`. Lower it if your card is
smaller; `specalive models` prints the split.

**qwen3 is a reasoning model and that silently broke every structured call.** With thinking
on, `response` comes back as `""` and the whole answer lands in a separate `thinking` field.
The router would have escalated a tier on *every single call* and nobody would have noticed
except as a large cloud bill. Provider now sends `think: false`, with a fallback that
recovers JSON from `thinking` if the flag is ever missing.

**Our prompts were the accuracy bottleneck, not the models.** First real bake-off: qwen3 36%,
gemma3 55%. The failures were models writing whole clauses into a `value` field whose schema
said nothing but `"type": "string"`:

```
value 'to transfer B1 liquid to B3'  != 0.13
value 'Cooling complete temperature' != 20
```

| Fix | qwen3 | gemma3 |
|:--|--:|--:|
| Start | 36% | 55% |
| Per-field `description` + one worked example | 73% | 64% |
| Accept genuinely-ambiguous duplicates (benchmark bug) | 82% | 82% |
| Answer by class name, not list index | **100%** | 91% |

Not one model was swapped. **A: copy the pattern — every schema field gets a `description`,
and the prompt carries one worked example showing exactly what belongs in the tricky field.**

**My own benchmark was penalising correct answers.** MSL has character-identical
descriptions: `Spice3.Basic.C_Capacitor` and `Analog.Basic.Capacitor` are both "Ideal linear
electrical capacitor", word for word. I was grading one right and one wrong on an
unanswerable question. Three of six pick cases were like that. Ground truth now accepts any
identically-described candidate. *Worth checking whether your own eval has the same flaw.*

**503 overload is the most likely free-tier failure.** Observed live: `gemini-flash-latest`
was overloaded and the P&ID run only succeeded because it walked down to `gemini-3.5-flash`.
502/503/529 now falls through to the next model instead of failing the tier.

### New tests

`tests/test_router.py`, 23 tests, all offline and fast. Invalid JSON, schema violation,
validator rejection, retry-feedback content, dead daemon, mid-call disconnect, 429 quota
disabling a tier, declared rate limits, cache hit/miss/key-separation, replay on warm and
cold cache, total failure, the stats log, stale model names, overload fallback.

Two of them found the router behaving *better* than I had asserted: in replay mode a live
provider is never even constructed, so nothing can accidentally reach the network.

### Still open on D

| | |
|:--|:--|
| **D3** warm the replay cache | **blocked, in a good way** — with the reference IR the pipeline makes *zero* model calls, so there is nothing to warm. Unblocks when A1 lands. |
| **D4** charge/energy conservation screens | for the electrical and drivetrain benches |
| **D5** plots in the report | matplotlib → inline SVG |
| **D6** build the HVAC and drivetrain bench packets | needs the organisers' packets, or I synthesise them |

### How to use the tiers

```python
from specalive.llm.router import Router
resp = Router(mode="auto").run("extract_claim", prompt, schema=MY_SCHEMA)
resp.data     # parsed, schema-validated; raises rather than returning junk
```

Modes: `auto` (everything) · `local` (Ollama only) · `cloud` (Groq + Gemini) ·
`replay` (cache only, demo-safe) · `none` (deterministic only).

Add a `validator=` callable for domain rules — that is where "the class must exist in the
catalog" belongs. A tier that returns plausible-but-wrong output is worse than one that
fails loudly, so validate aggressively and let the router escalate.

---

## 2026-09-23 — scaffold handover

Baseline built and verified: hard gate passes, pipeline runs end to end, catalog harvested
(1,529 classes in 203 s), 24 tests green. See [STATUS.md](../STATUS.md) §2 for the evidence
table and §3 for the decision log.
