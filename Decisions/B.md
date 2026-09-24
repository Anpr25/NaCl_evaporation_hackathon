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
