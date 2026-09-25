# C  H  A  P  T  E  R    7

# EXAMPLE APPLICATIONS

## 7.1  Introduction

This chapter presents three example applications of the EPANET program.  The data sets for each example are provided on the EPANET distribution disk and should already reside in your EPANET directory if you followed the installation instructions in Chapter 3. The file names of the data sets are:

	NET1.INP		(Input data for Example 1)

	NET1.MAP		(Map coordinates for Example 1)

	NET2.INP		(Input data for Example 2)

	NET2.MAP		(Map coordinates for Example 2)

	NET2-N11.DAT	(Node 11 sampling results for Example 2)

	NET2-N19.DAT	(Node 19 sampling results for Example 2)

	NET2-N34.DAT	(Node 34 sampling results for Example 2)

	NET3.INP		(Input data for Example 3)

	NET3.MAP		(Map coordinates for Example 3)

## 7.2  Example 1 - Chlorine Decay

Figure 7.1 depicts a small distribution system that will be used to illustrate how EPANET can model chlorine decay.  Pump 9 takes water from a reservoir at Node 9 and feeds it into a system containing a storage tank at Node 2.  The operation of the pump is controlled by the level in Tank 2.  A 24 hour simulation of chlorine transport will be made assuming a first order decay of chlorine in the bulk flow occurs with a rate constant of -0.5/day and a first order wall reaction occurs with a rate constant of -1 ft/day.  The input data for this problem appears in Figure 7.2 (comments have been added throughout the data set to enhance its readability -- use of such comments is purely optional).

Figure 7.1  Network for Example 1

```text
=============================================
[TITLE]
 EPANET Example Network 1
[JUNCTIONS]
;------------------------
;      Elevation   Demand
; ID      ft        gpm
;------------------------
  10      710         0
  11      710       150
  12      700       150
  13      695       100
  21      700       150
  22      695       200
  23      690       150
  31      700       100
  32      710       100
[TANKS]
;--------------------------------------------
;     Elev.   Init.    Min.    Max.     Diam.
; ID   ft     Level    Level   Level     ft
;--------------------------------------------
   2   850     120      100     150     50.5
   9   800
=============================================
```
Figure 7.2	Input Data for Example 1

		(Continued on Next Page)

```text
==================================================
[PIPES]
;------------------------------------------------
;      Head     Tail    Length    Diam.   Rough.
;ID    Node     Node      ft       in     Coeff.
;------------------------------------------------
10       10       11    10530       18      100
11       11       12     5280       14      100
12       12       13     5280       10      100
21       21       22     5280       10      100
22       22       23     5280       12      100
31       31       32     5280        6      100
110       2       12      200       18      100
111      11       21     5280       10      100
112      12       22     5280       12      100
113      13       23     5280        8      100
121      21       31     5280        8      100
122      22       32     5280        6      100
[PUMPS]
;------------------------------
;    Head   Tail    Design H-Q
;ID  Node   Node    ft     gpm
;------------------------------
 9     9     10     250   1500
[CONTROLS]
;-----------------------------------------
 LINK 9 OPEN IF NODE 2 BELOW 110
 LINK 9 CLOSED IF NODE 2 ABOVE 140
[PATTERNS]
;-----------------------------------------
; ID  Multipliers.....
;------------------------------------------
  1   1.0  1.2  1.4  1.6  1.4  1.2
  1   1.0  0.8  0.6  0.4  0.6  0.8
[QUALITY]
;------------------------
;          Initial
;Nodes     Concen. mg/L
;------------------------
  2  32     0.5
  9         1.0
  2         1.0
[REACTIONS]
;-------------------------------------------
 GLOBAL BULK  -.5          ; Bulk decay coeff.
 GLOBAL WALL  -1           ; Wall decay coeff.
[TIMES]
;-----------------------------------------------
 DURATION 24        ; 24 hour simulation period
 PATTERN TIMESTEP 2 ; 2 hour pattern time period
[OPTIONS]
;----------------------------------------------
 QUALITY  Chlorine  ; Chlorine analysis
 MAP      Net1.map  ; Map coordinates file
[END]
==================================================
```
		Figure 7.2	Continued

