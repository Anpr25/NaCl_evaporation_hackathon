"""The judge packet: one self-contained HTML file plus machine-readable JSON.

Written so that a reviewer who has never seen the project can, in one scroll, answer:
does it compile, does it run, does it meet the acceptance criteria, where did every number
come from, what did we get wrong, and how much of it did a language model actually do.

The honesty sections are not an afterthought -- gaps, provisional decisions and declared
deviations render above the pretty parts, on purpose.

Owner: D.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ir.system import SystemModel
from .acceptance import Scorecard

CSS = """
:root{--bg:#fff;--fg:#14161a;--mut:#5b6472;--line:#e3e6ea;--ok:#10725a;--okbg:#e8f5f1;
--bad:#a3282d;--badbg:#fdecec;--warn:#8a5a00;--warnbg:#fff6e0;--acc:#1d4ed8;--code:#f6f7f9;}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--fg:#e6e8ec;
--mut:#9aa3b2;--line:#252a33;--ok:#4ade80;--okbg:#0f2a20;--bad:#f87171;--badbg:#2a1213;
--warn:#fbbf24;--warnbg:#2a2110;--acc:#7aa2ff;--code:#161a21;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:1.9rem;margin:.2em 0}h2{font-size:1.25rem;margin:2.2em 0 .6em;
padding-bottom:.3em;border-bottom:1px solid var(--line)}h3{font-size:1rem;margin:1.4em 0 .4em}
.sub{color:var(--mut);margin:0 0 1.5em}
.gate{display:flex;gap:12px;flex-wrap:wrap;margin:1.5em 0}
.card{flex:1 1 180px;border:1px solid var(--line);border-radius:10px;padding:14px}
.card .k{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.card .v{font-size:1.5rem;font-weight:650;margin-top:4px}
.pass{color:var(--ok)}.fail{color:var(--bad)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;margin:.8em 0;font-size:.88rem}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--mut);font-size:.74rem;letter-spacing:.05em;text-transform:uppercase}
tr.ok td:first-child{border-left:3px solid var(--ok)}
tr.no td:first-child{border-left:3px solid var(--bad)}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.84em}
code{background:var(--code);padding:1px 5px;border-radius:4px}
pre{background:var(--code);padding:12px;border-radius:8px;overflow-x:auto}
.note{border-left:3px solid var(--warn);background:var(--warnbg);padding:10px 14px;
border-radius:0 8px 8px 0;margin:.8em 0}
.good{border-left:3px solid var(--ok);background:var(--okbg);padding:10px 14px;
border-radius:0 8px 8px 0;margin:.8em 0}
.bad{border-left:3px solid var(--bad);background:var(--badbg);padding:10px 14px;
border-radius:0 8px 8px 0;margin:.8em 0}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:.74rem;
border:1px solid var(--line);color:var(--mut)}
.bar{height:8px;border-radius:99px;background:var(--line);overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:var(--acc)}
@media(max-width:640px){.wrap{padding:20px 16px 60px}.card{flex:1 1 100%}}
"""


def _e(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _rows(headers: list[str], rows: list[list[Any]], classes: list[str] | None = None) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = []
    for i, r in enumerate(rows):
        cls = f' class="{classes[i]}"' if classes else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def build_report(
    model: SystemModel,
    *,
    out_dir: str | Path = "out",
    gate: dict[str, Any] | None = None,
    scorecard: Scorecard | None = None,
    router_stats: dict[str, Any] | None = None,
    repair_steps: list[Any] | None = None,
    validation: Any | None = None,
    environment: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cov = model.coverage()
    gate = gate or {}
    p: list[str] = []

    compiled = bool(gate.get("compiled"))
    simulated = bool(gate.get("simulated"))

    p.append(f"<h1>{_e(model.name)}</h1>")
    p.append(
        f'<p class="sub">SpecAlive run &middot; {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} '
        f"&middot; {len(model.sources)} evidence sources &middot; "
        f"domains: {_e(', '.join(model.domains))}</p>"
    )

    # ---------------------------------------------------------------- gate cards
    cards = [
        ("Modelica compiles", "PASS" if compiled else "FAIL", "pass" if compiled else "fail"),
        ("Simulation runs", "PASS" if simulated else "FAIL", "pass" if simulated else "fail"),
    ]
    if scorecard:
        good = scorecard.ok
        cards.append(
            (
                "Acceptance checks",
                f"{scorecard.passed}/{scorecard.total}",
                "pass" if good else ("warn" if scorecard.passed else "fail"),
            )
        )
    cards.append(
        (
            "Requirements satisfied",
            f"{cov['requirements_satisfied']}/{cov['requirements_active']}",
            "pass" if cov["requirements_satisfied"] == cov["requirements_active"] else "warn",
        )
    )
    cards.append(("Declared gaps", str(cov["gaps"]), "warn" if cov["gaps"] else "pass"))
    p.append('<div class="gate">')
    for k, v, cls in cards:
        p.append(f'<div class="card"><div class="k">{_e(k)}</div><div class="v {cls}">{_e(v)}</div></div>')
    p.append("</div>")

    # ---------------------------------------------------------------- honesty first
    p.append("<h2>Declared gaps and deviations</h2>")
    if model.gaps:
        p.append(
            _rows(
                ["Id", "Kind", "Subject", "Detail", "Workaround"],
                [
                    [_e(g.id), f'<span class="pill">{_e(g.kind)}</span>', _e(g.subject),
                     _e(g.detail), _e(g.workaround or "-")]
                    for g in model.gaps
                ],
                ["no" if g.severity == "blocking" else "" for g in model.gaps],
            )
        )
    else:
        p.append('<div class="good">No gaps declared. Verify that is true before claiming it.</div>')

    provisional = [d for d in model.decisions if d.provisional]
    if provisional:
        p.append("<h3>Open questions (no precedence rule discriminated)</h3>")
        p.append(
            _rows(
                ["Subject", "Attribute", "Provisional value", "Why unresolved"],
                [
                    [_e(d.subject), _e(d.predicate),
                     _e(getattr(model.claim(d.winner_claim_id), "value", "?")), _e(d.rationale)]
                    for d in provisional
                ],
            )
        )

    # ---------------------------------------------------------------- acceptance
    if scorecard:
        p.append("<h2>Acceptance</h2>")
        if scorecard.reference_consistent is False:
            p.append(
                '<div class="bad"><b>Supplied reference data failed the physical-consistency '
                "screen.</b><br>" + "<br>".join(_e(n) for n in scorecard.reference_notes) + "</div>"
            )
        elif scorecard.reference_notes:
            p.append('<div class="good">' + "<br>".join(_e(n) for n in scorecard.reference_notes) + "</div>")
        p.append(
            _rows(
                ["Check", "Requirement", "Result", "Evidence"],
                [
                    [_e(r.check_id), _e(", ".join(r.requirement_ids) or "-"),
                     f'<b class="{"pass" if r.passed else "fail"}">{r.icon()}</b>', _e(r.detail)]
                    for r in scorecard.results
                ],
                ["ok" if r.passed else "no" for r in scorecard.results],
            )
        )
        if scorecard.signal_errors:
            p.append("<h3>Signal agreement (secondary)</h3>")
            p.append(
                _rows(
                    ["Signal", "Normalised RMSE"],
                    [[_e(k), f"{v:.4f}"] for k, v in sorted(scorecard.signal_errors.items())],
                )
            )

    # ---------------------------------------------------------------- traceability
    p.append("<h2>Traceability matrix</h2>")
    p.append(
        '<p class="sub">Every active requirement, the model elements that satisfy it, and the '
        "check that verifies it. A blank cell is a real gap, not a formatting artefact.</p>"
    )
    trace_rows, trace_cls = [], []
    for r in model.requirements:
        if r.status != "active":
            continue
        sat = ", ".join(f"<code>{_e(s)}</code>" for s in r.satisfied_by) or "&mdash;"
        ver = ", ".join(f"<code>{_e(v)}</code>" for v in r.verified_by) or "&mdash;"
        ev = ", ".join(
            f"<code>{_e(model.claim(c).ref())}</code>" for c in r.provenance.claim_ids[:2] if model.claim(c)
        )
        trace_rows.append([_e(r.id), _e(r.text[:150]), sat, ver, ev or "&mdash;"])
        trace_cls.append("ok" if r.satisfied_by else "no")
    p.append(_rows(["Requirement", "Text", "Satisfied by", "Verified by", "Evidence"], trace_rows, trace_cls))

    superseded = [r for r in model.requirements if r.status == "superseded"]
    if superseded:
        p.append("<h3>Superseded requirements (deliberately not implemented)</h3>")
        p.append(
            _rows(
                ["Requirement", "Text", "Superseded by"],
                [[_e(r.id), _e(r.text[:150]), _e(r.superseded_by or "?")] for r in superseded],
            )
        )

    # ---------------------------------------------------------------- decisions
    p.append("<h2>Conflict resolutions</h2>")
    contested = [d for d in model.decisions if d.loser_claim_ids]
    if contested:
        p.append(
            _rows(
                ["Subject", "Attribute", "Winner", "Rule", "Rationale", "Trap avoided"],
                [
                    [
                        _e(d.subject),
                        _e(d.predicate),
                        f"<code>{_e(getattr(model.claim(d.winner_claim_id), 'ref', lambda: '?')())}</code>",
                        f'<span class="pill">{_e(d.rule_id)}</span>',
                        _e(d.rationale),
                        _e(d.failure_mode or "-"),
                    ]
                    for d in contested
                ],
            )
        )
    else:
        p.append('<p class="sub">No contested facts: every attribute had a single source.</p>')

    # ---------------------------------------------------------------- generation
    p.append("<h2>How the model was generated</h2>")
    tiers = cov["binding_tiers"]
    total_bound = sum(tiers.values()) or 1
    p.append(
        _rows(
            ["Tier", "What it means", "Blocks", "Share"],
            [
                ["L0", "bound to a harvested catalog class", tiers.get("L0", 0),
                 _bar(tiers.get("L0", 0) / total_bound)],
                ["L1", "bound to a SpecAlive template", tiers.get("L1", 0),
                 _bar(tiers.get("L1", 0) / total_bound)],
                ["L2", "equations authored by a model", tiers.get("L2", 0),
                 _bar(tiers.get("L2", 0) / total_bound)],
                ["unbound", "no binding found (declared gap)", tiers.get("unbound", 0),
                 _bar(tiers.get("unbound", 0) / total_bound)],
            ],
        )
    )
    p.append(
        f'<p class="sub">{cov["claims_deterministic_pct"]}% of the {cov["claims"]} evidence claims '
        "were extracted by deterministic parsers rather than by a language model.</p>"
    )

    if repair_steps:
        p.append("<h3>Compile-repair loop</h3>")
        p.append(
            _rows(
                ["Iter", "Diagnostic", "Method", "Change", "Errors", "Kept"],
                [
                    [s.iteration, _e(s.kind), f'<span class="pill">{_e(s.method)}</span>',
                     _e(s.description), f"{s.errors_before} &rarr; {s.errors_after}",
                     "yes" if s.accepted else "no"]
                    for s in repair_steps
                ],
                ["ok" if s.accepted else "no" for s in repair_steps],
            )
        )

    if router_stats:
        p.append("<h3>Model usage</h3>")
        p.append(
            f'<p class="sub">Mode <code>{_e(router_stats.get("mode"))}</code> &middot; '
            f'{router_stats.get("total_calls", 0)} calls &middot; '
            f'{router_stats.get("cache_hits", 0)} cache hits &middot; '
            f'{router_stats.get("escalations", 0)} escalations.</p>'
        )
        p.append(
            _rows(
                ["Tier", "Calls", "Tokens", "Seconds", "From cache"],
                [
                    [_e(t), v["calls"], v["tokens"], v["latency_s"], v["cached"]]
                    for t, v in sorted((router_stats.get("by_tier") or {}).items())
                ],
            )
        )

    # ---------------------------------------------------------------- inputs / env
    p.append("<h2>Evidence read</h2>")
    p.append(
        _rows(
            ["Id", "File", "Authority", "Status", "Basis"],
            [
                [_e(s.id), _e(s.filename), f'<span class="pill">{_e(s.authority.value)}</span>',
                 _e(s.status.value), _e(s.classification_basis)]
                for s in model.sources
            ],
        )
    )

    if validation is not None and getattr(validation, "findings", None):
        p.append("<h2>Static checks on the extracted model</h2>")
        p.append(
            _rows(
                ["Check", "Severity", "Subject", "Message"],
                [
                    [_e(f.check), _e(f.severity), _e(f.subject), _e(f.message)]
                    for f in validation.findings
                ],
                ["no" if f.severity == "error" else "" for f in validation.findings],
            )
        )

    p.append("<h2>Reproducing this run</h2>")
    env = environment or {}
    p.append(f"<pre>{_e(json.dumps(env, indent=2))}</pre>")
    if artifacts:
        p.append(
            _rows(["Artifact", "Path"], [[_e(k), f"<code>{_e(v)}</code>"] for k, v in artifacts.items()])
        )

    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(model.name)} &mdash; SpecAlive</title><style>{CSS}</style></head>"
        f"<body><div class='wrap'>{''.join(p)}</div></body></html>"
    )
    path = out_dir / "report.html"
    path.write_text(doc, encoding="utf-8")

    (out_dir / "report.json").write_text(
        json.dumps(
            {
                "name": model.name,
                "generated": datetime.now(timezone.utc).isoformat(),
                "gate": gate,
                "coverage": cov,
                "acceptance": [asdict(r) for r in (scorecard.results if scorecard else [])],
                "reference_consistent": scorecard.reference_consistent if scorecard else None,
                "reference_notes": scorecard.reference_notes if scorecard else [],
                "router": router_stats or {},
                "repair": [asdict(s) if is_dataclass(s) else str(s) for s in (repair_steps or [])],
                "gaps": [g.model_dump() for g in model.gaps],
                "environment": env,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def _bar(frac: float) -> str:
    pct = max(0, min(100, round(frac * 100)))
    return f'{pct}%<div class="bar"><i style="width:{pct}%"></i></div>'
