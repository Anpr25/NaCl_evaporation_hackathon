# DR-02 Design Review Minutes - Two-Tank Controller

**Date:** 19 Feb 2026  
**Status:** Final / approved decisions  
**Attendees:** A. Mehta (customer), S. Patel (controls), J. Lin (simulation), R. Gomez (V&V), L. Chen (safety)

## Discussion
The URS says STOP waits for either START or SHUT but does not state what happens to an active delay timer. Controls proposed freezing remaining delay. Simulation initially restarted the entire delay on resume. The review board selected **freeze remaining delay** because STOP should pause the process rather than alter the sequence timing.

The term `shut` was confirmed to mean a **controlled process shutdown/drain**, not an emergency-stop function. During SHUT, V1 must remain closed while V2 and V3 are commanded open together. This is an intentional exception to the normal prohibition on opening the transfer and drain valves together.

## Decisions
- **D-01:** Command precedence is `SHUT > STOP > START`.
- **D-02:** STOP closes all valves and stores the interrupted state.
- **D-03:** STOP during any delay freezes the remaining delay; START resumes the remaining delay.
- **D-04:** START while the automatic sequence is already running is ignored.
- **D-05:** START and STOP received during active SHUT are ignored.
- **D-06:** SHUT is complete only when both LT-101 and LT-102 are at or below their low-level setpoints.
- **D-07:** After shutdown completion, all valves are closed and the sequence context is reset to IDLE. A later START begins a new fill cycle.
- **D-08:** V1 and V2 must never be commanded open together.
- **D-09:** V2 and V3 must not be commanded open together in normal auto operation; SHUT is the only permitted exception.

## Open actions
- **A-17 / Customer:** Confirm whether T1 high should be increased from 0.78 m to 0.80 m. *Closed by CR-004 on 11 Mar 2026.*
- **A-18 / Customer:** Confirm post-transfer delay. *Closed by CR-004: 12 s.*
- **A-19 / Controls:** Consider reducing inter-cycle delay after Tank 2 low. *Closed by CR-004: 8 s.*
- **A-20 / Simulation:** Update legacy model after parameter approval. *No evidence of completion in the supplied packet.*

## Modeling note
The final SysML representation should distinguish the operator commands (events), the controller states, the physical valve/tank parts, the hydraulic connections and the requirement/verification elements. Do not model `shut` as a power-loss or emergency-stop event.
