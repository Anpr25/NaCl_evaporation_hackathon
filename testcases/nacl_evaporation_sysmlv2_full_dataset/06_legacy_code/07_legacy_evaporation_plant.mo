within SyntheticBench;
model EvaporationPlant_Legacy
  replaceable package Medium = Modelica.Media.Water.StandardWater;

  Tank B1(area=0.070, levelMax=0.60);
  Tank B2(area=0.070, levelMax=0.60);
  Tank B3(area=0.050, levelMax=0.45);
  Tank B4(area=0.055, levelMax=0.45);
  TankWithEvaporator B5(area=0.060, levelMax=0.45);
  TankWithHeatPort B6(area=0.050, levelMax=0.40);
  TankWithHeatPort B7(area=0.050, levelMax=0.40);

  Controller controller(
    B3_water_level=0.13,
    B3_target_X=0.080,
    B5_batch_level=0.18,
    B5_target_X=0.180,
    B6_target_T=293.15,
    B7_target_T=293.15, // STALE: 20 C, superseded by CR-017
    restartTime=2500);

equation
  controller.sensors.LIS_301 = B3.level;
  controller.sensors.QI_302  = B3.medium.Xi[1];
  controller.sensors.LIS_501 = B5.level;
  controller.sensors.QIS_502 = B5.medium.Xi[1];
  controller.sensors.TIS_602 = B6.medium.T;
  controller.sensors.TIS_702 = B7.medium.T;

  B5.heatPort.Q_flow = if controller.actuators.T5_Heater then 20000 else 0;

  // OLD return routing preserved from archived teaching controller:
  // Branch B: B7/P1 to B1; Branch A: B6/P2 to B2.
  // This is superseded by CR-017 in the released benchmark.
end EvaporationPlant_Legacy;
