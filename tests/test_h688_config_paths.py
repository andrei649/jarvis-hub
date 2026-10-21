"""H688 — config keys whose name contains a dot can be addressed, into nested values too.

The grammar (agents/core/settings_path.py): segments split at dots, ``\\.`` escapes a dot,
a quoted segment is exact, plain runs match the existing keys greedily and an ambiguous
run is refused; a write never creates a phantom key beside a dotted key. The CLI uses the
same parser for ``config get``, ``set`` and the new ``unset``.
"""

from __future__ import annotations

import io

import pytest

from agents.cli.nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, main
from agents.core import settings_db
from agents.core import settings_path as sp


def _texts(name):
    return [(s.text, s.strict) for s in sp.parse(name)]


# ── the parser ───────────────────────────────────────────────────────────────


def test_parse_splits_at_plain_dots_and_keeps_escaped_and_quoted_ones():
    assert _texts("a.b.c") == [("a", False), ("b", False), ("c", False)]
    assert _texts(r"a.ui\.theme") == [("a", False), ("ui.theme", True)]
    assert _texts('a."ui.theme".x') == [("a", False), ("ui.theme", True), ("x", False)]
    assert _texts(r'a."q\"uote".b\\c') == [("a", False), ('q"uote', True), ("b\\c", True)]
    assert _texts('a.""') == [("a", False), ("", True)]


@pytest.mark.parametrize("bad", ["", "a..b", ".a", "a.", 'a."open', 'a."x"y', 'a.b"c', "a\\"])
def test_parse_refuses_malformed_names(bad):
    with pytest.raises(sp.PathError):
        sp.parse(bad)


def test_render_round_trips_strict_keys():
    segs = [sp.Segment("ui.theme", True), sp.Segment("x"), sp.Segment('q"', True)]
    assert [(s.text, s.strict) for s in sp.parse("c." + sp.render(segs))][1:] == [
        ("ui.theme", True), ("x", False), ('q"', True)]


# ── resolving the setting (a declared key may itself contain dots) ───────────


def test_resolve_setting_matches_a_dotted_declared_key_greedily():
    declared = {("net", "proxy.url"), ("net", "proxy"), ("llm", "model")}
    with pytest.raises(sp.AmbiguousPath) as exc:
        sp.resolve_setting("net.proxy.url", declared)
    assert '"proxy.url"' in str(exc.value) and '"proxy"' in str(exc.value)
    assert sp.resolve_setting(r"net.proxy\.url", declared)[:2] == ("net", "proxy.url")
    cat, key, rest = sp.resolve_setting('net."proxy".url', declared)
    assert (cat, key, [s.text for s in rest]) == ("net", "proxy", ["url"])
    only_dotted = {("net", "proxy.url")}
    assert sp.resolve_setting("net.proxy.url", only_dotted) == ("net", "proxy.url", [])
    assert sp.resolve_setting("net.nope", only_dotted) is None
    with pytest.raises(sp.PathError):
        sp.resolve_setting("net", only_dotted)


# ── get/set/unset inside a nested value ──────────────────────────────────────


def test_get_set_unset_address_a_dotted_key_inside_a_value_consistently():
    value = {"ui.theme": "dark", "layout": {"side.bar": {"width": 3}}, "list": [1, {"a.b": 2}]}
    for spelling in ("ui.theme", r"ui\.theme", '"ui.theme"'):
        segs = sp.parse(spelling)
        assert sp.get_in(value, segs) == "dark"
        assert sp.set_in(value, segs, "light")["ui.theme"] == "light"
        assert "ui.theme" not in sp.unset_in(value, segs)
        assert "ui" not in sp.set_in(value, segs, "light")      # no phantom "ui" object
    assert sp.get_in(value, sp.parse("layout.side.bar.width")) == 3
    assert sp.set_in(value, sp.parse("layout.side.bar.width"), 4)["layout"]["side.bar"] == {"width": 4}
    assert sp.get_in(value, sp.parse("list.1.a.b")) == 2
    assert value["ui.theme"] == "dark"                           # the input is never mutated


def test_a_write_refuses_a_phantom_intermediate_beside_a_dotted_key():
    value = {"ui.theme": "dark"}
    with pytest.raises(sp.PhantomIntermediate) as exc:
        sp.set_in(value, sp.parse("ui.font"), "mono")
    assert '"ui.theme"' in str(exc.value) and '"ui"' in str(exc.value)
    # Said on purpose: a separate key "ui" (quoted) or one dotted key (escaped).
    assert sp.set_in(value, sp.parse('"ui".font'), "mono") == {"ui.theme": "dark", "ui": {"font": "mono"}}
    assert sp.set_in(value, sp.parse(r"ui\.font"), "mono") == {"ui.theme": "dark", "ui.font": "mono"}
    # Nothing dotted beside it: new objects are created on the way.
    assert sp.set_in({}, sp.parse("a.b.c"), 1) == {"a": {"b": {"c": 1}}}


def test_ambiguous_and_missing_paths_fail_loudly():
    value = {"a": {"b": 1}, "a.b": 2}
    for op in (lambda s: sp.get_in(value, s), lambda s: sp.set_in(value, s, 0), lambda s: sp.unset_in(value, s)):
        with pytest.raises(sp.AmbiguousPath):
            op(sp.parse("a.b"))
    assert sp.get_in(value, sp.parse('"a"."b"')) == 1
    assert sp.get_in(value, sp.parse('"a.b"')) == 2
    with pytest.raises(sp.PathError):
        sp.get_in(value, sp.parse("nope"))
    with pytest.raises(sp.PathError):
        sp.unset_in(value, sp.parse("nope"))
    with pytest.raises(sp.PathError):
        sp.get_in({"x": 1}, sp.parse("x.y"))                      # into a scalar
    with pytest.raises(sp.PathError):
        sp.set_in({"l": [1]}, sp.parse("l.5"), 0)                 # past a list's end
    with pytest.raises(sp.PathError):
        sp.get_in({"l": [1]}, sp.parse("l.x"))                    # not an index


