"""Two injection surfaces: the public widget snippet, and the skill importer.

`GET /api/widget/{token}` is public and unauthenticated, and its output is
`<script>`-embedded on third-party sites — so whatever it emits runs in *their*
origin. Six config values were interpolated into that JavaScript. Two of them had
`.replace('"', "'")` applied; the other four had nothing. `color` and `position`
were substituted raw into a string that is then concatenated into `innerHTML`.

`POST /skills/import` built its target directory as
`skill_name.lower().replace(" ", "-")`, which replaces ONLY spaces — path
separators, `..`, a leading `/` and a drive letter all survived, and the result
was joined straight onto the skills directory.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from agents.core.skills.importer import SkillImporter, _safe_slug
from agents.core.widget import render_snippet

# ── widget snippet ────────────────────────────────────────────────────────────

def _literal_after(js: str, marker: str) -> str:
    """The JS string literal (quotes included) that follows *marker*."""
    rest = js.split(marker, 1)[1]
    assert rest.startswith('"'), f"{marker} is not followed by a string literal"
    out, i, escaped = ['"'], 1, False
    while i < len(rest):
        ch = rest[i]
        out.append(ch)
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            break
        i += 1
    return "".join(out)


def _unescaped(literal: str) -> str:
    """The literal's body with every backslash escape sequence removed.

    An ESCAPED quote (`\\"`) is correct and expected; only a BARE one closes the
    string early. Checking for `\'"\'` without stripping escapes first flags the
    fix as if it were the bug.
    """
    import re
    return re.sub(r"\\.", "", literal[1:-1], flags=re.S)


def _assert_parses(js: str) -> None:
    """The snippet must still be syntactically valid JavaScript.

    This is the assertion that actually means something: if a payload had escaped
    its string literal, the surrounding statement would almost certainly no longer
    parse. Skipped when node is unavailable rather than silently passing.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available to parse-check the snippet")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert proc.returncode == 0, f"generated snippet does not parse:\n{proc.stderr}"


def test_a_hostile_color_cannot_break_out_into_innerhtml():
    """`color` had no escaping at all and lands in `panel.innerHTML`.

    The payload TEXT surviving is fine and expected — it ends up as inert
    characters inside a quoted string. What must not survive is the syntax: the
    quote that would close the JS literal and the `<` that would open an HTML tag
    once the string reaches innerHTML.
    """
    payload = 'red;"></div><img src=x onerror=alert(1)><div style="'
    js = render_snippet({"token": "t", "color": payload})
    color_literal = _literal_after(js, "COLOR=")

    assert payload not in js                      # not verbatim, anywhere
    assert '"' not in _unescaped(color_literal)   # no BARE quote inside the literal
    assert "<" not in color_literal               # cannot open a tag in innerHTML
    _assert_parses(js)


def test_a_title_cannot_close_the_host_script_tag():
    """The HTML parser finds `</script>` before JavaScript sees any string, so
    JS-level quoting cannot help here — the sequence itself has to be broken up."""
    js = render_snippet({"token": "t", "title": "</script><script>alert(1)</script>"})
    assert "</script>" not in js
    assert "<\\/script>" in js or "&lt;/script&gt;" in js


def test_a_trailing_backslash_cannot_escape_the_closing_quote():
    """The old `.replace('"', "'")` left backslashes alone, so a value ending in
    one escaped the quote that was meant to terminate it and the rest of the
    snippet became part of the string."""
    js = render_snippet({"token": "t", "greeting": "hi\\"})
    # The backslash is escaped, so the literal terminates where it should.
    assert 'GREET="hi\\\\"' in js


def test_position_cannot_inject_a_statement():
    """Again: the text may survive inside the literal; a STATEMENT may not."""
    js = render_snippet({"token": "t", "position": 'bottom-right";alert(1);//'})
    pos_literal = _literal_after(js, "POS=")

    assert '"' not in _unescaped(pos_literal), "the payload closed the string literal"
    _assert_parses(js)


def test_a_newline_cannot_break_the_statement():
    """A raw newline inside a JS string literal is a syntax error — it would have
    broken the whole snippet for every embedding site."""
    js = render_snippet({"token": "t", "title": "line1\nline2"})
    assert "\\n" in js
    var_line = [ln for ln in js.splitlines() if "TITLE=" in ln][0]
    assert "line1" in var_line and "line2" in var_line   # both on ONE line


def test_the_normal_config_still_renders_usably():
    """None of this may break the actual widget."""
    js = render_snippet(
        {"token": "abc123", "title": "Jarvis", "color": "#4f46e5",
         "position": "bottom-right", "greeting": "Hi! How can I help?"},
        base_url="http://127.0.0.1:8080")
    assert 'T="abc123"' in js
    assert 'TITLE="Jarvis"' in js
    assert 'COLOR="#4f46e5"' in js
    assert 'POS="bottom-right"' in js
    assert 'BASE="http://127.0.0.1:8080"' in js


@pytest.mark.parametrize("field", ["token", "title", "color", "position", "greeting"])
def test_no_field_leaks_an_unescaped_quote(field):
    """Sweep: every interpolated field, not just the two that were half-handled."""
    js = render_snippet({"token": "t", field: 'a"; alert(1); var x="'})
    assert '"; alert(1); var x="' not in js


# ── skill import path traversal ───────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "../../pwned",
    "/etc/jarvis-pwned",
    "a/../../b",
    "..",
    "",
    "   ",
    "x" * 200,
])
def test_unsafe_skill_names_are_rejected(name):
    assert _safe_slug(name) is None, f"{name!r} should not produce a slug"


@pytest.mark.parametrize("name,expected", [
    ("weather", "weather"),
    ("My Skill", "my-skill"),
    ("pdf-tools", "pdf-tools"),
    ("PDF_Tools", "pdf_tools"),
])
def test_ordinary_skill_names_still_work(name, expected):
    assert _safe_slug(name) == expected


def test_import_does_not_write_outside_the_skills_directory():
    """The concrete escape: `../../pwned` resolved to the grandparent directory."""
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "nested" / "skills"
        importer = SkillImporter(str(skills))
        outside = Path(tmp) / "pwned"

        ok = asyncio.run(importer._save_skill("../../pwned", "test", skill_md_text="x"))

        assert ok is False
        assert not outside.exists(), "the import escaped the skills directory"
        assert list(skills.iterdir()) == []


def test_import_rejects_rather_than_silently_renaming():
    """Sanitizing `../../pwned` down to `pwned` would install a skill under a name
    the caller never asked for — refusing is the honest outcome."""
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "skills"
        importer = SkillImporter(str(skills))
        asyncio.run(importer._save_skill("../../pwned", "test", skill_md_text="x"))
        assert not (skills / "pwned").exists()


def test_a_normal_import_still_lands_in_the_skills_directory():
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "skills"
        importer = SkillImporter(str(skills))
        ok = asyncio.run(importer._save_skill("Weather Bot", "test", skill_md_text="# x"))
        assert ok is True
        assert (skills / "weather-bot" / "SKILL.md").read_text(encoding="utf-8") == "# x"
        assert (skills / "weather-bot" / "manifest.json").exists()
