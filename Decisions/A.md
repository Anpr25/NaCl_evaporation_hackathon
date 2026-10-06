# A — Ingestion and evidence

**Owns:** `src/specalive/ingest/` · `src/specalive/extract/`
**Gate:** any file type → claims with accurate locators.

Newest entry at the top. Format for numbered decisions: `A-nn | decision | why | what it costs
us`, the same shape as [C.md](C.md).

---

## 2026-10-06 (latest) — this page, written after the fact

`A.md` was created empty in the first planning commit (`cbe9fa1`, 2026-09-23) and never filled
in. This page reconstructs workstream A's decisions from two sources, and cites a commit for each
one so it can be checked:

- **shreedhar_cctech's three commits** on `feature/ingestion-evidence` — `46843db`, `0d1b294`,
  `7fba7fe` — merged into `Dev-C` (`b40972e`) and from there into `main`;
- **decisions other workstreams later took inside A's files**, mostly on
  `modelling_improvement_Dev-D`, plus the rows of [STATUS.md §3](../STATUS.md) that touch
  extraction.

Written by Claude from the commit history, not by shreedhar. Where the history does not say *why*,
this page says so rather than inventing a reason. Corrections are welcome.

### Where A's checklist stands (PLAN.md §10)

| PLAN item | State | Evidence |
|:--|:--|:--|
| Model extraction path in `extract/claims.py` | **done** | `46843db` (A-01–A-03) |
| Vision path for `doc.images()` | **done**, including images embedded in `.docx` | `46843db`, `7fba7fe` (A-04) |
| Claim de-duplication across sources | **not built as an extraction pass.** Agreeing claims are counted at reconcile time by precedence rule P6 (corroboration); differing values still reach the reconciler as conflicts, as PLAN asked | `reconcile/precedence.py` |
| Per-claim authority, not per-file | **partly.** A row now carries its own status (A-10), but source classification is still the title-area heuristic (STATUS D17) | `47483f2` |
| Raise recall against the reference IR | last measured **83% overall** (topology 90%, series groups 100%, requirements 100%) | [B.md](B.md), D.md 2026-09-24 |

---

## 2026-10-01 → 2026-10-04 — extraction decisions taken on Dev-D, in A's files

Made by D (Anurag) while getting four new test packets (two-tank, IAQ ventilation, magnetic
circuit, NaCl) to compile and run. Each one came from a packet that extracted the wrong thing.

### A-07 | Extraction calls the cloud model first, with the local 3B underneath it | measured on four packets, the 3B missed facts that nothing downstream can recover — a part no claim mentions is a part the emitter is right to leave out | needs a key and free-tier quota; the local tiers stay in the chain, so `--provider local` and an offline machine still work

Route `extract_claim: [t4_cloud_extract, t1_local_small, t2_local_mid, t3_cloud_reasoning,
t3_openrouter]` in `config/models.yaml` (`4ca0763`). The "cheapest tier that can do the job" rule
still holds — the measurement just showed the cheapest tier could not do this job.

### A-08 | One whole-packet "skeleton" read, subordinate to the deterministic path (`extract/skeleton.py`, owner A/D) | no single chunk contains the system: a schedule names a room, a matrix in another sheet connects it to a duct, a note in a `.docx` says the duct is ideal, and on three of the four packets the deterministic path recovered none of that untabulated half | one large call per run, capped at 180,000 characters overall and 18,000 per document

Three rules keep it honest (`4ca0763`):
- every result is an `EvidenceClaim` with a verbatim quote, and a quote not found in the packet is
  dropped before it reaches the reconciler (A-01 again);
- its confidence is **0.5**, below the deterministic paths and below per-span text (0.6), so where
  a register already states a fact the register wins — this pass can only *add*;
- a Modelica class it suggests is checked against the harvested catalog and dropped if it does
  not exist.

### A-09 | Header vocabulary is fixed on evidence, one wrong packet at a time | every register invents its own column names, and a misread header silently turns a table into the wrong kind of fact | each rule is a small special case, so each one carries the packet that forced it