# ── the CLI: config get / set / unset with dotted names ─────────────────────


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_cli_reads_and_writes_a_dotted_key_inside_a_json_setting(temp_settings):
    settings_db.put_category("appearance", {"preferences": {"ui.theme": "dark", "panel": {"w.px": 3}}})

    code, out, _ = _run(["config", "get", "appearance.preferences.ui.theme"])
    assert code == EXIT_OK and out.strip() == '"dark"'
    code, out, _ = _run(["config", "get", r"appearance.preferences.panel.w\.px"])
    assert code == EXIT_OK and out.strip() == "3"

    code, out, _ = _run(["config", "set", "appearance.preferences.ui.theme", "light"])
    assert code == EXIT_OK and 'appearance.preferences.ui.theme = "light"' in out
    code, _, _ = _run(["config", "set", "appearance.preferences.panel.w.px", "7"])
    assert code == EXIT_OK
    assert settings_db.get_value("appearance", "preferences") == {"ui.theme": "light", "panel": {"w.px": 7}}

    code, _, err = _run(["config", "set", "appearance.preferences.ui.font", "mono"])
    assert code == EXIT_FAILED and "refusing to create" in err and '"ui.theme"' in err
    assert settings_db.get_value("appearance", "preferences") == {"ui.theme": "light", "panel": {"w.px": 7}}

    code, _, _ = _run(["config", "set", r"appearance.preferences.ui\.font", "mono"])
    assert code == EXIT_OK and settings_db.get_value("appearance", "preferences")["ui.font"] == "mono"

    code, out, _ = _run(["config", "unset", "appearance.preferences.ui.theme"])
    assert code == EXIT_OK and "removed" in out
    assert settings_db.get_value("appearance", "preferences") == {"panel": {"w.px": 7}, "ui.font": "mono"}

    code, _, err = _run(["config", "unset", "appearance.preferences.ui.theme"])
    assert code == EXIT_FAILED and "no " in err

    code, _, err = _run(["config", "get", "appearance.preferences.nope"])
    assert code == EXIT_FAILED and "nope" in err


def test_cli_unset_puts_a_whole_setting_back_to_its_declared_value(temp_settings):
    settings_db.put_category("llm", {"tool_loop_max_iterations": 12})
    code, out, _ = _run(["config", "unset", "llm.tool_loop_max_iterations"])
    default = settings_db._SPEC[("llm", "tool_loop_max_iterations")]["value"]
    assert code == EXIT_OK and "declared value" in out
    assert settings_db.get_value("llm", "tool_loop_max_iterations") == default

    code, _, err = _run(["config", "unset", "llm.no_such_key"])
    assert code == EXIT_FAILED and "not a declared setting" in err
    code, _, err = _run(["config", "unset", "skills.disabled"])
    assert code == EXIT_FAILED and "nerva skills" in err


def test_cli_refuses_a_path_below_a_setting_that_holds_no_object(temp_settings):
    code, _, err = _run(["config", "set", "llm.tool_loop_enabled.x", "on"])
    assert code == EXIT_FAILED and "nothing is inside it" in err
    code, _, err = _run(["config", "get", "appearance..preferences"])
    assert code == EXIT_USAGE and "empty segment" in err


def test_cli_addresses_a_declared_key_whose_name_contains_a_dot(temp_settings, monkeypatch):
    spec = {"category": "appearance", "key": "font.family", "value": "sans", "label": "Font family", "kind": "text"}
    monkeypatch.setattr(settings_db, "DEFAULTS", [*settings_db.DEFAULTS, spec])
    monkeypatch.setitem(settings_db._SPEC, ("appearance", "font.family"), spec)

    code, out, _ = _run(["config", "get", "appearance.font.family"])
    assert code == EXIT_OK and out.strip() == '"sans"'
    code, _, _ = _run(["config", "set", "appearance.font.family", "serif"])
    assert code == EXIT_OK and settings_db.get_value("appearance", "font.family") == "serif"
    code, out, _ = _run(["config", "get", r"appearance.font\.family"])
    assert code == EXIT_OK and out.strip() == '"serif"'
    code, _, _ = _run(["config", "unset", '"appearance"."font.family"'])
    assert code == EXIT_OK and settings_db.get_value("appearance", "font.family") == "sans"


def test_cli_masks_a_secret_even_when_read_by_path(temp_settings, monkeypatch):
    spec = {"category": "appearance", "key": "api_token", "value": {}, "label": "t", "kind": "json"}
    monkeypatch.setattr(settings_db, "DEFAULTS", [*settings_db.DEFAULTS, spec])
    monkeypatch.setitem(settings_db._SPEC, ("appearance", "api_token"), spec)
    settings_db.put_category("appearance", {"api_token": {"x.y": "sk-live-9"}})
    code, out, _ = _run(["config", "get", "appearance.api_token.x.y"])
    assert code == EXIT_OK and "sk-live-9" not in out and "••" in out
    code, out, _ = _run(["config", "get", "appearance.api_token.x.y", "--reveal"])
    assert code == EXIT_OK and "sk-live-9" in out
