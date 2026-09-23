package SpecAlive
  "Domain-general component templates used by SpecAlive-generated Modelica models"
  extends Modelica.Icons.Package;

  package Interfaces "Causal directed-stream connectors (Tier-1 process abstraction)"
    extends Modelica.Icons.InterfacesPackage;

    connector Outlet "Supply side of a storage element"
      output Modelica.Units.SI.MassFraction w "Solute mass fraction of supplied stream";
      output Modelica.Units.SI.Temperature T "Temperature of supplied stream";
      output Real avail "Draw-down availability, 0 to 1";
      input Modelica.Units.SI.MassFlowRate m_flow "Flow drawn by the downstream element";
    end Outlet;

    connector Suction "Upstream side of a transport element"
      input Modelica.Units.SI.MassFraction w;
      input Modelica.Units.SI.Temperature T;
      input Real avail;
      output Modelica.Units.SI.MassFlowRate m_flow;
    end Suction;

    connector Discharge "Downstream side of a transport element"
      output Modelica.Units.SI.MassFlowRate m_flow;
      output Modelica.Units.SI.MassFraction w;
      output Modelica.Units.SI.Temperature T;
    end Discharge;

    connector Inlet "Feed side of a receiving element"
      input Modelica.Units.SI.MassFlowRate m_flow;
      input Modelica.Units.SI.MassFraction w;
      input Modelica.Units.SI.Temperature T;
    end Inlet;
  end Interfaces;

  package Media "Replaceable lightweight property correlations"
    extends Modelica.Icons.FunctionsPackage;

    function density "Linear solute-dependent density"
      input Modelica.Units.SI.MassFraction w;
      input Modelica.Units.SI.Density d0 = 998.0;
      input Real k_d = 700.0;
      output Modelica.Units.SI.Density d;
    algorithm
      d := d0 + k_d * w;
      annotation (Inline = true);
    end density;

    function specificHeat "Linear solute-dependent specific heat capacity"
      input Modelica.Units.SI.MassFraction w;
      input Modelica.Units.SI.SpecificHeatCapacity cp0 = 4180.0;
      input Real k_cp = -2400.0;
      output Modelica.Units.SI.SpecificHeatCapacity cp;
    algorithm
      cp := cp0 + k_cp * w;
      annotation (Inline = true);
    end specificHeat;

    function boilingPoint "Boiling temperature including solute elevation"
      input Modelica.Units.SI.MassFraction w;
      input Modelica.Units.SI.Temperature T0 = 373.15;
      input Real k_bpe = 55.0;
      output Modelica.Units.SI.Temperature T;
    algorithm
      T := T0 + k_bpe * w;
      annotation (Inline = true);
    end boilingPoint;
  end Media;

  package Vessels "Lumped storage elements"
    extends Modelica.Icons.Package;

    partial model PartialVessel
      "Mass, solute and energy balance for a lumped vessel. Extend and bind Q_ext and m_evap."
      import SI = Modelica.Units.SI;

      parameter SI.Area area = 0.05 "Cross-sectional area";
      parameter SI.Height levelMax = 0.5 "Geometric maximum level";
      parameter SI.Height level_start = 0.005 "Initial level";
      parameter SI.MassFraction w_start = 0.0 "Initial solute mass fraction";
      parameter SI.Temperature T_start = 293.15 "Initial temperature";
      parameter SI.Height level_min = 0.005 "Residual level that cannot be drained";
      parameter SI.Height level_band = 0.004 "Regularization band above level_min";
      parameter Integer nIn = 0 "Number of feed ports";
      parameter Integer nOut = 0 "Number of supply ports";
      parameter SI.Density d0 = 998.0;
      parameter Real k_d = 700.0;
      parameter SI.SpecificHeatCapacity cp0 = 4180.0;
      parameter Real k_cp = -2400.0;
      parameter SI.SpecificEnthalpy h_vap = 2.26e6 "Latent heat of vaporization";

      final parameter SI.Density d_start = Media.density(w_start, d0, k_d);
      final parameter SI.Mass m_start = area * level_start * d_start;

      Interfaces.Inlet inlet[nIn];
      Interfaces.Outlet outlet[nOut];

      SI.Mass m(start = m_start, fixed = true) "Total mass (state)";
      SI.Mass mSolute(start = m_start * w_start, fixed = true) "Solute mass (state)";
      SI.Temperature T(start = T_start, fixed = true) "Bulk temperature (state)";
      SI.MassFraction w "Solute mass fraction";
      SI.Height level "Liquid level";
      SI.Density d "Bulk density";
      SI.SpecificHeatCapacity cp "Bulk specific heat capacity";
      SI.MassFlowRate m_in_total;
      SI.MassFlowRate m_out_total;
      SI.HeatFlowRate Q_ext "External heat input, bound by the extending model";
      SI.MassFlowRate m_evap "Vapor leaving, bound by the extending model";
    protected
      constant SI.Mass m_eps = 1e-6;
    equation
      w = mSolute / max(m, m_eps);
      d = Media.density(w, d0, k_d);
      cp = Media.specificHeat(w, cp0, k_cp);
      level = m / (area * d);

      m_in_total = sum(inlet.m_flow);
      m_out_total = sum(outlet.m_flow);

      der(m) = m_in_total - m_out_total - m_evap;
      der(mSolute) = sum(inlet.m_flow .* inlet.w) - m_out_total * w;
      max(m, m_eps) * cp * der(T) =
        sum(inlet.m_flow .* Media.specificHeat(inlet.w, cp0, k_cp) .* (inlet.T .- T))
        + Q_ext - m_evap * h_vap;

      for i in 1:nOut loop
        outlet[i].w = w;
        outlet[i].T = T;
        outlet[i].avail = min(1.0, max(0.0, (level - level_min) / level_band));
      end for;
    end PartialVessel;

    model Reservoir "Passive lumped vessel"
      extends PartialVessel;
    equation
      Q_ext = 0;
      m_evap = 0;
    end Reservoir;

    model CooledVessel "Vessel with a commanded cooling duty"
      extends PartialVessel;
      parameter Modelica.Units.SI.HeatFlowRate Q_cool = 6500 "Cooling duty magnitude";
      parameter Modelica.Units.SI.Temperature T_floor = 288.15 "Coolant-limited floor temperature";
      Modelica.Blocks.Interfaces.BooleanInput cooler "Cooling command";
    equation
      Q_ext = -Q_cool * (if cooler then 1.0 else 0.0)
              * min(1.0, max(0.0, T - T_floor))
              * min(1.0, max(0.0, (level - level_min) / level_band));
      m_evap = 0;
    end CooledVessel;

    model Evaporator "Heated vessel that boils off solvent through a vapor port"
      extends PartialVessel;
      parameter Modelica.Units.SI.HeatFlowRate Q_heater = 20000 "Heater duty";
      parameter Real eta_heat = 1.0 "Heater effectiveness";
      parameter Modelica.Units.SI.Temperature T_boil0 = 373.15;
      parameter Real k_bpe = 55.0 "Boiling-point elevation coefficient";
      Modelica.Blocks.Interfaces.BooleanInput heater "Heater command";
      Interfaces.Discharge vapor "Vapor outlet to the condenser";
      Modelica.Units.SI.Temperature T_boil "Composition-dependent boiling temperature";
      Modelica.Units.SI.HeatFlowRate Q_in "Delivered heater duty";
      Real boiling "Regularized 0 to 1 boiling indicator";
    equation
      T_boil = Media.boilingPoint(w, T_boil0, k_bpe);
      Q_in = eta_heat * Q_heater * (if heater then 1.0 else 0.0);
      boiling = min(1.0, max(0.0, (T - (T_boil - 0.5)) / 0.5));
      m_evap = boiling * Q_in / h_vap
               * min(1.0, max(0.0, (level - level_min) / level_band));
      Q_ext = Q_in;
      vapor.m_flow = m_evap;
      vapor.w = 0.0;
      vapor.T = T_boil;
    end Evaporator;
  end Vessels;

  package Transport "Directed transfer elements"
    extends Modelica.Icons.Package;

    model Path
      "Commanded transfer path. A series valve group lowers to one Path with a conjunct command."
      import SI = Modelica.Units.SI;
      parameter SI.MassFlowRate m_flow_nominal = 0.04 "Flow when the path is open";
      parameter SI.Height dz = 0.0 "Destination minus source elevation (documentation only in Tier 1)";
      parameter SI.TemperatureDifference dT_loss = 0.0 "Temperature drop across the path";
      Modelica.Blocks.Interfaces.BooleanInput open "Aggregate open command";
      Interfaces.Suction port_a;
      Interfaces.Discharge port_b;
      SI.MassFlowRate m_flow;
    equation
      m_flow = m_flow_nominal * (if open then 1.0 else 0.0) * port_a.avail;
      port_a.m_flow = m_flow;
      port_b.m_flow = m_flow;
      port_b.w = port_a.w;
      port_b.T = port_a.T - dT_loss;
    end Path;

    model Pump "Commanded return pump with a discharge-pressure signal"
      extends Path(m_flow_nominal = 0.30);
      parameter Modelica.Units.SI.Pressure dp_nominal = 1.8e5 "Nominal differential pressure";
      Modelica.Blocks.Interfaces.RealOutput p_discharge "Gauge discharge pressure";
    equation
      p_discharge = dp_nominal * (if open then 1.0 else 0.0);
    end Pump;

    model Condenser "Total condenser with a cooling-water duty signal"
      parameter Modelica.Units.SI.Temperature T_out = 368.15 "Condensate outlet temperature";
      parameter Modelica.Units.SI.SpecificEnthalpy h_vap = 2.26e6;
      Interfaces.Inlet port_a "Vapor inlet";
      Interfaces.Discharge port_b "Condensate outlet";
      Modelica.Blocks.Interfaces.RealInput cw_flow "Cooling-water mass flow";
      Modelica.Units.SI.HeatFlowRate Q_cw "Duty rejected to cooling water";
    equation
      port_b.m_flow = port_a.m_flow;
      port_b.w = port_a.w;
      port_b.T = T_out;
      Q_cw = -port_a.m_flow * h_vap;
    end Condenser;

    model Junction "Header that merges several streams into one"
      parameter Integer nIn = 2;
      parameter Modelica.Units.SI.Volume V = 1e-5 "Nominal junction volume (documentation)";
      Interfaces.Inlet inlet[nIn];
      Interfaces.Discharge outlet;
      Modelica.Units.SI.MassFlowRate m_total;
    protected
      constant Modelica.Units.SI.MassFlowRate m_eps = 1e-8;
    equation
      m_total = sum(inlet.m_flow);
      outlet.m_flow = m_total;
      outlet.w = sum(inlet.m_flow .* inlet.w) / max(m_total, m_eps);
      outlet.T = if noEvent(m_total > m_eps)
                 then sum(inlet.m_flow .* inlet.T) / m_total
                 else 293.15;
    end Junction;
  end Transport;

  package Sources "Boundary elements"
    extends Modelica.Icons.SourcesPackage;

    model FixedSupply "Unlimited supply at a fixed state"
      parameter Modelica.Units.SI.MassFraction w = 0.0;
      parameter Modelica.Units.SI.Temperature T = 293.15;
      Interfaces.Outlet outlet;
    equation
      outlet.w = w;
      outlet.T = T;
      outlet.avail = 1.0;
    end FixedSupply;

    model Drain "Accepts any incoming stream"
      parameter Integer nIn = 1;
      Interfaces.Inlet inlet[nIn];
      Modelica.Units.SI.Mass m_collected(start = 0, fixed = true);
    equation
      der(m_collected) = sum(inlet.m_flow);
    end Drain;
  end Sources;

  annotation (
    uses(Modelica(version = "4.0.0")),
    version = "0.1.0",
    Documentation(info = "<html>
<p>Tier-1 (L1) component templates for SpecAlive. These are deliberately causal and
directed: flow is imposed by transport elements and states live in vessels. That removes
nonlinear pressure networks entirely, so generated models compile and integrate reliably.
Tier-2 models bind to acausal <code>Modelica.Fluid</code> components from the harvested
catalog instead.</p>
</html>"));
end SpecAlive;