| Rule | The packet that forced it | Commit |
|:--|:--|:--|
| `start` and `end` are **not** synonyms for `from`/`to` | an occupancy schedule's *Start Time / End Time* columns produced twelve phantom components (`e_00_00`, `e_07_00` …) and twenty-one connections in a model with no real parts | `4ca0763` |
| a header ending in ` id` or ` no` is the id column | *Element ID*, *Interface ID*, *Component ID* — listing them one by one is a losing game | `4ca0763` |
| an exact synonym beats a fuzzy prefix, tried across every predicate first; `scope` is its own predicate | *Tag / Scope* matched `id` on its "tag " prefix, so a shared tank's name became the subject of every setpoint row and `TK_101` was misread as an external boundary (B's 2026-09-25 entry) | `8e325fa` |
| a header ending in ` value` is the value column | a calculations sheet headed *Input Value* contributed nothing, and the IAQ controller lost its bias and output limits | `adbf5ec` |

### A-10 | A claim carries its own row's status (`row_status`: effective / superseded), and superseded wins | source-level precedence cannot tell two rows of one register apart: the tank's high limit resolved to a superseded 0.78 m | a row marked *Approved* in one column and *Effective? No* in another counts as not in force — the conservative reading, by design

`_row_status()` reads the row's status-like columns (`status`, `effective`, `valid`, `current`);
`no`/`false` or a superseded word marks it superseded (`47483f2`). This is the per-row half of
PLAN's "per-claim authority" item; per-source classification is unchanged.

### A-11 | A name repeated with different scopes becomes separate subjects | *Low level limit | TK-101* and *Low level limit | TK-102* are two setpoints; keyed by name alone they competed in one precedence contest and one tank lost its limit | only repeated names are qualified (`Low level limit [TK-101]`), so a register whose names are already unique keeps exactly the subjects it had

`47483f2`.

### A-12 | The extracted claims are also written on their own, as `claims.json` plus `claims.schema.json` | the evidence trail was reachable only inside the full `ir.json` dump; a reviewer or another tool wanting just "what was asserted, from where, with what confidence" had to dig it out | none of note: `EvidenceClaim` (the frozen contract) is unchanged; this is a read-only consumer, and the schema is generated from the pydantic model so it cannot drift

`b135a04`. Listed in the CLI's artifact table, the web UI and the HTML report.

---

## 2026-09-25 — three review-flagged bugs: a crash, silent image corruption, an inverted precedence

shreedhar_cctech, `7fba7fe`. Each fix has a regression test, and each test was confirmed to fail
on the pre-fix code (via `git stash`), including the exact `ValidationError` from bug 1.

1. **An explicit `"kind": null` from the model crashed extraction and threw away every claim in
   the call, deterministic ones included.** Schema validation skips null-valued properties, so the
   null reached `EvidenceClaim`'s `Literal` field and raised outside the `LLMError` guard. Fixed
   with `c.get("kind") or "note"` — `.get(key, default)` only covers a *missing* key, not an
   explicit null — plus a `try/except` around claim construction as defence in depth. (An invented
   non-null kind such as `"widget"` still crashed without the second guard.)
2. **A transparent `.docx` diagram silently became a black rectangle.** `DocxAdapter` called
   `img.convert("RGB")`, which drops the alpha channel instead of compositing it. It now composites
   onto a white canvas first.
3. **A supersession written in an unfamiliar spelling inverted winner and loser.**
   `build_supersession_map` checked direction against an exact list of four spellings, so
   `is_superseded_by` or `replaced-by` fell through to the opposite branch — exactly the F1 trap
   the NaCl packet is built to catch. Replaced with a normalised substring check. The supersession
   prompt's predicate is also pinned to exactly `supersedes`.

### A-05 | One malformed claim never discards the batch it came in | a batch mixes deterministic and model claims, and losing all of them for one bad field is the worst possible failure mode for extraction | a malformed claim is skipped with a warning rather than surfaced as an error

Generalises the per-claim quote check of A-01 to every way a single claim can be malformed.

---

## 2026-09-24 — OpenRouter tiers on free models; a real crash they exposed

shreedhar_cctech, `0d1b294`.

### A-06 | OpenRouter tiers point at OpenRouter's `:free` text and vision models | live extraction testing should not draw on paid credits | the free tier overloads more often, which is how the crash below was found

**The crash:** OpenRouter can return **HTTP 200 with an `error` body** instead of `choices` (seen
live: `{"error": {"code": 503, "Service temporarily overloaded"}}`), which raised an unhandled
`KeyError` mid-run. Now checked explicitly and mapped to the router's error types: 429 →
`QuotaExhausted`, 401/403 → `ProviderUnavailable`, anything else → plain `LLMError`, so the router
retries or escalates rather than disabling the tier for the whole run. The
`choices → message → content` access is wrapped instead of assumed.

