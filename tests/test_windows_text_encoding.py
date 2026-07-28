"""Production text I/O must name its encoding — the hub ships to Windows.

`Path.read_text()` / `write_text()` and `open()` with no `encoding=` use
`locale.getpreferredencoding()`. That is UTF-8 on the Linux CI box and cp1252 on
the Windows host this product actually runs on. Every file in this repo that
carries Romanian text, an em dash, or a HUD glyph is then unreadable there:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f

which is exactly how a gate added in this same PR failed on windows-latest while
passing locally. The failure mode is nasty because it is invisible until a
non-ASCII byte shows up in the data — so an owner hits it with their own content,
not in CI.

Scope is deliberately `agents/` and `scripts/` — the code that ships. Test files
are excluded: they read and write fixtures they created themselves, which are
ASCII by construction, and blanket-fixing 80-odd call sites would be churn
without a defect behind it. A test that reads real repository source (as the
NEW-4 gate does) is the case that bites, and those live in production paths'
shadow anyway — pass `encoding="utf-8"` there and it stays fixed.
"""

import ast
import pathlib

import pytest

_SHIPPED_ROOTS = ("agents", "scripts")
_TEXT_IO_METHODS = frozenset({"read_text", "write_text"})


def _unencoded_text_io():
    """Every (file, line, call) in shipped code that omits `encoding=`."""
    offenders = []
    for root in _SHIPPED_ROOTS:
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if any(kw.arg == "encoding" for kw in node.keywords):
                    continue

                name = getattr(node.func, "attr", None)
                if name in _TEXT_IO_METHODS:
                    offenders.append((str(path), node.lineno, f"{name}()"))
                    continue

                # open(...) — binary mode carries no encoding, so it is exempt.
                if getattr(node.func, "id", None) == "open":
                    mode = ""
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        mode = str(node.args[1].value)
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode = str(kw.value.value)
                    if "b" not in mode:
                        offenders.append((str(path), node.lineno, "open()"))
    return offenders


def test_shipped_code_always_names_its_text_encoding():
    offenders = _unencoded_text_io()
    assert not offenders, (
        "text I/O without encoding= in shipped code — this reads as cp1252 on the "
        "Windows host and raises UnicodeDecodeError on the first non-ASCII byte:\n  "
        + "\n  ".join(f"{f}:{line}  {call}" for f, line, call in offenders)
        + '\nAdd encoding="utf-8" (or open in binary mode).'
    )


@pytest.mark.parametrize("sample", [
    "Frigga are grijă de casă",        # Romanian diacritics — all over this repo
    "strict-local — nothing leaves",   # em dash — all over the HUD copy
    "🔒 STRICT",                        # emoji — the trust chip
])
def test_utf8_roundtrips_where_the_platform_default_would_not(tmp_path, sample):
    """The property the gate is protecting, stated directly.

    Under cp1252 the writes below raise UnicodeEncodeError and the reads raise
    UnicodeDecodeError. Naming utf-8 makes them platform-independent.
    """
    target = tmp_path / "note.txt"
    target.write_text(sample, encoding="utf-8")
    assert target.read_text(encoding="utf-8") == sample
