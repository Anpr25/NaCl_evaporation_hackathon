# AHU-2 / ZN-1 — Zone Heating Design Basis
Issue: Rev A, released. Superseded values may appear in later approved field change notices.
Discipline: Mechanical (HVAC). Project 4471 "North Wing".

## 1. Scope
This document covers the heating side of air handling unit AHU-2 serving zone ZN-1 only.
Cooling, humidification and the supply fan are outside this scope and are covered by
document 4471-M-12 (not issued).

## 2. Arrangement

The zone is treated as a single well-mixed thermal mass. Heat is lost through the building
envelope to outdoor air. A hot-water preheat coil in the AHU-2 supply duct injects heat into
the zone under thermostat control.

```
   OA  ─────[ envelope EF-1 ]───── ZN-1 ◄──── heat ──── HC-1 (preheat coil)
 outdoor                            zone                     ▲
   air                            air mass                   │
                                     │                    TC-2101
                                     └──── TT-2101 ───────────┘
```

## 3. Equipment

| Mark | Service | Notes |
|---|---|---|
| ZN-1 | Zone thermal mass | North Wing open-plan office, treated as one node |
| EF-1 | Envelope fabric | Lumped conductance, zone to outdoor air |
| OA | Outdoor air | Boundary condition, not plant |
| HC-1 | Preheat coil (LPHW) | On/off control, no modulation in this revision |
| TT-2101 | Zone air temperature transmitter | Wall mounted, 1.5 m AFL |
| TC-2101 | Zone temperature controller | Enables HC-1 |

## 4. Design conditions

Outdoor design temperature is 2 degC. Zone design temperature is 21 degC. The envelope
conductance is 450 W/K at design condition.

## 5. Notes

The preheat coil is sized at 12 kW. It is an on/off coil: when the controller enables it the
coil delivers its full rated duty, and when it is disabled it delivers nothing. There is no
face-and-bypass damper and no valve modulation in Rev A.

The zone thermal mass includes furniture and the exposed slab soffit and is taken as
300 kJ/K.