---

## 2026-09-24 — the model extraction path, text and vision (A1/A2)

shreedhar_cctech, `46843db`. Before this, `extract_claims()` ran only the deterministic path; the
prose loop and the image loop were both `TODO(A)`.

**Measured live on the NaCl packet:** **698 claims** — 501 deterministic, 150 from text, 47 from
vision — with about **19%** of raw text claims caught and dropped by the verbatim check (A-01).

### A-01 | Reject any claim whose quote is not a literal substring of its source, checked per claim | PLAN.md's single most important rule for small models: it removes almost all fabrication and costs nothing | a claim that paraphrases correctly is still dropped — recall traded for honesty, deliberately

Checked per claim (`_quote_ok`, `_quote_is_verbatim`), so one fabricated quote no longer discards
a whole valid batch. Dropped claims are warned about, not lost silently.

### A-02 | The text model sees prose blocks only | tables, key-value blocks, graphs, code and images already have exact deterministic readers; giving them to a model as text invites it to "re-read" a number wrongly | `Document.chunks(kinds=...)`, a new filter on the ingest side

### A-03 | Confidence is fixed per extraction path, not reported by the model | precedence needs a number it can trust; a model's self-reported confidence is not one | the numbers are a judgement call, recorded here so they can be argued with

| Path | Confidence |
|:--|:--|
| table rows, key-value pairs | 0.95 |
| graph edges | 0.9 |
| supersession records | 0.8 |
| per-span text model | 0.6 |
| whole-packet skeleton (A-08, later) | 0.5 |
| vision | 0.4 |

### A-04 | Images embedded in `.docx` files reach the vision path, through the same tiling helper as standalone images | P&IDs and sketches usually arrive pasted into a document, not as a separate file | `_diagram_claims_are_plausible` validates the vision output's shape; bug 2 above shows what it did not yet catch

Also in this commit: an `OpenRouterProvider` (OpenAI-compatible, text and vision), because the
environment had an OpenRouter key rather than Groq/Gemini/Ollama; a router fix so the escalation
cap counts **actual provider attempts** rather than position in the chain — it was capping at three
tiers *before* skipping unavailable ones, so a fourth-tier fallback behind dead tiers was never
reached; `pypdfium2` and a `live` pytest marker; `tests/test_live_smoke.py`, gated on
`OPENROUTER_API_KEY`; and a non-NaCl fixture proving nothing domain-specific is load-bearing.

**Scope at the time:** extraction only. `reconcile/builder.py`'s assembly (B1–B5) did not exist
yet, so these claims were verified through `extract_claims()` directly, not through a full
`specalive run`.

---

## Decisions about extraction recorded elsewhere

Listed here so A's picture is complete. The rows themselves live in [STATUS.md §3](../STATUS.md)
and the other logs.

| Where | Decision | What it means for A |
|:--|:--|:--|
| STATUS D17 | Source classification reads the **title area only** | a register that *mentions* change records is not one; still imperfect — per-claim classification is the real fix (A-10 covers rows, not sources) |
| STATUS D22 | A hand-built **reference IR** is a first-class artefact | decoupled B/C/D from A on day one, and is A's scoring oracle via `specalive ir-diff` |
| STATUS D28 (B) | Table extraction keeps **every named column** | B changed A's `extract/claims.py`: an unrecognised header keeps its own name, the id column must be unique |
| STATUS D32 (B) | Drawing and vision edges **corroborate** register topology, never create it | A's vision claims are evidence, not routing authority — the vision model's P&ID edges were mostly wrong (B1→B2, B6→B7) |
| D.md 2026-09-24 | `ir-diff` compared **meaning, not spelling** | it had been scoring vocabulary: 0% on connections against a topologically identical graph. Fixed to compare edges block-to-block and signals by role and binding: autonomous packet **3/10 → 8/10**, semantic recall **83% → 92%** |

## Still open

- **Prose-only sequences.** B's 2026-09-25 handoff asked A to teach `extract_claim` the
  `next`/`action`/`region` vocabulary for a sequence described only in prose. The two-tank packet
  is now solved another way — its transition *table* is read deterministically (`47483f2`), and the
  controller reaches all 8 of its states — but a packet whose sequence exists **only** as narrative
  text is still unaddressed.
- **Per-source authority.** Still the title-area heuristic (D17).
- **Cross-source de-duplication** as an extraction step, if the team still wants it beyond P6
  corroboration at reconcile time.
