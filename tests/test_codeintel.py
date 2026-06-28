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
