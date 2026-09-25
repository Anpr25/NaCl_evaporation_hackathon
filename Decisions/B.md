# Workstream B — IR, reconciliation, SysML

The decision table lives in [STATUS.md §3](../STATUS.md) (D27–D34). This page is the short
version for whoever picks B up next.

## How the builder reads a packet

1. **Precedence** picks one winning claim per (subject, predicate). Many-valued relations
   (`connects_to`, `label`) skip it: B5 feeds K1 *and* B7, which is not a conflict.
2. **Entities** regroup winners per subject (`reconcile/entities.py`). Nothing downstream ever
   sees a losing claim, so a superseded value cannot leak into the model.
3. **Shapes, not names** (D27). `from`+`to` is a hop, `next` is a sequence step,
   `location`+measurement is an instrument, a numeric `value` is a parameter, a tagged subject
   with a physical kind is a part.
4. **Topology** (`topology.py`, B2) walks hops into node-to-node paths, collapses series
   elements, and resolves named groups ("plus B1 routing group") from wherever their members are
   listed, with a `DecisionRecord` for every derivation (D30).
5. **Behaviour** (`behaviour.py`) parses conditions into the guard language, builds interlocks
   from permissive/inhibit statements, and lowers the sequence table to an FSM with synthesised
   `Idle<R>` / `Done<R>` states per parallel region. A clause it cannot formalise is dropped
   and declared (D31).
6. **Traceability**: each active requirement is linked to the elements its text names, which
   become `satisfy` / `verify` relationships in the SysML (D33).

## Where to look when it goes wrong

| Symptom | Look at |
|:--|:--|
| a register sheet contributes nothing | `extract/claims.py::column_predicates` — is the header row found, is there a unique id column? |
| a part is missing | `Assembler.classify` — it needs a tag-like subject plus a physical kind, or a topology reference |
| a series group is short | `TopologyBuilder.group_members` — which of the two group forms should have matched? |
| a guard is `true` | the `GAP-FSM-*` gaps name the dropped clause |
| SysML round trip fails | `parse_back().unparsed` first: a new construct the parser does not know yet |

## Measure

```bash
specalive run nacl_evaporation_sysmlv2_full_dataset --provider none --out out/nacl_x
specalive ir-diff out/nacl_x/ir.json benchmarks/nacl_evaporation/reference_ir.json
```

Last measured: 83% overall, topology 90%, series groups 100%, requirements 100%. The remaining
misses are naming (`RET_A` vs `L_B6_B1`) and two setpoints the reference invented that no source
states (`SP-HEATER-LVL`, `SP-PUMP-LVL`).

## 2026-09-25 — why TK_101 read as "external boundary": a scope column misread as an id

Responds to C-27's handoff (`Decisions/C.md`): on the TwoTank packet, `TK_101`/`TK_102` arrived
`physical_only` even though `Equipment_Schedule` states real tank geometry for both. Traced past
`Assembler.classify` (correctly true: `has_kind` and `physical` were both true) into extraction.

**Root cause.** `Operating_Parameters` has a `Tag / Scope` column: which existing part a
setpoint applies to, not that row's own identity ('Initial level' repeats once per tank).
`normalise_header` matched it to canonical `id` anyway, on the "tag " prefix rule meant for
headers like `Tag Number`. `claims_from_table` then took every setpoint row's SUBJECT from that
column — so `TK-101` became the subject of "High level limit", "Low level limit" and "Initial
level" claims too, merging a numeric `value` fact into `TK_101`'s own entity. `classify()`'s
`parameter_keys` test (`e.get("value") is not None`) claimed it before `part_keys` ever got a
turn, so `build_blocks` never ran for it and `build_topology`'s `_boundary()` fallback filled in
an "external boundary" placeholder instead — legitimate-looking, wrong reason.

The same column pattern hid `PLC_101`'s own equipment record ("Controller scan time" scoped to
`PLC-101`), and a second, independent bug compounded it: `build_topology`'s signal/physical
split excluded a command or measurement edge from the signal bus **only if** neither endpoint
was already a modeled block — backwards once both ends legitimately exist. Fixed by removing
that guard: a medium word decides "signal", not whether the graph happens to have caught up.

**Fixes (`extract/claims.py`, `reconcile/builder.py`):**
- `normalise_header` now tries every predicate's *exact* synonym across the whole table before
  any predicate's fuzzy prefix rule runs, and `scope` (`"tag / scope"`, `"applies to"`) is a
  first-class predicate `_build_parameters` already knew how to read.
- `claims_from_table`'s "nothing is fully distinct" fallback now takes the first column, per its
  own docstring, instead of silently returning `[]` and dropping the whole table — a revisioned
  register (superseded/approved rows) never has a distinct column by construction.
- `build_topology`'s bus/physical split no longer requires an endpoint to be un-modeled.
- `build_blocks` marks a `kind` containing "controller" `physical_only`: its behaviour belongs to
  `build_behaviour`'s state machine and `_emit_controller`, not the L0/L1/L2 binding cascade —
  letting it in synthesised an L2 "controller" out of two bare equations, one referencing a
  member no plain `RealInput` has.

Verified: `TK_101`/`TK_102` now bind (`SpecAlive.Vessels.Reservoir` via L1 once
`emit/modelica.py` also stopped offering `Modelica.Fluid.*` for a fluid-domain vessel — different
connector convention, same "wrong reason" shape as C-27's fix), the plant compiles and
simulates, and `specalive bench` is unchanged (drivetrain 7/7, nacl_evaporation 11/12). 162 fast
tests green.

**Still open — the rest of C-27's handoff.** `state_machines` is still `[]`. The tank sequence
lives entirely in `04_control_logic_design_notes.docx` prose; `step_rows()` needs a `next` fact
per state and `EXTRACT_PROMPT` never asks the model for one — it extracted `guard` facts for
every state (`IDLE`, `FILL_T1`, ... `SHUTDOWN`) but nothing links one to the next, so
`build_state_machine` gets zero rows and returns nothing. Every valve stays at its declared
default (closed); the model compiles and runs, but is inert. This needs prompt/schema work
(A's side: teach `extract_claim` the `next`/`action`/`region` vocabulary for sequential prose,
or a deterministic step-table parser for a docx narrative with numbered/ordered steps), not
another reconciliation fix — `classify()` already promotes any entity `e.has("next")` to a
`step_key` correctly; there is just nothing with that shape to promote. Also open, separately:
LT_101/LT_102 arrive as blocks needing their own binding when a level transmitter should be a
`Signal` bound to `TK_101.level`/`TK_102.level` (noted in C-27; not touched here — reclassifying
an instrument that already has a `location` fact pointing at a *physical_only-turned-real* block
is a `build_signals`/`instrument_keys` change, not a `classify()` one).
