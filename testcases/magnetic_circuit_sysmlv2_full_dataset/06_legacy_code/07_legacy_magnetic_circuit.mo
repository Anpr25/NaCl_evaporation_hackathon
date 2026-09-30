within SyntheticMagnetics;
model MagneticCircuit_v1
  import Modelica.Magnetic.QuasiStatic.FluxTubes;

  parameter SI.Length a = 0.025;
  parameter SI.Length l = 0.150;
  parameter SI.Length delta = 0.0015;
  parameter Real mu_r = 1000;       // STALE: CR-MAG-004 -> 1200
  parameter Real sigma = 0.05;      // STALE: CR-MAG-006 -> 0.08
  parameter Integer N_exc = 600;
  parameter Integer N_meas = 40;    // STALE: Coil Data B -> 50
  parameter SI.Frequency f = 50;

  // Simplified topology notes:
  // leftLeg -> upperYoke -> rightLeg -> (airGap || leakage) -> lowerYoke
  // Phi_gap = (1-sigma)*Phi_core
  // Electric and magnetic grounds are instantiated in the complete example.

equation
  // Legacy benchmark current was interpreted inconsistently in comments:
  // some notes call 2 A "amplitude"; released EP-03 defines 2 A RMS phasor magnitude.
end MagneticCircuit_v1;