These data also appear in the file NET1.INP in your EPANET directory.  You can run the program on this data several different ways:

	a)	from DOS, issue the command:

		EPANET  NET1.INP  NET1.RPT

		and use a file viewer to view the contents of NET1.RPT or have it printed,

	b)	from DOS, issue the command:

		EPANET4D  NET1.INP  NET1.RPT

		and select to run EPANET from the menu and then view or print the output file NET1.RPT,

	c)	if you've installed EPANET for Windows, then launch it, open the NET1.INP file, run the file through EPANET, and then look at the results using EPANET4W's various view options.

A portion of the output file, NET1.RPT, produced by methods (a) and (b) above is shown in Figure 7.3.

```text
==========================================================
    Page 1                                    Thu Jul 29 09:48:12 1993
    ******************************************************************
    *                           E P A N E T                          *
    *                   Hydraulic and Water Quality                  *
    *                   Analysis for Pipe Networks                   *
    *                           Version 1.1                          *
    ******************************************************************

     EPANET Example Network 1

      Input Data File ................... net1.inp
      Verification File .................
      Hydraulics File ...................
      Map File .......................... Net1.map
      Number of Pipes ................... 12
      Number of Nodes ................... 11
      Number of Tanks ................... 2
      Number of Pumps ................... 1
      Number of Valves .................. 0
      Headloss Formula .................. Hazen-Williams
      Hydraulic Timestep ................ 1.00 hrs
      Hydraulic Accuracy ................ 0.001000
      Maximum Trials .................... 40
      Quality Analysis .................. Chlorine
      Minimum Travel Time ............... 6.00 min
      Maximum Segments per Pipe ......... 100
      Specific Gravity .................. 1.00
      Kinematic Viscosity ............... 1.10e-005 sq ft/sec
      Chemical Diffusivity .............. 1.30e-008 sq ft/sec
      Total Duration .................... 24.00 hrs
      Reporting Criteria:
         All Nodes
         All Links

  Node Results at 0:00 hrs:
  -------------------------------------------------------------------
             Elev.    Demand     Grade  Pressure   Chlorine
      Node      ft       gpm        ft       psi      mg/L
  -------------------------------------------------------------------
        10  710.00      0.00   1004.50    127.61      0.50
        11  710.00    150.00    985.31    119.29      0.50
        12  700.00    150.00    970.07    117.02      0.50
        13  695.00    100.00    968.86    118.66      0.50
        21  700.00    150.00    971.55    117.66      0.50
        22  695.00    200.00    969.07    118.75      0.50
        23  690.00    150.00    968.63    120.73      0.50
        31  700.00    100.00    967.35    115.84      0.50
        32  710.00    100.00    965.63    110.77      0.50
         2  850.00    765.06    970.00     52.00      1.00   Tank
         9  800.00  -1865.06    800.00      0.00      1.00   Reservoir
==========================================================
```
Figure 7.3	Portion of Output Report for Example 1

		(Panel 1 of 3)

