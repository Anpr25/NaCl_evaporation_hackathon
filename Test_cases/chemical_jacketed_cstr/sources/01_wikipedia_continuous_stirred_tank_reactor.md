# Continuous stirred-tank reactor

[Figure: Diagram showing the setup of a continuous stirred-tank reactor]

The **continuous stirred-tank reactor** (**CSTR**), also known as **vat-** or **backmix reactor**, **mixed flow reactor** (**MFR**), or a **continuous-flow stirred-tank reactor** (**CFSTR**), is a common model for a chemical reactor in chemical engineering and environmental engineering. A CSTR often refers to a model used to estimate the key unit operation variables when using a continuous agitated-tank reactor to reach a specified output. The mathematical model works for all fluids: liquids, gases, and slurries.

The behavior of a CSTR is often approximated or modeled by that of an ideal CSTR, which assumes perfect mixing. In a perfectly mixed reactor, reagent is instantaneously and uniformly mixed throughout the reactor upon entry. Consequently, the output composition is identical to composition of the material inside the reactor, which is a function of residence time and reaction rate. The CSTR is the ideal limit of complete mixing in reactor design, which is the complete opposite of a plug flow reactor (PFR). In practice, no reactors behave ideally but instead fall somewhere in between the mixing limits of an ideal CSTR and PFR.

## Ideal CSTR
[Figure: Cross-sectional diagram of a CSTR]

### Modeling
A continuous fluid flow containing non-conservative chemical reactant *A* enters an ideal CSTR of volume *V*.

#### Assumptions
* perfect or ideal mixing
* steady state $\Bigl(\frac{dN_A}{dt} = 0\Bigr)$, where *N<sub>A</sub>* is the number of moles of species *A*
* closed boundaries
* constant fluid density (valid for most liquids; valid for gases only if there is no net change in the number of moles or drastic temperature change)
* n<sup>th</sup>-order reaction (*r* = *kC<sub>A</sub><sup>n</sup>*), where *k* is the reaction rate constant, *C<sub>A</sub>* is the concentration of species *A,* and *n* is the order of the reaction
* isothermal conditions, or constant temperature (*k* is constant)
* single, irreversible reaction (*ν<sub>A</sub>* = −1)
* All reactant *A* is converted to products via chemical reaction
* *N<sub>A</sub>* = *C<sub>A</sub>* *V*

#### Governing equations
Integral mass balance on number of moles *N<sub>A</sub>* of species *A* in a reactor of volume *V*:

1. $[\text{Net accumulation of} ~A] = [A~\text{in}] - [A~\text{out}] + [\text{Net generation of} ~A]$

2. $\frac{dN_A}{dt} = F_{Ao} - F_A + V \nu_A r_A$

where
* *F<sub>Ao</sub>* is the molar flow rate inlet of species *A*
* *F<sub>A</sub>* is the molar flow rate outlet of species *A*
* *v<sub>A</sub>* is the stoichiometric coefficient
* *r<sub>A</sub>* is the reaction rate

Applying the assumptions of steady state and *ν<sub>A</sub>* = −1, Equation 2 simplifies to:

3. $0 = F_{Ao} - F_A - V  r_A$

The molar flow rates of species *A* can then be rewritten in terms of the concentration of *A* and the fluid flow rate (*Q*):

4. $0 = QC_{Ao} - QC_A - V  r_A$

Equation 4 can then be rearranged to isolate *r<sub>A</sub>* and simplified:

5. $r_A = \frac{Q}{V} (C_{Ao} - C_A)$

6. $r_A = \frac{1}{\tau} (C_{Ao} - C_A)$

where
* $\tau$ is the theoretical residence time (<u>$\tau = \tfrac{V}{Q}$</u>)
* *C<sub>Ao</sub>* is the inlet concentration of species A
* *C<sub>A</sub>* is the reactor/outlet concentration of species A

Residence time is the total amount of time a discrete quantity of reagent spends inside the reactor. For an ideal reactor, the theoretical residence time, <u>$\tau$</u>, is always equal to the reactor volume divided by the fluid flow rate. See the next section for a more in-depth discussion on the residence time distribution of a CSTR.

