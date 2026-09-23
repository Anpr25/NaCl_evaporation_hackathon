package GeneratedPlant
  "REFERENCE EMITTER OUTPUT -- what emit/modelica.py must reproduce from reference_ir.json.

   Every element carries an @trace comment naming the requirement and evidence source it
   came from. The emitter writes these automatically; they are the traceability artifact."

  extends Modelica.Icons.Package;

  block BatchController
    "Sequential controller lowered to a PLC scan model: one Integer state per concurrent region.

     @trace REQ-DAT-001 REQ-DAT-002 SRC-04!ControlSequenceDesign#2
     @lowering state_machine -> sampled algorithmic FSM (domain-general emitter pattern)"

    // ---- scan / timing -------------------------------------------------------
    parameter Modelica.Units.SI.Time Ts = 0.1 "Controller scan period";
    parameter Modelica.Units.SI.Time t_start = 20 "Start permissive time";
    parameter Modelica.Units.SI.Time t_restart = 2500
      "@trace REQ-CTL-001 SP-RESTART minimum cycle restart time";

    // ---- setpoints (all sourced from the Setpoint register) ------------------
    parameter Real SP_B3_LVL_WATER = 0.13 "m  @trace REQ-FUN-002 SP-B3-LVL-WATER";
    parameter Real SP_B3_COMP = 0.080 "kg/kg  @trace REQ-PER-001 SP-B3-COMP";
    parameter Real SP_B3_EMPTY = 0.01 "m  @trace REQ-FUN-004 SP-B3-EMPTY";
    parameter Real SP_B5_IDLE = 0.01 "m  @trace REQ-FUN-005 SP-B5-IDLE";
    parameter Real SP_B5_BATCH = 0.18 "m  @trace REQ-FUN-006 SP-B5-BATCH";
    parameter Real SP_B5_COMP = 0.180 "kg/kg  @trace REQ-PER-002 SP-B5-COMP";
    parameter Real SP_B6_COOL = 293.15 "K  @trace REQ-FUN-009 SP-B6-COOL (20 degC)";
    parameter Real SP_B7_COOL = 298.15
      "K  @trace REQ-FUN-010 SP-B7-COOL (25 degC, CR-017 supersedes the 20 degC legacy note)";
    parameter Real SP_K1_CW = 0.10 "kg/s  @trace REQ-SAF-001 SP-K1-CW";
    parameter Real SP_HEATER_MIN_LVL = 0.05 "m  @trace REQ-SAF-005 DR-07";
    parameter Real SP_PUMP_MIN_LVL = 0.02 "m  @trace REQ-SAF-003 REQ-SAF-004";
    parameter Real SP_B4_EMPTY = 0.01 "m";

    parameter Boolean allowBufferExhaustedExit = true
      "OPEN-ISSUE-01: the REQ-FUN-006 guard LIS_501 >= 0.18 m is unreachable from one B3 batch
       under a mass-consistent balance. Derived fallback exit added so the sequence cannot
       deadlock. See report section 'Declared deviations'.";

    // ---- sensor inputs  @trace REQ-DAT-001 ICD-04 ----------------------------
    input Real LIS_301 "B3 level, m";
    input Real QI_302 "B3 NaCl mass fraction, kg/kg";
    input Real LIS_401 "B4 level, m";
    input Real LIS_501 "B5 level, m";
    input Real QIS_502 "B5 NaCl mass fraction, kg/kg";
    input Real TI_503 "B5 temperature, K";
    input Real LIS_601 "B6 level, m";
    input Real TIS_602 "B6 temperature, K";
    input Real LIS_701 "B7 level, m";
    input Real TIS_702 "B7 temperature, K";
    input Real FIS_801 "K1 cooling-water flow, kg/s";

    // ---- actuator outputs  @trace REQ-DAT-002 ICD-04 -------------------------
    output Boolean cmd_V1;
    output Boolean cmd_V3;
    output Boolean cmd_V5;
    output Boolean cmd_V6;
    output Boolean cmd_V8;
    output Boolean cmd_V9;
    output Boolean cmd_V11;
    output Boolean cmd_V12;
    output Boolean cmd_V15;
    output Boolean cmd_V18;
    output Boolean cmd_V20;
    output Boolean cmd_V22;
    output Boolean cmd_V23;
    output Boolean cmd_V24;
    output Boolean cmd_V25;
    output Boolean cmd_P1;
    output Boolean cmd_P2;
    output Boolean cmd_heater;
    output Boolean cmd_coolB6;
    output Boolean cmd_coolB7;

    // ---- region states -------------------------------------------------------
    Integer sMain(start = 0, fixed = true)
      "0 Initial, 1..6 Step1..Step6, 7 ParallelActive, 8 Join";
    Integer sA(start = 0, fixed = true) "0 idle, 1 Step12, 2 Step13, 3 DoneA";
    Integer sB(start = 0, fixed = true) "0 idle, 1 Step7, 2 Step8, 3 Step9, 4 Step10, 5 DoneB";

    Boolean heaterPermissive "@trace REQ-SAF-001 REQ-SAF-005";
    Boolean returnA "@trace REQ-ROU-003 CR-017: B6 condensate -> B1";
    Boolean returnB "@trace REQ-ROU-004 CR-017: B7 concentrate -> B2";

  algorithm
    when sample(0, Ts) then
      // ---------------- region MAIN ----------------
      if pre(sMain) == 0 then
        if time >= t_start then
          sMain := 1;
        end if;
      elseif pre(sMain) == 1 then
        if LIS_301 >= SP_B3_LVL_WATER then
          sMain := 2;
        end if;
      elseif pre(sMain) == 2 then
        if QI_302 >= SP_B3_COMP then
          sMain := 3;
        end if;
      elseif pre(sMain) == 3 then
        if LIS_301 < SP_B3_EMPTY then
          sMain := 4;
        end if;
      elseif pre(sMain) == 4 then
        if LIS_501 < SP_B5_IDLE then
          sMain := 5;
        end if;
      elseif pre(sMain) == 5 then
        if LIS_501 >= SP_B5_BATCH
           or (allowBufferExhaustedExit and LIS_401 < SP_B4_EMPTY) then
          sMain := 6;
        end if;
      elseif pre(sMain) == 6 then
        if QIS_502 >= SP_B5_COMP then
          sMain := 7;
          sA := 1;
          sB := 1;
        end if;
      elseif pre(sMain) == 7 then
        if pre(sA) == 3 and pre(sB) == 5 then
          sMain := 8;
        end if;
      elseif pre(sMain) == 8 then
        if time > t_restart then
          sMain := 0;
          sA := 0;
          sB := 0;
        end if;
      end if;

      // ---------------- region A: condensate ----------------
      if pre(sA) == 1 then
        if TIS_602 <= SP_B6_COOL then
          sA := 2;
        end if;
      elseif pre(sA) == 2 then
        if LIS_601 <= SP_PUMP_MIN_LVL then
          sA := 3;
        end if;
      end if;

      // ---------------- region B: concentrate ----------------
      if pre(sB) == 1 then
        if LIS_701 < SP_B5_IDLE then
          sB := 2;
        end if;
      elseif pre(sB) == 2 then
        if LIS_501 < SP_B5_IDLE then
          sB := 3;
        end if;
      elseif pre(sB) == 3 then
        if TIS_702 <= SP_B7_COOL then
          sB := 4;
        end if;
      elseif pre(sB) == 4 then
        if LIS_701 <= SP_PUMP_MIN_LVL then
          sB := 5;
        end if;
      end if;
    end when;

  equation
    heaterPermissive = LIS_501 >= SP_HEATER_MIN_LVL and FIS_801 >= SP_K1_CW;
    returnA = (sA == 2);
    returnB = (sB == 4);

    cmd_V8 = (sMain == 1);
    cmd_V9 = (sMain == 2);
    cmd_V11 = (sMain == 3);
    cmd_V12 = (sMain == 5);
    cmd_heater = (sMain == 6) and heaterPermissive;
    cmd_V15 = (sB == 2);
    cmd_coolB6 = (sA == 1);
    cmd_coolB7 = (sB == 3);

    // CR-017 branch A: B6 condensate returns to B1 through P2 and the B1 valve group.
    cmd_V20 = returnA;
    cmd_V24 = returnA;
    cmd_V25 = returnA;
    cmd_V1 = returnA;
    cmd_V3 = returnA;
    cmd_P2 = returnA and (LIS_601 > SP_PUMP_MIN_LVL);

    // CR-017 branch B: B7 concentrate returns to B2 through P1 and the B2 valve group.
    cmd_V18 = returnB;
    cmd_V22 = returnB;
    cmd_V23 = returnB;
    cmd_V5 = returnB;
    cmd_V6 = returnB;
    cmd_P1 = returnB and (LIS_701 > SP_PUMP_MIN_LVL);
  end BatchController;

  model EvaporationPlant "NaCl evaporation bench, generated topology"

    // ---- vessels  @trace Equipment schedule ---------------------------------
    SpecAlive.Vessels.Reservoir B1(
      area = 0.070, levelMax = 0.50, level_start = 0.45, w_start = 0.0,
      nIn = 1, nOut = 1) "Charging tank, water-rich initial charge";
    SpecAlive.Vessels.Reservoir B2(
      area = 0.070, levelMax = 0.50, level_start = 0.30, w_start = 0.25,
      nIn = 1, nOut = 1) "Charging tank, concentrated brine initial charge";
    SpecAlive.Vessels.Reservoir B3(
      area = 0.050, levelMax = 0.38, nIn = 2, nOut = 1) "Mixing tank";
    SpecAlive.Vessels.Reservoir B4(
      area = 0.055, levelMax = 0.40, nIn = 1, nOut = 1) "Buffer tank";
    SpecAlive.Vessels.Evaporator B5(
      area = 0.060, levelMax = 0.40, nIn = 1, nOut = 1,
      Q_heater = 20000) "Evaporator  @trace REQ-THM-001 SP-B5-Q";
    SpecAlive.Transport.Condenser K1(T_out = 368.15)
      "Physical condenser retained as a distinct part  @trace DR-07 decision 5";
    SpecAlive.Vessels.CooledVessel B6(
      area = 0.050, levelMax = 0.35, nIn = 1, nOut = 1,
      Q_cool = 6500, T_floor = 288.15) "Condensate cooler  @trace SP-B6-Q";
    SpecAlive.Vessels.CooledVessel B7(
      area = 0.050, levelMax = 0.35, nIn = 1, nOut = 1,
      Q_cool = 4500, T_floor = 288.15) "Concentrate cooler  @trace SP-B7-Q";

    // ---- transfer paths ------------------------------------------------------
    // Each Path is the lowering of one series valve group; see @lowering notes.
    SpecAlive.Transport.Path L_V8(m_flow_nominal = 0.040) "B1 -> B3  @trace IF-PROC-01/02";
    SpecAlive.Transport.Path L_V9(m_flow_nominal = 0.020) "B2 -> B3  @trace IF-PROC-03/04";
    SpecAlive.Transport.Path L_V11(m_flow_nominal = 0.060) "B3 -> B4  @trace IF-PROC-05/06";
    SpecAlive.Transport.Path L_V12(m_flow_nominal = 0.060) "B4 -> B5  @trace IF-PROC-07/08";
    SpecAlive.Transport.Path L_V15(m_flow_nominal = 0.060) "B5 -> B7  @trace IF-PROC-11/12";
    SpecAlive.Transport.Pump RET_A(m_flow_nominal = 0.30)
      "@lowering series group {P2,V20,V24,V25,V1,V3} -> one Path   @trace IF-RET-01/02 REQ-ROU-003";
    SpecAlive.Transport.Pump RET_B(m_flow_nominal = 0.30)
      "@lowering series group {P1,V18,V22,V23,V5,V6} -> one Path   @trace IF-RET-03/04 REQ-ROU-004";

    // ---- utilities and controller -------------------------------------------
    Modelica.Blocks.Sources.Constant cw(k = 0.12)
      "K1 cooling-water flow proof  @trace IF-UTIL-01 REQ-SAF-001";
    BatchController ctrl;

  equation
    // ---- process topology  @trace Interfaces sheet --------------------------
    connect(B1.outlet[1], L_V8.port_a);
    connect(L_V8.port_b, B3.inlet[1]);
    connect(B2.outlet[1], L_V9.port_a);
    connect(L_V9.port_b, B3.inlet[2]);
    connect(B3.outlet[1], L_V11.port_a);
    connect(L_V11.port_b, B4.inlet[1]);
    connect(B4.outlet[1], L_V12.port_a);
    connect(L_V12.port_b, B5.inlet[1]);
    connect(B5.vapor, K1.port_a);
    connect(K1.port_b, B6.inlet[1]);
    connect(B5.outlet[1], L_V15.port_a);
    connect(L_V15.port_b, B7.inlet[1]);
    connect(B6.outlet[1], RET_A.port_a);
    connect(RET_A.port_b, B1.inlet[1]);
    connect(B7.outlet[1], RET_B.port_a);
    connect(RET_B.port_b, B2.inlet[1]);
    connect(cw.y, K1.cw_flow);

    // ---- sensor bundle  @trace REQ-DAT-001 SRC-04 section 6 -----------------
    ctrl.LIS_301 = B3.level;
    ctrl.QI_302 = B3.w;
    ctrl.LIS_401 = B4.level;
    ctrl.LIS_501 = B5.level;
    ctrl.QIS_502 = B5.w;
    ctrl.TI_503 = B5.T;
    ctrl.LIS_601 = B6.level;
    ctrl.TIS_602 = B6.T;
    ctrl.LIS_701 = B7.level;
    ctrl.TIS_702 = B7.T;
    ctrl.FIS_801 = cw.y;

    // ---- actuator bundle  @trace REQ-DAT-002 --------------------------------
    L_V8.open = ctrl.cmd_V8;
    L_V9.open = ctrl.cmd_V9;
    L_V11.open = ctrl.cmd_V11;
    L_V12.open = ctrl.cmd_V12;
    L_V15.open = ctrl.cmd_V15;
    B5.heater = ctrl.cmd_heater;
    B6.cooler = ctrl.cmd_coolB6;
    B7.cooler = ctrl.cmd_coolB7;

    // Series valve groups: every element of the group must be open for flow.
    RET_A.open = ctrl.cmd_P2 and ctrl.cmd_V20 and ctrl.cmd_V24 and ctrl.cmd_V25
                 and ctrl.cmd_V1 and ctrl.cmd_V3;
    RET_B.open = ctrl.cmd_P1 and ctrl.cmd_V18 and ctrl.cmd_V22 and ctrl.cmd_V23
                 and ctrl.cmd_V5 and ctrl.cmd_V6;

    annotation (
      experiment(StopTime = 3000, Interval = 5, Tolerance = 1e-6),
      __OpenModelica_simulationFlags(s = "dassl"));
  end EvaporationPlant;

  model BAT09 "Batch acceptance test BAT-09 Rev B  @trace REQ-VV-001 REQ-VV-002"
    extends EvaporationPlant;
    annotation (
      experiment(StopTime = 3000, Interval = 5, Tolerance = 1e-6),
      __OpenModelica_simulationFlags(s = "dassl"));
  end BAT09;

  annotation (uses(Modelica(version = "4.0.0"), SpecAlive(version = "0.1.0")));
end GeneratedPlant;
