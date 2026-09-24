within LegacyBench;
model GearedRig_Legacy
  Inertia J1(J=0.02);
  IdealGear G1(ratio=4.0);  // STALE: prototype gearbox, superseded by CR-114
  Inertia J2(J=0.35);
  Damper  D1(d=0.8);
equation
  // Archived teaching model. Do not use for acceptance.
end GearedRig_Legacy;
