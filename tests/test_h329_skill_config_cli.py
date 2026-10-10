"""H329's interactive picker never writes on cancel, EOF, or non-TTY input."""

from __future__ import annotations

import io

from agents.cli.nerva import Context, main


class _TTY(io.StringIO):
    def isatty(self):
        return True


def _run(text: str, *, tty: bool = True, skills=None):
    calls = []

    class Client:
        def get(self, path):
            assert path == "/skills"
            return {"skills": skills if skills is not None else {
                "Weather": {"disabled": False, "disabled_channels": ["telegram"], "category": "info"},
                "Security Monitor": {"essential": True, "disabled": False, "category": "core"},
            }}

        def post(self, path, body):
            calls.append((path, body))
            return {"status": "pending", "task_id": 42, "pending": ["Weather"]} if body["enabled"] else {
                "changed": ["Weather"]}

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=_TTY(text) if tty else io.StringIO(text),
                  client_factory=lambda _env: Client())
    return main(["skills", "config"], context=ctx), out.getvalue(), err.getvalue(), calls


def test_noninteractive_cancel_and_eof_never_mutate():
    code, _out, err, calls = _run("1\non\n\n", tty=False)
    assert code == 2 and "interactive" in err and calls == []
    for text in ("", "\n", "2\n", "2\non\n"):
        code, _out, _err, calls = _run(text)
        assert code == 0 and calls == []


def test_per_skill_and_category_picker_use_owner_route_and_show_pending():
    code, out, err, calls = _run("2\non\nweb\n")
    assert code == 0 and not err
    assert calls == [("/api/skills/switch", {"skill": "Weather", "enabled": True, "channel": "web"})]
    assert "skill: Weather (off on telegram)" in out
    assert "category: info (off on telegram)" in out
    assert "category: core (on)" in out
    assert "pending owner approval: task 42" in out and "switched on" not in out
    code, out, err, calls = _run("3\noff\n\n")
    assert code == 0 and not err
    assert calls == [("/api/skills/switch", {"category": "core", "enabled": False})]


def test_category_with_different_member_switches_says_mixed():
    code, out, _err, calls = _run("\n", skills={
        "News": {"disabled": True, "category": "info"},
        "Weather": {"disabled": False, "disabled_channels": ["telegram"], "category": "info"},
    })
    assert code == 0 and "category: info (mixed)" in out and calls == []