Depending on the order of the reaction, the reaction rate, *r<sub>A</sub>*, is generally dependent on the concentration of species *A* in the reactor and the rate constant. A key assumption when modeling a CSTR is that any reactant in the fluid is perfectly (i.e. uniformly) mixed in the reactor, implying that the concentration within the reactor is the same in the outlet stream. The rate constant can be determined using a known empirical reaction rate that is adjusted for temperature using the Arrhenius temperature dependence. Generally, as the temperature increases so does the rate at which the reaction occurs.

Equation 6 can be solved by integration after substituting the proper rate expression. The table below summarizes the outlet concentration of species *A* for an ideal CSTR. The values of the outlet concentration and residence time are major design criteria in the design of CSTRs for industrial applications.
Table: Outlet Concentration for an Ideal CSTR

| Reaction Order | *C<sub>A</sub>* |
|---|---|
| n=0 | $C_A = {C_{Ao}}-{k \tau }$ |
| n=1 | $C_A = \frac {C_{Ao}}{1 + k \tau }$ |
| n=2 | $C_A = \frac {-1 + \sqrt {1 + 4k\tau C_{Ao}}} {2k\tau}$ |
| Other n | Numerical solution required<br /> |

### Residence time distribution
[Figure: Exit age distribution E(t) and cumulative age distribution F(t) functions for an ideal CSTR]An ideal CSTR will exhibit well-defined flow behavior that can be characterized by the reactor's residence time distribution, or exit age distribution. Not all fluid particles will spend the same amount of time within the reactor. The exit age distribution (E(t)) defines the probability that a given fluid particle will spend time t in the reactor. Similarly, the cumulative age distribution (F(t)) gives the probability that a given fluid particle has an exit age less than time t. One of the key takeaways from the exit age distribution is that a very small number of fluid particles will never exit the CSTR. Depending on the application of the reactor, this may either be an asset or a drawback.

## Non-ideal CSTR
While the ideal CSTR model is useful for predicting the fate of constituents during a chemical or biological process, CSTRs rarely exhibit ideal behavior in reality. More commonly, the reactor hydraulics do not behave ideally or the system conditions do not obey the initial assumptions. Perfect mixing is a theoretical concept that is not achievable in practice. For engineering purposes, however, if the residence time is 5–10 times the mixing time, the perfect mixing assumption generally holds true.
[Figure: Exit age distribution E(t) and cumulative age distribution F(t) functions for a CSTR with dead space]
Non-ideal hydraulic behavior is commonly classified by either dead space or short-circuiting. These phenomena occur when some fluid spends less time in the reactor than the theoretical residence time, <s>$\tau$</s>. The presence of corners or baffles in a reactor often results in some dead space where the fluid is poorly mixed. Similarly, a jet of fluid in the reactor can cause short-circuiting, in which a portion of the flow exits the reactor much quicker than the bulk fluid. If dead space or short-circuiting occur in a CSTR, the relevant chemical or biological reactions may not finish before the fluid exits the reactor. Any deviation from ideal flow will result in a residence time distribution different from the ideal distribution, as seen at right.

### Modeling non-ideal flow
Although ideal flow reactors are seldom found in practice, they are useful tools for modeling non-ideal flow reactors. Any flow regime can be achieved by modeling a reactor as a combination of ideal CSTRs and plug flow reactors (PFRs) either in series or in parallel. For examples, an infinite series of ideal CSTRs is hydraulically equivalent to an ideal PFR. Reactor models combining a number of CSTRs in series are often termed tanks-in-series (TIS) models.

To model systems that do not obey the assumptions of constant temperature and a single reaction, additional dependent variables must be considered. If the system is considered to be in unsteady-state, a differential equation or a system of coupled differential equations must be solved. Deviations of the CSTR behavior can be considered by the dispersion model. CSTRs are known to be one of the systems which exhibit complex behavior such as steady-state multiplicity, limit cycles, and chaos.

## Cascades of CSTRs
[Figure: A series of three CSTRs]
Cascades of CSTRs, also known as a series of CSTRs, are used to decrease the volume of a system.

