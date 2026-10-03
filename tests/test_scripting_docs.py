"""Real-time grounding in the OpenModelica Scripting API: fetch, parse, cache, and fail
silently. No real network access here -- httpx is monkeypatched -- so these run in the fast
suite and prove the module's own logic rather than the site's current uptime."""

from __future__ import annotations

import pytest

from specalive.llm.scripting_docs import _render, fetch_function_doc, render_lookup

SAMPLE_HTML = """
<div class="om-summary">Saves a model and dependencies to a single file.</div>
<section id="info"><h2>Information</h2>
<p>Save the <code>className</code> model in a single file.</p></section>
<section id="inputs"><h2>Inputs</h2>
<table><tbody>
<tr id="c-fileName"><td class="om-type">String</td><td class="om-name">fileName</td><td class="om-default"></td><td></td></tr>
<tr id="c-className"><td class="om-type">TypeName</td><td class="om-name">className</td><td class="om-default"></td><td></td></tr>
<tr id="c-stripAnnotations"><td class="om-type">Boolean</td><td class="om-name">stripAnnotations</td><td class="om-default">false</td><td></td></tr>
</tbody></table></section>
<section id="outputs"><h2>Outputs</h2>
<table><tbody>
<tr id="c-success"><td class="om-type">Boolean</td><td class="om-name">success</td><td class="om-default"></td><td></td></tr>
</tbody></table></section>
"""


def test_render_extracts_signature_and_description_from_the_real_page_shape():
    out = _render("saveTotalModel", SAMPLE_HTML)
    assert out is not None
    assert "saveTotalModel(fileName: String, className: TypeName, stripAnnotations: Boolean = false)" in out
    assert "-> success: Boolean" in out
    assert "Saves a model and dependencies to a single file." in out
    assert "Save the className model in a single file." in out


def test_render_returns_none_for_a_page_that_is_not_a_function_doc():
    assert _render("whatever", "<html><body>404 not found</body></html>") is None


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_fetch_returns_none_on_404(monkeypatch, tmp_path):
    monkeypatch.setattr("httpx.get", lambda *a, **kw: _Resp(404))
    assert fetch_function_doc("doesNotExist", cache_dir=tmp_path) is None


def test_fetch_returns_none_on_network_error(monkeypatch, tmp_path):
    def boom(*a, **kw):
        raise OSError("no network")

    monkeypatch.setattr("httpx.get", boom)
    assert fetch_function_doc("saveTotalModel", cache_dir=tmp_path) is None


def test_fetch_caches_to_disk_and_does_not_refetch(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_get(*a, **kw):
        calls["n"] += 1
        return _Resp(200, SAMPLE_HTML)

    monkeypatch.setattr("httpx.get", fake_get)
    first = fetch_function_doc("saveTotalModel", cache_dir=tmp_path)
    second = fetch_function_doc("saveTotalModel", cache_dir=tmp_path)
    assert first and first == second
    assert calls["n"] == 1, "the second call must be served from the cache, not the network"
    assert (tmp_path / "saveTotalModel.txt").exists()


@pytest.mark.parametrize("bad", ["../etc/passwd", "rm -rf /", "a b", "", "a;b", "a/b"])
def test_an_invalid_function_name_is_refused_before_any_network_call(monkeypatch, bad, tmp_path):
    def must_not_be_called(*a, **kw):
        raise AssertionError("fetch_function_doc must not reach the network for an invalid name")

    monkeypatch.setattr("httpx.get", must_not_be_called)
    assert fetch_function_doc(bad, cache_dir=tmp_path) is None


def test_render_lookup_reports_not_found_without_fabricating_a_signature(monkeypatch, tmp_path):
    monkeypatch.setattr("httpx.get", lambda *a, **kw: _Resp(404))
    out = render_lookup(["notARealFunction"], cache_dir=tmp_path)
    assert "VERIFIED OPENMODELICA SCRIPTING API DOCUMENTATION" in out
    assert "NOT FOUND" in out and "do not guess" in out
