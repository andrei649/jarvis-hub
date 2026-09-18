"""H002 — one scripted turn from a pipe, and a report a script can trust.

The row this pins asks for three things Hermes' `-z` gives a script: only the answer on
stdout, an exit code that distinguishes "answered" from "did not answer", and a usage
report written even when the run fails.

It also carries a governance clause that inverts Hermes' own behaviour, and that clause
is the most important thing tested here. Hermes sets YOLO and accept-hooks flags inside
`-z` because "no user is watching". Nerva must do the opposite: a turn that queues an
action for approval stays queued, the verb exits non-zero, and nothing in the one-shot
path can approve or execute the queued item. `test_a_queued_approval_is_never_approved…`
is the test that would catch a future change to that.
"""

from __future__ import annotations

import io
import json

import pytest

from agents.cli.client import HubError, HubUnavailable
from agents.cli.nerva import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_NO_HUB,
    EXIT_OK,
    EXIT_USAGE,
    Context,
    main,
)
from tests.test_nerva_cli import _FakeHub, _run

ANSWER = {"POST /chat": {"reply": "the roof is fine"}}


def _posted(hub):
    return [call for call in hub.calls if call[:2] == ("POST", "/chat")]


# ── the answer, and only the answer ──────────────────────────────────────────


def test_oneshot_prints_only_the_answer_on_stdout():
    code, out, err, hub = _run(["chat", "-z", "is the roof ok?"], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK
    assert out == "the roof is fine\n"
    assert err == ""
    assert _posted(hub)[0][2]["message"] == "is the roof ok?"


def test_oneshot_keeps_newlines_and_tabs_but_not_escapes():
    """A model's answer is data. Newlines and tabs are content; ESC is not."""
    hub = _FakeHub({"POST /chat": {"reply": "line one\nline two\tcell\x1b[2Jcleared\x07"}})
    code, out, _err, _hub = _run(["chat", "-z", "hi"], hub=hub)
    assert code == EXIT_OK
    assert out == "line one\nline two\tcellcleared\n"
    assert "\x1b" not in out and "\x07" not in out


def test_the_interactive_shape_is_unchanged():
    """Every existing caller of `nerva chat` must behave exactly as before."""
    code, out, err, _hub = _run(["chat", "is the roof ok?"], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK and out == "the roof is fine\n" and err == ""
    code, out, _err, _hub = _run(["chat", "--json", "hi"], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK and json.loads(out) == {"reply": "the roof is fine"}


def test_oneshot_and_json_are_mutually_exclusive():
    code, out, err, hub = _run(["chat", "-z", "--json", "hi"])
    assert code == EXIT_USAGE and out == "" and "pick one" in err
    assert hub.calls == []


# ── the body: the same precedence `nerva send` uses ──────────────────────────


def test_oneshot_reads_the_prompt_from_stdin_and_from_a_file(tmp_path):
    code, _out, _err, hub = _run(["chat", "-z"], hub=_FakeHub(ANSWER), stdin="from the pipe")
    assert code == EXIT_OK and _posted(hub)[0][2]["message"] == "from the pipe"

    prompt = tmp_path / "prompt.txt"
    prompt.write_text("from the file\n", encoding="utf-8")
    code, _out, _err, hub = _run(["chat", "-z", "-f", str(prompt)], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK and _posted(hub)[0][2]["message"] == "from the file\n"


def test_chat_never_reads_a_terminal():
    """A script that forgot its prompt gets a usage error, not a hang."""
    class _Tty(io.StringIO):
        def isatty(self):
            return True

        def read(self, *a):
            raise AssertionError("the terminal must not be read")

    hub = _FakeHub(ANSWER)
    err = io.StringIO()
    ctx = Context(environ={}, out=io.StringIO(), err=err, inp=_Tty(), client_factory=lambda env: hub)
    assert main(["chat", "-z"], context=ctx) == EXIT_USAGE
    assert "no message provided" in err.getvalue() and hub.calls == []


def test_a_prompt_over_the_hubs_own_bound_is_a_usage_error_before_any_request():
    """ChatRequest caps `message` at 4096; refusing here beats an HTTP 422 a script
    would read as "the turn failed"."""
    code, _out, err, hub = _run(["chat", "-z", "x" * 4_097])
    assert code == EXIT_USAGE and "4,096" in err and hub.calls == []
    code, _out, _err, hub = _run(["chat", "-z", "x" * 4_096], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK and len(_posted(hub)) == 1


# ── the governance clause ────────────────────────────────────────────────────


APPROVAL = "I paused the tool loop because this action requires approval."


def test_a_queued_approval_is_never_approved_and_exits_non_zero_naming_the_id():
    """The binding clause of the H002 row: a one-shot run must QUEUE what the kernel
    would queue and exit non-zero with the pending id. It must never decide it."""
    hub = _FakeHub({"POST /chat": {"reply": APPROVAL, "pending_approvals": [71]}})
    code, out, err, hub = _run(["chat", "-z", "delete the archive"], hub=hub)
    assert code == EXIT_FAILED
    assert out == "", "a queued turn produced no answer; stdout must stay empty"
    assert "71" in err and "approval" in err.lower() and "nerva approvals" in err
    decided = [c for c in hub.calls if c[0] != "GET" and "/chat" not in c[1]]
    assert decided == [], f"the one-shot path must not decide anything: {decided}"


def test_a_plausible_answer_that_also_queued_an_approval_still_exits_non_zero():
    """The sentinel table is a convenience, not the verdict. A hub that queues an action
    and *still* composes a reply — a tool loop that answered from what it already had —
    would otherwise hand a script an exit 0 while the action sits undecided. The pending
    list is what decides; the reply text only supplies the wording when it is empty."""
    hub = _FakeHub({"POST /chat": {"reply": "Archived 4 of 5; the fifth needs a decision.",
                                   "pending_approvals": [88]}})
    code, out, err, hub = _run(["chat", "-z", "archive the lot"], hub=hub)
    assert code == EXIT_FAILED
    assert out == "", "an undecided action is not a completed turn; stdout stays empty"
    assert "88" in err and "nerva approvals" in err
    decided = [c for c in hub.calls if c[0] != "GET" and "/chat" not in c[1]]
    assert decided == [], f"the one-shot path must not decide anything: {decided}"


def test_a_queued_approval_without_an_id_still_exits_non_zero():
    """An older hub does not report the id. Reporting 'an approval is pending, id
    unknown' is honest; exiting 0 is not."""
    hub = _FakeHub({"POST /chat": {"reply": APPROVAL}})
    code, out, err, _hub = _run(["chat", "-z", "delete the archive"], hub=hub)
    assert code == EXIT_FAILED and out == ""
    assert "did not report the id" in err and "nerva approvals" in err


@pytest.mark.parametrize("reply", [
    "I'm still working on your previous message — send that again in a moment.",
    "I stopped this turn because its context compaction could not be safely committed. Please retry.",
    "I stopped this turn because this continued conversation could not be safely restored.",
    "⚠️ No local language model is available. Start LM Studio or Ollama and try again.",
    "Internal error.",
    "Jarvis not initialized.",
    "",
    "   ",
])
def test_a_refused_turn_is_not_an_answer(reply):
    """Every one of these arrives as HTTP 200. A script that trusted the status code
    would treat 'Internal error.' as the model's opinion."""
    code, out, err, _hub = _run(["chat", "-z", "hi"], hub=_FakeHub({"POST /chat": {"reply": reply}}))
    assert code == EXIT_FAILED, f"{reply!r} is not an answer"
    assert out == "" and err.strip()


def test_the_sentinel_table_still_matches_the_hub():
    """The CLI keeps a stdlib-only COPY of the hub's refusal strings, because importing
    the orchestrator to read one constant would pull the runtime into `nerva --help`.

    A copy can drift, so drift is made loud here rather than silent: if one of these
    constants is reworded, this test fails and the table in nerva.py needs the new text.
    Read a failure as "update the table", not as "delete the test" — without it, `-z`
    would quietly start exiting 0 on a refused turn.
    """
    from agents.cli.nerva import _NOT_AN_ANSWER
    from agents.core.agent_runtime import _APPROVAL_REPLY
    from agents.core.conversation_clock import CONTEXT_REFUSED_REPLY
    from agents.core.llm.base import LOCAL_SELECTION_UNAVAILABLE_REPLY
    from agents.core.orchestrator import TURN_BUSY_REPLY
    from agents.core.session_continuation import CONTINUATION_REFUSED_REPLY

    for constant in (_APPROVAL_REPLY, TURN_BUSY_REPLY, CONTEXT_REFUSED_REPLY,
                     CONTINUATION_REFUSED_REPLY, LOCAL_SELECTION_UNAVAILABLE_REPLY):
        assert constant.strip() in _NOT_AN_ANSWER, (
            f"the hub now replies {constant!r}; add it to _NOT_AN_ANSWER in agents/cli/nerva.py"
        )


# ── the usage report ─────────────────────────────────────────────────────────


def test_the_usage_file_is_written_on_success(tmp_path):
    path = tmp_path / "spend.json"
    code, _out, _err, _hub = _run(["chat", "-z", "--usage-file", str(path), "hi"], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["schema"] == "nerva.chat.usage.v1"
    assert report["status"] == "completed" and report["completed"] is True and report["exit_code"] == 0
    assert report["started_at"] and report["finished_at"] and report["duration_ms"] is not None


@pytest.mark.parametrize("hub,expected_code,expected_status", [
    (_FakeHub({"POST /chat": {"reply": APPROVAL, "pending_approvals": [7]}}), EXIT_FAILED, "queued_for_approval"),
    (_FakeHub({"POST /chat": {"reply": "Internal error."}}), EXIT_FAILED, "refused"),
    (_FakeHub(raise_with=HubUnavailable("http://127.0.0.1:9", "refused")), EXIT_NO_HUB, "no_hub"),
    (_FakeHub(raise_with=HubError(401, "user token required")), EXIT_AUTH, "unauthorised"),
])
def test_the_usage_file_is_written_even_when_the_run_fails(tmp_path, hub, expected_code, expected_status):
    """A receipt that only appears on success is useless to the cron job that needs to
    know what the failed run cost."""
    path = tmp_path / "spend.json"
    code, _out, _err, _hub = _run(["chat", "-z", "--usage-file", str(path), "hi"], hub=hub)
    assert code == expected_code
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == expected_status
    assert report["completed"] is False and report["exit_code"] == expected_code
    assert report["reason"]


def test_the_usage_file_never_invents_a_number(tmp_path):
    """The hub cannot attribute one turn's spend today (the meter is fed each agent's
    configured model, so it reads $0.00 for every turn). `null` with a stated basis is
    the honest report; `0.0` would read as a measured zero."""
    path = tmp_path / "spend.json"
    _run(["chat", "-z", "--usage-file", str(path), "hi"], hub=_FakeHub(ANSWER))
    report = json.loads(path.read_text(encoding="utf-8"))
    for key in ("estimated_cost_usd", "input_tokens", "output_tokens", "api_calls", "model", "provider"):
        assert report[key] is None, f"{key} must be null until it can be measured, not 0"
    assert report["cost_basis"] == "unavailable"


def test_the_usage_file_reports_the_session_only_when_the_caller_named_one(tmp_path):
    """The hub never says which session it used, so reporting one we were not given
    would be a guess."""
    path = tmp_path / "a.json"
    _run(["chat", "-z", "--usage-file", str(path), "hi"], hub=_FakeHub(ANSWER))
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] is None
    path = tmp_path / "b.json"
    _run(["chat", "-z", "--usage-file", str(path), "--session", "s-42", "hi"], hub=_FakeHub(ANSWER))
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == "s-42"


def test_a_usage_file_that_cannot_be_written_warns_without_changing_the_verdict(tmp_path):
    """Losing the receipt must not change what the run actually did."""
    code, out, err, _hub = _run(
        ["chat", "-z", "--usage-file", str(tmp_path / "no-such-dir" / "u.json"), "hi"], hub=_FakeHub(ANSWER))
    assert code == EXIT_OK and out == "the roof is fine\n"
    assert "could not write the usage file" in err


def test_the_usage_file_is_replaced_atomically(tmp_path):
    """A reader polling the path sees the old report or the new one, never half of one."""
    path = tmp_path / "spend.json"
    path.write_text('{"schema": "stale"}\n', encoding="utf-8")
    _run(["chat", "-z", "--usage-file", str(path), "hi"], hub=_FakeHub(ANSWER))
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "nerva.chat.usage.v1"
    assert not list(tmp_path.glob(".nerva-usage-*")), "no temporary file may be left behind"


# ── interruption ─────────────────────────────────────────────────────────────


def test_an_interrupt_is_130_with_one_line_and_no_partial_answer():
    """Ctrl-C already exited 130 — through a traceback, which in a pipeline looks like
    a crash and can spill a partial answer."""
    class _Interrupting:
        base_url = "http://127.0.0.1:8080"
        calls: list = []

        def post(self, path, body=None):
            raise KeyboardInterrupt

        def get(self, path):
            raise KeyboardInterrupt

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: _Interrupting())
    assert main(["chat", "-z", "hi"], context=ctx) == EXIT_INTERRUPTED
    assert out.getvalue() == ""
    assert err.getvalue() == "interrupted\n", "one line, no traceback"