### Minimizing volume
[Figure: As the number of CSTRs in series increases, the total reactor volume decreases.]
As seen in the graph with one CSTR, where the inverse rate is plotted as a function of fractional conversion, the area in the box is equal to $\frac{V}{F_{Ao}}$ where V is the total reactor volume and $F_{Ao}$ is the molar flow rate of the feed. When the same process is applied to a cascade of CSTRs as seen in the graph with three CSTRs, the volume of each reactor is calculated from each inlet and outlet fractional conversion, therefore resulting in a decrease in total reactor volume. Optimum size is achieved when the area above the rectangles from the CSTRs in series that was previously covered by a single CSTR is maximized. For a first order reaction with two CSTRs, equal volumes should be used. As the number of ideal CSTRs (n) approaches infinity, the total reactor volume approaches that of an ideal PFR for the same reaction and fractional conversion.

### Ideal cascade of CSTRs
From the design equation of a single CSTR where $\tau = \frac{C_{Ao} - C_A}{-r_A}$, we can determine that for a single CSTR in series that $\tau_i = \frac{C_{A(i-1)}-C_{Ai}}{-r_{Ai}}$, where $\tau$ is the space time of the reactor, $C_{Ao}$ is the feed concentration of A, $C_{A}$ is the outlet concentration of A, and $-r_{A}$ is the rate of reaction of A.

#### First order
For an isothermal first order, constant density reaction in a cascade of identical CSTRs operating at steady state

For one CSTR:
$C_{A1} = \frac{C_{Ao}}{1 + k\tau}$, where k is the rate constant and $C_{A1}$ is the outlet concentration of A from the first CSTR

Two CSTRs:
$C_{A1} = \frac{C_{Ao}}{1 + k\tau}$ and $C_{A2} = \frac{C_{A1}}{1 + k\tau}$

Plugging in the first CSTR equation to the second:
$C_{A2} = \frac{C_{Ao}}{(1 + k\tau)^2}$

Therefore, for m identical CSTRs in series:
$C_{Am} = \frac{C_{Ao}}{(1 + k\tau)^m}$

When the volumes of the individual CSTRs in series vary, the order of the CSTRs does not change the overall conversion for a first order reaction as long as the CSTRs are run at the same temperature.

#### Zeroth order
At steady state, the general equation for an isothermal zeroth order reaction at in a cascade of CSTRs is given by $C_{Am} = C_{Ao} - \sum_{i=1}^{m} k_i\tau_i$

When the cascade of CSTRs is isothermal with identical reactors, the concentration is given by $C_{Am} = C_{Ao} - mk_i\tau_i$

#### Second order
For an isothermal second order reaction at steady state in a cascade of CSTRs, the general design equation is $C_{Ai} = \frac{-1 + \sqrt{1 + 4k_i\tau_iC_{A(i-1)}}}{2k_i\tau_i}$

### Non-ideal cascade of CSTRs
With non-ideal reactors, residence time distributions can be calculated. At the concentration at the jth reactor in series is given by

$\frac{C_j}{C_o} = 1 -e^{-\frac{nt}{\bar{t}}}[1 + \frac{nt}{\bar{t}} + \frac{1}{2!}(\frac{nt}{\bar{t}})^2 + ... + \frac{1}{(j-1)!}(\frac{nt}{\bar{t}})^{j-1}]$

where n is the total number of CSTRs in series, and $\bar{t}$ is the average residence time of the cascade given by $\bar{t} = \frac{V}{Q}$ where Q is the volumetric flow rate.

From this, the cumulative residence time distribution (F(t)) can be calculated as

$F(t) = \frac{C_n}{C_o} = 1 -e^{-\frac{nt}{\bar{t}}}[1 + \frac{nt}{\bar{t}} + \frac{1}{2!}(\frac{nt}{\bar{t}})^2 + ... + \frac{1}{(n-1)!}(\frac{nt}{\bar{t}})^{n-1}]$

As n → ∞, F(t) approaches the ideal PFR response. The variance associated with F(t) for a pulse stimulus into a cascade of CSTRs is $\sigma_{t}^2 = \frac{\bar{t}^2}{n}$.

### Cost
[Figure: Cost initially decreases with the number of CSTRs as volume decreases but as operational costs increase, the total cost eventually begins to increase.]
When determining the cost of a series of CSTRs, capital and operating costs must be taken into account. As seen above, an increase in the number of CSTRs in series will decrease the total reactor volume. Since cost scales with volume, capital costs are lowered by increasing the number of CSTRs. The largest decrease in cost, and therefore volume, occurs between a single CSTR and having two CSTRs in series. When considering operating cost, operating cost scales with the number of pumps and controls, construction, installation, and maintenance that accompany larger cascades. Therefore, as the number of CSTRs increases, the operating cost increases. Therefore, there is a minimum cost associated with a cascade of CSTRs.

