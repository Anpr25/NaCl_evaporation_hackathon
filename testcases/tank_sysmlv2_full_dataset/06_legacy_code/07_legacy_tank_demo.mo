within SyntheticTankDemo;
model TankDemo_Rev12
  // Archived 02-Feb-2026. This model predates later approved controls changes.
  parameter Real A1(unit="m2") = 1.20;
  parameter Real A2(unit="m2") = 1.40;
  parameter Real h0(unit="m") = 0.05;
  parameter Real h1High(unit="m") = 0.78;
  parameter Real h1Low(unit="m") = 0.05;
  parameter Real h2Low(unit="m") = 0.05;
  parameter Real qFill(unit="m3/s") = 0.0060;
  parameter Real qTransfer(unit="m3/s") = 0.0045;
  parameter Real qDrain(unit="m3/s") = 0.0050;
  parameter Real wait1(unit="s") = 10;
  parameter Real wait2(unit="s") = 10;
  parameter Real wait3(unit="s") = 10;

  Real tank1Level(start=h0, unit="m");
  Real tank2Level(start=h0, unit="m");
  Boolean valve1;
  Boolean valve2;
  Boolean valve3;
  Boolean startCmd;
  Boolean stopCmd;
  Boolean shutCmd;

  type StepState = enumeration(IDLE,FILL,HOLD1,TRANSFER,HOLD2,DRAIN,HOLD3);
  discrete StepState seq(start=StepState.IDLE);
  discrete Boolean stopped(start=false);

algorithm
  // Simplified demonstration logic. SHUT handling was not completed in this revision.
  when edge(startCmd) then stopped := false; end when;
  when edge(stopCmd) then stopped := true; end when;

  valve1 := (seq == StepState.FILL) and not stopped;
  valve2 := (seq == StepState.TRANSFER) and not stopped;
  valve3 := (seq == StepState.DRAIN) and not stopped;

  // State transition details omitted from this archived fragment.
  // A test harness supplies button edges at 20, 220, 280, 650 and 700 seconds.

equation
  der(tank1Level) = (if valve1 then qFill else 0)/A1 - (if valve2 then qTransfer else 0)/A1;
  der(tank2Level) = (if valve2 then qTransfer else 0)/A2 - (if valve3 then qDrain else 0)/A2;
end TankDemo_Rev12;