```text
==========================================================
  Page 2                                       EPANET Example Network 1
  Link Results at 0:00 hrs:
  ----------------------------------------------------------------
             Start     End  Diameter      Flow  Velocity  Headloss
      Link    Node    Node        in       gpm       fps   /1000ft
  ----------------------------------------------------------------
        10      10      11     18.00   1865.06      2.35      1.82
        11      11      12     14.00   1233.57      2.57      2.89
        12      12      13     10.00    129.41      0.53      0.23
        21      21      22     10.00    190.71      0.78      0.47
        22      22      23     12.00    120.59      0.34      0.08
        31      31      32      6.00     40.77      0.46      0.33
       110       2      12     18.00   -765.06      0.96      0.35
       111      11      21     10.00    481.48      1.97      2.61
       112      12      22     12.00    189.11      0.54      0.19
       113      13      23      8.00     29.41      0.19      0.04
       121      21      31      8.00    140.77      0.90      0.79
       122      22      32      6.00     59.23      0.67      0.65
         9       9      10             1865.06     96 hp   -204.50  Pump

  Node Results at 1:0 hrs:
  -------------------------------------------------------------------
             Elev.    Demand     Grade  Pressure   Chlorine
      Node      ft       gpm        ft       psi      mg/L
  -------------------------------------------------------------------
        10  710.00      0.00   1006.92    128.65      1.00
        11  710.00    150.00    988.05    120.48      0.45
        12  700.00    150.00    973.13    118.35      0.44
        13  695.00    100.00    971.91    119.98      0.44
        21  700.00    150.00    974.49    118.94      0.43
        22  695.00    200.00    972.10    120.07      0.44
        23  690.00    150.00    971.66    122.04      0.45
        31  700.00    100.00    970.32    117.13      0.41
        32  710.00    100.00    968.63    112.06      0.40
         2  850.00    747.57    973.06     53.32      0.97   Tank
         9  800.00  -1847.57    800.00      0.00      1.00   Reservoir

  Link Results at 1:00 hrs:
  ----------------------------------------------------------------
             Start     End  Diameter      Flow  Velocity  Headloss
      Link    Node    Node        in       gpm       fps   /1000ft
  ----------------------------------------------------------------
        10      10      11     18.00   1847.49      2.33      1.79
        11      11      12     14.00   1219.82      2.54      2.83
        12      12      13     10.00    130.19      0.53      0.23
        21      21      22     10.00    187.26      0.76      0.45
        22      22      23     12.00    119.81      0.34      0.08
        31      31      32      6.00     40.42      0.46      0.32
       110       2      12     18.00   -747.49      0.94      0.34
       111      11      21     10.00    477.68      1.95      2.57
==========================================================
```
	Figure 7.3	Panel 2 of 3

```text
==========================================================
  Page 3                                       EPANET Example Network 1

  Link Results at 1:00 hrs: (continued)
  ----------------------------------------------------------------
             Start     End  Diameter      Flow  Velocity  Headloss
      Link    Node    Node        in       gpm       fps   /1000ft
  ----------------------------------------------------------------
       112      12      22     12.00    192.14      0.55      0.20
       113      13      23      8.00     30.19      0.19      0.05
       121      21      31      8.00    140.42      0.90      0.79
       122      22      32      6.00     59.58      0.68      0.66
         9       9      10             1847.49     97 hp   -206.92  Pump

  Node Results at 2:00 hrs:
  -------------------------------------------------------------------
             Elev.    Demand     Grade  Pressure   Chlorine
      Node      ft       gpm        ft       psi      mg/L
  -------------------------------------------------------------------
        10  710.00      0.00   1008.43    129.31      1.00
        11  710.00    180.00    989.77    121.22      0.87
        12  700.00    180.00    976.09    119.63      0.81
        13  695.00    120.00    974.02    120.90      0.37
        21  700.00    180.00    975.41    119.34      0.76
        22  695.00    240.00    973.81    120.81      0.38
        23  690.00    180.00    973.33    122.77      0.40
        31  700.00    120.00    969.96    116.98      0.34
        32  710.00    120.00    968.13    111.85      0.31
         2  850.00    516.44    976.06     54.62      0.94   Tank
         9  800.00  -1836.44    800.00      0.00      1.00   Reservoir

  Link Results at 2:00 hrs:
  ----------------------------------------------------------------
             Start     End  Diameter      Flow  Velocity  Headloss
      Link    Node    Node        in       gpm       fps   /1000ft
  ----------------------------------------------------------------
        10      10      11     18.00   1836.44      2.32      1.77
        11      11      12     14.00   1163.77      2.43      2.59
        12      12      13     10.00    173.00      0.71      0.39
        21      21      22     10.00    150.47      0.61      0.30
        22      22      23     12.00    127.00      0.36      0.09
        31      31      32      6.00     42.20      0.48      0.35
       110       2      12     18.00   -516.44      0.65      0.17
       111      11      21     10.00    492.67      2.01      2.72
       112      12      22     12.00    294.33      0.83      0.43
       113      13      23      8.00     53.00      0.34      0.13
       121      21      31      8.00    162.20      1.04      1.03
       122      22      32      6.00     77.80      0.88      1.08
         9       9      10             1836.44     97 hp   -208.43  Pump
==========================================================
```
	Figure 7.3	Panel 3 of 3
