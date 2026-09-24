"""C6 / Tier 2: the modelling constraints Tier 1 cannot express, shown to be numerically real.

Decision C-01 makes Tier 1 a causal directed-flow abstraction, which is the right default --
no pressure network, no nonlinear algebraic systems, reliable integration on an unseen packet.
The declared cost (OPEN-ISSUE-04) is that REQ-MOD-004/005/006 have no *numerical* effect there:
they are honoured on paper and nothing in the equations depends on them.

These tests are the evidence that Tier 2 closes that. Each asserts a number the requirement
predicts, not that a file exists.

All of them run `omc`, so they are marked slow.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from specalive.verify.omc import OmcRunner

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "modelica" / "SpecAliveFluid.mo"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def staged(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tier2")
    shutil.copy(LIB, d / LIB.name)
    return d


def _columns(path: Path) -> dict[str, list[float]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out: dict[str, list[float]] = {k: [] for k in rows[0]}
    for r in rows:
        for k, v in r.items():
            try:
                out[k].append(float(v))
            except (TypeError, ValueError):
                out[k].append(float("nan"))
    return out


@pytest.fixture(scope="module")
def charge_leg(staged) -> dict[str, list[float]]:
    runner = OmcRunner(workdir=str(staged / "omc"))
    res = runner.simulate(
        "SpecAliveFluid.Examples.ChargeLeg",
        [staged / LIB.name],
        libraries=["Modelica"],
        stop_time=400,
        interval=1,
    )
    assert res.ok, res.summary()
    assert res.result_file is not None
    return _columns(Path(res.result_file))


def test_the_acausal_leg_compiles_and_simulates(charge_leg):
    """Tier 2 is only worth anything if it runs. The packet warns the acausal variant is where
    the legacy study got into trouble, so this is not a formality."""
    assert len(charge_leg["time"]) > 100


def test_req_mod_004_port_crossing_actually_switches(charge_leg):
    """B3's inlet sits at 0.10 m and the level starts at 0.005 m, so the port is crossed.

    MSL implements the requirement natively (Fluid/Vessels.mo:336): `ports_penetration` is a
    regStep whose hysteresis width is 0.1 x the port diameter, and it multiplies zeta_in while
    dividing zeta_out -- regularized and asymmetric, exactly as REQ-MOD-004 specifies. If the
    value never leaves its floor, the treatment is inert and the requirement is decorative.
    """
    pen = charge_leg["B3.ports_penetration[1]"]
    level = charge_leg["B3.level"]
    assert min(pen) < 0.01, "penetration never sat at its blocked value"
    assert max(pen) > 0.99, "penetration never opened: the port crossing did nothing"

    # And it must switch *at the port*, not somewhere arbitrary.
    crossing = next(i for i, p in enumerate(pen) if p > 0.5)
    assert 0.09 <= level[crossing] <= 0.12, f"switched at level {level[crossing]:.4f}, not ~0.10"


def test_req_mod_005_junction_volume_carries_its_own_state(charge_leg):
    """The junction sits between a pipe and a valve, both pressure-drop-only. If it has no
    state of its own that node is undefined when the valve shuts."""
    p = charge_leg["J1.medium.p"]
    assert max(p) - min(p) > 1000, "junction pressure is constant, so it is not a state"
    # Distinct from ambient: it is genuinely solving, not inheriting a boundary.
    assert max(p) > 101325 + 1000


def test_req_mod_006_static_head_matches_rho_g_dz(charge_leg):
    """The leg falls 1.32 m. Predicted head is rho*g*dz ~ 998 * 9.81 * 1.32 ~ 12.9 kPa, and it
    dominates the friction term -- so if gravity were missing the number would be nowhere near.
    """
    dp = [a - b for a, b in zip(charge_leg["downcomer.port_a.p"], charge_leg["downcomer.port_b.p"])]
    flowing = [d for d, m in zip(dp, charge_leg["V8.port_a.m_flow"]) if m > 1e-4]
    assert flowing, "no flow in the run, so the head was never exercised"
    predicted = -998.0 * 9.81 * 1.32
    worst = max(abs(d - predicted) / abs(predicted) for d in flowing)
    assert worst < 0.05, f"static head off by {worst:.1%} from rho*g*dz"


def test_the_leg_reproduces_the_supplied_step1_duration(charge_leg):
    """Calibration against evidence rather than a guess: the supplied trace runs Step1 from
    t=20 s to t=180 s, and valve sizing (ASSUMPTION A-01) was fitted to that 160 s window."""
    t = charge_leg["time"]
    done = charge_leg["step1Complete"]
    finish = next(t[i] for i, v in enumerate(done) if v > 0.5)
    assert 140 <= finish <= 180, f"Step1 finished at {finish:.0f}s, expected ~160s"


def test_req_mod_005_is_demonstrated_by_the_pair_that_needs_it(staged):
    """The honest version of this demonstration, after the obvious one failed.

    Shrinking `ChargeLeg`'s junction towards zero changed nothing (1.56 s vs 1.38 s, noise),
    because REQ-MOD-005 asks for a junction where *multiple* isolating elements bracket a node
    and the charge leg has only one valve. With two valves closing on the same node the
    difference is unambiguous: omc's default linear solver fails at exactly the isolation
    instant without the junction, and does not with it.

    The run still completes either way -- the fallback solver rescues it -- which is precisely
    why this needs demonstrating: the failure is silent unless someone reads the log.
    """
    runner = OmcRunner(workdir=str(staged / "omc2"))
    files = [staged / LIB.name]

    good = runner.simulate("SpecAliveFluid.Examples.IsolatedNode", files,
                           libraries=["Modelica"], stop_time=3)
    bad = runner.simulate("SpecAliveFluid.Examples.IsolatedNodeNoJunction", files,
                          libraries=["Modelica"], stop_time=3)
    assert good.ok and bad.ok, "both are expected to complete; the difference is in the log"

    def solver_failed(res) -> bool:
        return "default linear solver fails" in (res.stdout or "").lower()

    assert solver_failed(bad), "removing the junction did not degrade the solve"
    assert not solver_failed(good), "the junction did not prevent the degraded solve"


def test_the_waternacl_gap_is_declared_in_the_source(staged):
    """GAP-MEDIUM-01. Four of the five required properties have no coefficients anywhere in the
    packet, so the medium is not reconstructible. Inventing them would compile, simulate and be
    wrong. The one correlation that WAS supplied is implemented; the rest is declared."""
    text = LIB.read_text(encoding="utf-8")
    assert "GAP-MEDIUM-01" in text
    assert "dynamicViscosity_WaterNaCl" in text
    assert "-6.83241e-07" in text, "the supplied viscosity coefficients should be used verbatim"
    for missing in ("rho", "p_sat", "cp"):
        assert missing in text, f"the gap should name {missing} as unreconstructible"
