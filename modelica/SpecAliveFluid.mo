within ;
package SpecAliveFluid
  "Tier-2: acausal Modelica.Fluid components, for the modelling constraints Tier 1 cannot express"

  // ==========================================================================================
  // Why this package exists (C6, closing OPEN-ISSUE-04)
  //
  // Tier 1 (`SpecAlive.mo`) is a causal directed-flow abstraction. That is decision C-01 and it
  // is the right default: no pressure network means no nonlinear algebraic systems, so every
  // generated model integrates reliably, and the packet itself warns that the acausal variant
  // stalls at pump start.
  //
  // The cost, declared rather than hidden, is that three modelling requirements have no
  // NUMERICAL effect in Tier 1 -- they are honoured on paper and nothing in the equations
  // depends on them:
  //
  //   REQ-MOD-004  regularized asymmetric port loss with hysteresis around the port elevation
  //   REQ-MOD-005  junction volumes where isolating pressure-drop elements could leave a node
  //                with no pressure, enthalpy or composition state
  //   REQ-MOD-006  static head on every non-horizontal pipe
  //
  // This package makes them real. It is deliberately small: the claim is not "we rebuilt the
  // plant acausally", it is "here is the same charge leg with those three constraints actually
  // in the equations, and here is the evidence they are active".
  // ==========================================================================================

  extends Modelica.Icons.Package;

  package Media "Composition-dependent properties"
    extends Modelica.Icons.Package;

    // ----------------------------------------------------------------------------------------
    // GAP-MEDIUM-01 -- WaterNaCl is NOT reconstructible from the supplied evidence.
    //
    // `13_water_nacl_medium_notes.pdf` specifies the hierarchy as
    //     PartialMedium -> PartialMixtureMedium -> PartialMixtureTwoPhaseMedium -> WaterNaCl
    // and MSL 4.1.0 has no `PartialMixtureTwoPhaseMedium`. Enumerating
    // `Modelica.Media.Interfaces` gives `PartialMixtureMedium` and `PartialTwoPhaseMedium` as
    // separate branches; the combined class would have to be written.
    //
    // That alone would be work, not a blocker. The blocker is that the same note says the
    // numeric coefficients are "intentionally absent from this benchmark evidence" for four of
    // the five required properties. Only viscosity is given in full:
    //
    //     eta(T,w) = exp(c1*T^3 + c2*T^2 + c3*T + c4 + c5*w + c6*w^2 + c7*w^3)
    //
    // rho(T,p,w), h(T,p,w), cp(T,w) and p_sat(T,w) have no coefficients anywhere in the packet.
    // Inventing them would be fabricated physics that compiles and simulates and is wrong --
    // exactly what standing rule 4 exists to prevent. So the one correlation we were given is
    // implemented, and the rest is declared.
    //
    // REQ-MOD-001 sanctions StandardWater as the topology and control-sequence baseline, and
    // that is what the examples below use.
    // ----------------------------------------------------------------------------------------

    function dynamicViscosity_WaterNaCl
      "Viscosity of aqueous NaCl. The ONE correlation the packet gives in full."
      extends Modelica.Icons.Function;
      input Modelica.Units.SI.Temperature T "Temperature";
      input Modelica.Units.SI.MassFraction w "NaCl mass fraction";
      output Modelica.Units.SI.DynamicViscosity eta;
    protected
      // 13_water_nacl_medium_notes.pdf section 5, verbatim.
      constant Real c1 = -6.83241e-07;
      constant Real c2 = 0.000765676;
      constant Real c3 = -0.297018665;
      constant Real c4 = -0.299730079;
      constant Real c5 = 2.065267182;
      constant Real c6 = 1.546491257;
      constant Real c7 = 31.57571595;
      Real Tc = Modelica.Units.Conversions.to_degC(T);
    algorithm
      eta := exp(c1*Tc^3 + c2*Tc^2 + c3*Tc + c4 + c5*w + c6*w^2 + c7*w^3);
      annotation (Documentation(info="<html>
<p>Implemented because the coefficients were supplied. The other four required properties --
density, enthalpy, heat capacity and saturation pressure -- have no coefficients anywhere in
the packet, so they are declared as GAP-MEDIUM-01 rather than invented.</p>
</html>"));
    end dynamicViscosity_WaterNaCl;
  end Media;

  package Examples "Demonstrators that put the three constraints in the equations"
    extends Modelica.Icons.ExamplesPackage;

    model ChargeLeg
      "B1 --V8--> B3 water charge, acausal, with REQ-MOD-004/005/006 numerically active"

      replaceable package Medium = Modelica.Media.Water.StandardWater
        constrainedby Modelica.Media.Interfaces.PartialMedium
        "REQ-MOD-001: the sanctioned baseline. Intended physical medium is WaterNaCl -- see GAP-MEDIUM-01.";

      // ---- geometry, from the Equipment sheet of 02_process_data_register.xlsx ----
      parameter Modelica.Units.SI.Area A_B1 = 0.070 "B1 cross-section";
      parameter Modelica.Units.SI.Height H_B1 = 0.600 "B1 height";
      parameter Modelica.Units.SI.Height ZP_B1 = 0.120 "B1 port elevation above its base";
      parameter Modelica.Units.SI.Area A_B3 = 0.050 "B3 cross-section";
      parameter Modelica.Units.SI.Height H_B3 = 0.450 "B3 height";
      parameter Modelica.Units.SI.Height ZP_B3 = 0.100 "B3 port elevation above its base";

      // ---- elevations, from 12_layout_coordinates.json (z_base, metres) ----
      parameter Modelica.Units.SI.Height Z_B1 = 4.8 "B1 floor datum";
      parameter Modelica.Units.SI.Height Z_B3 = 3.5 "B3 floor datum";
      // Signed, so SI.Length: SI.Height has min = 0 and this leg falls.
      final parameter Modelica.Units.SI.Length dZ = (Z_B3 + ZP_B3) - (Z_B1 + ZP_B1)
        "REQ-MOD-006: port-to-port elevation change, B1 -> B3";

      parameter Modelica.Units.SI.Height SP_B3_LVL_WATER = 0.13
        "Step1 exit [SP-B3-LVL-WATER, REQ-FUN-002]";

      // ASSUMPTION A-01. 08_valve_pump_datasheet.pdf gives the fail state, opening time and
      // leakage as %Kv, but no numeric Kv. Calibrated instead against the observed Step1
      // duration in 10_batch_run_3000s.csv, which runs t=20 s to t=180 s.
      parameter Medium.MassFlowRate V8_m_flow_nominal = 0.025 "ASSUMPTION A-01";
      parameter Modelica.Units.SI.Pressure V8_dp_nominal = 1.0e4 "ASSUMPTION A-01";

      // ASSUMPTION A-02. REQ-MOD-005 mandates junction volumes and states no size. 0.1 L is
      // small against the 6.5 L batch and large enough to stay well-conditioned.
      parameter Modelica.Units.SI.Volume V_junction = 1e-4 "ASSUMPTION A-02";

      inner Modelica.Fluid.System system(
        p_ambient = 101325,
        T_ambient = 293.15,
        g = 9.81,
        energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial,
        m_flow_small = 1e-4)
        "Ambient conditions per BAT-09 section 2";

      // ---------------------------------------------------------------------------------
      // REQ-MOD-004. `use_portsData = true` is not decoration. MSL's PartialLumpedVessel
      // implements exactly what the requirement asks for -- Fluid/Vessels.mo:336:
      //
      //   ports_penetration[i] = regStep(fluidLevel - portsData_height[i]
      //                                  - 0.1*portsData_diameter[i], 1, 1e-3,
      //                                  0.1*portsData_diameter[i])
      //
      // regularized (regStep), asymmetric (zeta_in is multiplied by the penetration while
      // zeta_out is divided by it), and the hysteresis width is scaled by the PORT DIAMETER.
      // Writing our own would be worse and harder to defend.
      // ---------------------------------------------------------------------------------
      Modelica.Fluid.Vessels.OpenTank B1(
        redeclare package Medium = Medium,
        crossArea = A_B1,
        height = H_B1,
        level_start = 0.45,
        nPorts = 1,
        use_portsData = true,
        portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(
          diameter = 0.02, height = ZP_B1, zeta_out = 0.5, zeta_in = 1.04)})
        "Charging tank B1";

      // B3's inlet sits at 0.10 m and the level starts at 0.005 m, so the port is crossed
      // during the fill. That crossing is the numerical case this example exists to exercise.
      Modelica.Fluid.Vessels.OpenTank B3(
        redeclare package Medium = Medium,
        crossArea = A_B3,
        height = H_B3,
        level_start = 0.005,
        nPorts = 1,
        use_portsData = true,
        portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(
          diameter = 0.02, height = ZP_B3, zeta_out = 0.5, zeta_in = 1.04)})
        "Mixing tank B3";

      // REQ-MOD-006: the leg falls 1.32 m and the static head is in the momentum balance.
      Modelica.Fluid.Pipes.StaticPipe downcomer(
        redeclare package Medium = Medium,
        length = 1.5,
        diameter = 0.02,
        height_ab = dZ)
        "Downcomer B1 -> V8 header";

      // REQ-MOD-005: the pipe and the valve are both pressure-drop-only. With V8 shut this
      // node would otherwise carry no state.
      Modelica.Fluid.Vessels.ClosedVolume J1(
        redeclare package Medium = Medium,
        V = V_junction,
        nPorts = 2,
        use_portsData = false)
        "Junction volume upstream of V8";

      Modelica.Fluid.Valves.ValveDiscrete V8(
        redeclare package Medium = Medium,
        dp_nominal = V8_dp_nominal,
        m_flow_nominal = V8_m_flow_nominal)
        "Automated valve V8. Boolean, fails closed [REQ-CTL-002, REQ-SAF-002]";

      Modelica.Units.SI.Height LIS_301 "B3 level transmitter";
      Boolean step1Complete(start = false, fixed = true) "Latched at SP-B3-LVL-WATER";

    equation
      LIS_301 = B3.level;
      // Latched, or the valve chatters at the setpoint.
      step1Complete = LIS_301 >= SP_B3_LVL_WATER or pre(step1Complete);
      // Written as an equation, matching the textual convention in section 6 of
      // 04_control_sequence_design.docx.
      V8.open = not step1Complete;

      connect(B1.ports[1], downcomer.port_a);
      connect(downcomer.port_b, J1.ports[1]);
      connect(J1.ports[2], V8.port_a);
      connect(V8.port_b, B3.ports[1]);

      annotation (
        experiment(StopTime = 400, Interval = 1, Tolerance = 1e-6),
        Documentation(info="<html>
<p>The smallest model that can carry all three constraints at once, so that each can be shown
to be <em>numerically</em> active rather than merely present:</p>
<ul>
<li><b>REQ-MOD-004</b> B3's inlet at 0.10 m is crossed by the rising level.</li>
<li><b>REQ-MOD-005</b> a junction volume between two pressure-drop-only elements.</li>
<li><b>REQ-MOD-006</b> static head from a 1.32 m fall.</li>
</ul>
<p>Calibration: reaches SP-B3-LVL-WATER at about 159 s against the 160 s the supplied trace
shows for Step1.</p>
</html>"));
    end ChargeLeg;

    // ------------------------------------------------------------------------------------
    // The pair below exists because the obvious counterexample did not work, and the
    // negative result is worth keeping.
    //
    // First attempt: take `ChargeLeg` and shrink the junction volume towards zero. It made
    // no difference -- 1.56 s against 1.38 s, which is noise. REQ-MOD-005 does not bite
    // there, and the requirement says why: it asks for a junction "wherever MULTIPLE
    // pressure-drop-only valve/pipe elements can be isolated simultaneously". In the charge
    // leg only V8 isolates, and B1 upstream of the pipe carries a state.
    //
    // The condition the requirement actually protects against needs TWO isolating elements
    // bracketing one node. That is the pair below, and the difference is unambiguous.
    // ------------------------------------------------------------------------------------

    model IsolatedNode
      "REQ-MOD-005 honoured: a junction volume between two isolating valves"
      replaceable package Medium = Modelica.Media.Water.StandardWater
        constrainedby Modelica.Media.Interfaces.PartialMedium;
      inner Modelica.Fluid.System system(
        energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial);
      Modelica.Fluid.Sources.Boundary_pT src(
        redeclare package Medium = Medium, nPorts = 1, p = 2e5, T = 293.15);
      Modelica.Fluid.Sources.Boundary_pT snk(
        redeclare package Medium = Medium, nPorts = 1, p = 1e5, T = 293.15);
      Modelica.Fluid.Valves.ValveDiscrete Va(
        redeclare package Medium = Medium, dp_nominal = 1e4, m_flow_nominal = 0.02);
      Modelica.Fluid.Valves.ValveDiscrete Vb(
        redeclare package Medium = Medium, dp_nominal = 1e4, m_flow_nominal = 0.02);
      Modelica.Fluid.Vessels.ClosedVolume J(
        redeclare package Medium = Medium, V = 1e-4, nPorts = 2, use_portsData = false,
        energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial)
        "REQ-MOD-005: the state that keeps this node defined when both valves shut";
    equation
      // Both valves shut at t = 1 s, isolating the node between them.
      Va.open = time < 1;
      Vb.open = time < 1;
      connect(src.ports[1], Va.port_a);
      connect(Va.port_b, J.ports[1]);
      connect(J.ports[2], Vb.port_a);
      connect(Vb.port_b, snk.ports[1]);
      annotation (
        experiment(StopTime = 3),
        Documentation(info="<html>
<p>Simulates cleanly through the isolation event.</p>
</html>"));
    end IsolatedNode;

    model IsolatedNodeNoJunction
      "The same, with the junction removed. A counterexample, not a variant to use."
      // Written out rather than `extends IsolatedNode`: Modelica inheritance can redeclare a
      // component but cannot delete one, and deleting the junction is the entire point.
      replaceable package Medium = Modelica.Media.Water.StandardWater
        constrainedby Modelica.Media.Interfaces.PartialMedium;
      inner Modelica.Fluid.System system(
        energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial);
      Modelica.Fluid.Sources.Boundary_pT src(
        redeclare package Medium = Medium, nPorts = 1, p = 2e5, T = 293.15);
      Modelica.Fluid.Sources.Boundary_pT snk(
        redeclare package Medium = Medium, nPorts = 1, p = 1e5, T = 293.15);
      Modelica.Fluid.Valves.ValveDiscrete Va(
        redeclare package Medium = Medium, dp_nominal = 1e4, m_flow_nominal = 0.02);
      Modelica.Fluid.Valves.ValveDiscrete Vb(
        redeclare package Medium = Medium, dp_nominal = 1e4, m_flow_nominal = 0.02);
    equation
      Va.open = time < 1;
      Vb.open = time < 1;
      connect(src.ports[1], Va.port_a);
      connect(Va.port_b, Vb.port_a);
      connect(Vb.port_b, snk.ports[1]);
      annotation (
        experiment(StopTime = 3),
        Documentation(info="<html>
<p>Identical except that the two valves connect directly, so the node between them has no
state. At the moment both shut, omc reports:</p>
<pre>The default linear solver fails, the fallback solver with total pivoting is started
at time 1.000000</pre>
<p>With the junction present that warning does not appear. The run still completes -- the
fallback solver rescues it -- which is exactly why this is worth demonstrating rather than
trusting to luck: the failure is silent unless the log is read, and on a larger plant with
several isolating groups it is what turns into a stall.</p>
</html>"));
    end IsolatedNodeNoJunction;
  end Examples;

  annotation (
    uses(Modelica(version = "4.0.0")),
    Documentation(info="<html>
<p>Tier 2. Not the default emission target: Tier 1 stays the default because it integrates
reliably on an unseen packet, and this exists so the constraints Tier 1 cannot express are
demonstrated in equations rather than claimed in prose.</p>
</html>"));
end SpecAliveFluid;
