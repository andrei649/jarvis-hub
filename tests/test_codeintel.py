"""0.31 — Code Intelligence: read-only AST symbol index over Python source."""

from agents.core.codeintel import build_index, search_symbols

_SAMPLE = '''\
"""module doc."""


def top_level(a, b):
    """Adds two things.

    second line ignored.
    """
    return a + b


async def fetch_it():
    pass


class Widget:
    """A widget."""

    def render(self):
        """Draw it."""
        return "x"

    async def reload(self):
        pass
'''


def _index(tmp_path):
    (tmp_path / "sample.py").write_text(_SAMPLE, encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.py").write_text("def ignore_me(): pass\n", encoding="utf-8")
    return build_index(tmp_path)


def test_extracts_functions_classes_methods_with_kinds(tmp_path):
    idx = _index(tmp_path)
    by_qual = {s["qualname"]: s for s in idx["symbols"]}
    assert by_qual["top_level"]["kind"] == "function"
    assert by_qual["fetch_it"]["kind"] == "async_function"
    assert by_qual["Widget"]["kind"] == "class"
    assert by_qual["Widget.render"]["kind"] == "method"
    assert by_qual["Widget.reload"]["kind"] == "method"
    assert idx["by_kind"] == {"function": 1, "async_function": 1, "class": 1, "method": 2}


def test_doc_is_only_the_first_nonempty_line(tmp_path):
    idx = _index(tmp_path)
    top = next(s for s in idx["symbols"] if s["qualname"] == "top_level")
    assert top["doc"] == "Adds two things."          # not the whole docstring body
    assert top["lineno"] == 4 and top["file"] == "sample.py"


def test_skips_pycache_and_counts_files(tmp_path):
    idx = _index(tmp_path)
    assert idx["files_indexed"] == 1                  # __pycache__/junk.py skipped
    assert all("__pycache__" not in s["file"] for s in idx["symbols"])


def test_syntax_error_is_recorded_not_fatal(tmp_path):
    (tmp_path / "ok.py").write_text("def fine(): pass\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    idx = build_index(tmp_path)
    assert any(s["qualname"] == "fine" for s in idx["symbols"])   # good file still indexed
    assert any(e["file"] == "broken.py" for e in idx["errors"])   # bad file surfaced honestly


# ── search ────────────────────────────────────────────────────────────────────
def test_search_substring_and_kind_filter(tmp_path):
    idx = _index(tmp_path)
    assert {s["qualname"] for s in search_symbols(idx, "re")} == {"Widget.render", "Widget.reload"}
    assert [s["qualname"] for s in search_symbols(idx, "render", kind="method")] == ["Widget.render"]
    assert search_symbols(idx, "render", kind="class") == []     # kind filter excludes it


def test_search_ranks_exact_name_first_and_caps_limit(tmp_path):
    idx = _index(tmp_path)
    # exact-name match ranks ahead of a broader substring
    hits = search_symbols(idx, "Widget")
    assert hits[0]["qualname"] == "Widget"
    assert search_symbols(idx, "", limit=10) == []               # empty query → nothing
    assert len(search_symbols(idx, "e", limit=2)) <= 2           # limit respected


# ── DRA-15 backend defect 2: the index was one level deep, and blind to .venv312 ──
#
# `_symbols_in_source` walked `tree.body` plus one pass over each module-level class
# body. Everything deeper was absent: nested functions, closures, defs inside a
# module-level if/try/with, and classes nested in classes (skipped entirely, along with
# every method they hold). Measured on this repo before the fix: 267 of 6,007 function
# defs under agents/ were unindexed, so /api/codeintel/search answered count:0 for
# symbols that demonstrably exist — a miss that reads as "not in the repo" rather than
# "not indexed at this depth".

_NESTED = '''
def outer():
    def inner_closure():
        pass
    return inner_closure

if True:
    def defined_under_if():
        pass

try:
    class GuardedClass:
        def guarded_method(self):
            pass
except Exception:
    pass

class Outer:
    def method(self):
        def method_local():
            pass
        return method_local

    class Inner:
        def inner_method(self):
            pass
'''


def _names(tmp_path, source, fname="deep.py"):
    (tmp_path / fname).write_text(source, encoding="utf-8")
    from agents.core.codeintel.index import build_index
    idx = build_index(str(tmp_path))
    return {s["name"] for s in idx["symbols"]}, idx


def test_index_reaches_nested_and_conditionally_defined_symbols(tmp_path):
    names, idx = _names(tmp_path, _NESTED)
    for expected in ("outer", "inner_closure", "defined_under_if", "GuardedClass",
                     "guarded_method", "Outer", "method", "method_local", "Inner",
                     "inner_method"):
        assert expected in names, f"{expected!r} is defined but was not indexed"
    assert idx["errors"] == []


def test_nested_symbols_carry_a_qualname_that_locates_them(tmp_path):
    """A bare name is not enough: two `inner` defs in one file must be tellable apart."""
    _, idx = _names(tmp_path, _NESTED)
    q = {s["name"]: s["qualname"] for s in idx["symbols"]}
    assert q["inner_closure"] == "outer.inner_closure"
    assert q["method_local"] == "Outer.method.method_local"
    assert q["inner_method"] == "Outer.Inner.inner_method"
    assert q["guarded_method"] == "GuardedClass.guarded_method"


def test_a_virtualenv_is_skipped_by_its_marker_not_by_its_name(tmp_path):
    """.venv312 is this repo's actual venv and was not in the fixed name list, so 37,220
    of 53,641 indexed symbols were third-party site-packages. Skip on pyvenv.cfg."""
    from agents.core.codeintel.index import build_index

    (tmp_path / "mine.py").write_text("def project_symbol():\n    pass\n", encoding="utf-8")
    venv = tmp_path / ".venv312" / "lib" / "site-packages"
    venv.mkdir(parents=True)
    (tmp_path / ".venv312" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (venv / "vendored.py").write_text("def vendored_symbol():\n    pass\n", encoding="utf-8")

    names = {s["name"] for s in build_index(str(tmp_path))["symbols"]}
    assert "project_symbol" in names
    assert "vendored_symbol" not in names, "a virtualenv was indexed as project code"