#### Zeroth order reactions
From a rearrangement of the equation given for identical isothermal CSTRs running a zeroth order reaction: $\tau = \frac{C_{Ao} - C_{Am}}{mk}$, the volume of each individual CSTR will scale by $\frac{1}{m}$. Therefore, the total reactor volume is independent of the number of CSTRs for a zeroth order reaction. Therefore, cost is not a function of the number of reactors for a zeroth order reaction and does not decrease as the number of CSTRs increases.

### Selectivity of parallel reactions
When considering parallel reactions, utilizing a cascade of CSTRs can achieve greater selectivity for a desired product.

For a given parallel reaction $\ce{A -> B}$ and $\ce{A -> C}$ with constants $k_1$ and $k_2$ and rate equations $\frac{d[\ce B]}{dt}=k_1[\ce A]^{n_1}$   and   $\frac{d[\ce C]}{dt}=k_2[\ce A]^{n_2}$, respectively, we can obtain a relationship between the two by dividing $\frac{d[\ce B]}{dt}$ by $\frac{d[\ce C]}{dt}$. Therefore $\frac{d[\ce B]}{d[\ce C]} = \frac{k_1}{k_2}[\ce A]^{n_1 - n_2}$. In the case where $n_1 > n_2$ and B is the desired product, the cascade of CSTRs is favored with a fresh secondary feed of $\ce{A}$ in order to maximize the concentration of $\ce{A}$.

For a parallel reaction with two or more reactants such as $\ce{A + D -> B}$ and $\ce{A + D -> C}$ with constants $k_1$ and $k_2$ and rate equations $\frac{d[\ce B]}{dt}=k_1[\ce A]^{n_1}[\ce D]^{m_1}$   and   $\frac{d[\ce C]}{dt}=k_2[\ce A]^{n_2}[\ce D]^{m_12}$, respectively, we can obtain a relationship between the two by dividing $\frac{d[\ce B]}{dt}$ by $\frac{d[\ce C]}{dt}$. Therefore $\frac{d[\ce B]}{d[\ce C]} = \frac{k_1}{k_2}[\ce A]^{n_1 - n_2}[\ce D]^{m_1 - m_2}$. In the case where $n_1 > n_2$ and $m_1 > m_2$ and B is the desired product, a cascade of CSTRs with an inlet stream of high $\ce{[A]}$ and $\ce{[D]}$ is favored. In the case where $n_1 > n_2$ and $m_1 < m_2$ and B is the desired product, a cascade of CSTRs with a high concentration of $\ce{A}$ in the feed and small secondary streams of $\ce{D}$ is favored.

Series reactions such as $\ce{A -> B -> C}$ also have selectivity between $\ce{B}$ and $\ce{C}$ but CSTRs in general are typically not chosen when the desired product is $\ce{B}$ as the back mixing from the CSTR favors $\ce{C}$. Typically a batch reactor or PFR is chosen for these reactions.

## Applications
CSTRs facilitate rapid dilution of reagents through mixing. Therefore, for non-zero-order reactions, the low concentration of reagent in the reactor means a CSTR will be less efficient at removing the reagent compared to a PFR with the same residence time. Therefore, CSTRs are typically larger than PFRs, which may be a challenge in applications where space is limited. However, one of the added benefits of dilution in CSTRs is the ability to neutralize shocks to the system. As opposed to PFRs, the performance of CSTRs is less susceptible to changes in the influent composition, which makes it ideal for a variety of industrial applications:
[Figure: Anaerobic digesters at Newtown Creek Wastewater Treatment Plant in Greenpoint, Brooklyn]

### Environmental engineering
* Activated sludge process for wastewater treatment
* Lagoon treatment systems for natural wastewater treatment
* Anaerobic digesters for the stabilization of wastewater biosolids
* Treatment wetlands for wastewater and storm water runoff

### Chemical engineering
* Loop reactor for production of pharmaceuticals
* Fermentation
* Biogas production

## See also
*Laminar flow reactor
*Microreactor
*Oscillatory baffled reactor
*Plug flow reactor model
