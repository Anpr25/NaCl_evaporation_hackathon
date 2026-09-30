within Hackathon.Legacy;
model RoomCO2Control_Archived_0_9
  // ARCHIVED MODEL - useful for topology, NOT all effective values.
  // Known stale values: 350 ppm outdoor CO2 and 12-person peak schedule.
  parameter Real V = 100 "Room volume [m3]";
  parameter Real rho = 1.2 "Nominal air density [kg/m3]";
  parameter Real C_nominal = 1.519e-3 "Nominal trace concentration [kg/kg]";
  parameter Real C_out = 0.35*C_nominal "STALE: 350 ppm equivalent";
  parameter Real GPeo = 8.18e-6 "CO2 generation [kg/s/person]";
  parameter Real CPeo = 100 "Trace concentration used by peopleSource [kg/kg]";
  parameter Real Kp = 4.0 "STALE controller tuning [ACH/normalized]";
  parameter Real uBias = 3.0 "STALE ACH bias";
  parameter Real uMin = 0.2;
  parameter Real uMax = 6.0;

  Real nPeo "occupancy, legacy schedule peaks at 12";
  Real mPeoCarrier "carrier source flow [kg/s]";
  Real CRoom "room CO2 mass fraction [kg/kg]";
  Real yCO2 "normalized feedback";
  Real achCmd;
  Real mFreshCmd "negative means into room at source port";

 equation
  mPeoCarrier = nPeo*GPeo/CPeo;
  yCO2 = CRoom/C_nominal;
  achCmd = min(uMax,max(uMin,uBias + Kp*(yCO2 - 1)));
  mFreshCmd = -V*rho/3600*achCmd;

  // Detailed fluid component declarations omitted from this archived extract.
  // Topology in original graphical model:
  // CAtm -> freshAir -> ductIn -> volume -> ductOut -> boundary4
  // NumberOfPeople -> gain -> peopleSource -> volume
  // volume.C -> traceVolume -> gainSensor -> PID -> gain1 -> freshAir.m_flow
end RoomCO2Control_Archived_0_9;
