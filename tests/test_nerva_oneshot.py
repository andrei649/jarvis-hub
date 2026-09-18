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


def test_a_write_that_dies_mid_report_leaves_the_previous_one_intact(tmp_path, monkeypatch):
    """The atomicity pin with teeth.

    The assertions above hold for a plain truncating `open(path, "w")` too — the stale
    report is still replaced, and no temp file is left precisely BECAUSE none was made.
    The property that actually distinguishes the two is what a reader sees when the
    write dies half-way: with a tempfile plus `os.replace`, the previous report is
    still there, whole. With a truncating write it has already been destroyed.
    """
    from agents.cli import nerva

    path = tmp_path / "spend.json"
    path.write_text('{"schema": "the report from the last run"}\n', encoding="utf-8")

    def _die_midway(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(nerva.json, "dump", _die_midway)
    code, _out, err, _hub = _run(
        ["chat", "-z", "--usage-file", str(path), "hi"], hub=_FakeHub(ANSWER))

    assert code == EXIT_OK and "could not write the usage file" in err
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == (
        "the report from the last run"
    ), "a half-written report destroyed the previous one; the write is not atomic"
    assert not list(tmp_path.glob(".nerva-usage-*"))


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


# ── the verdict cannot be an exact-string match (adversarial review, 2026-09-18) ──
#
# The first version of this verb decided governance with `_NOT_AN_ANSWER.get(answer)`.
# An independent review broke it in one line: the hub does not hand `/chat` the agent's
# reply verbatim. `Orchestrator._synthesize` wraps a single specialist's answer as
# "[athena]: …" whenever `jarvis` is not among the responders — the ordinary routed
# path — so the sentinel never matched, `-z` exited 0, and the approval notice was
# printed as if it were the model's answer. A cron entry doing `nerva chat -z … &&
# deploy` treated an undecided irreversible action as a completed turn.


def test_the_hub_really_does_wrap_a_specialist_reply():
    """The pin below is only worth anything if this is still the wire shape.

    Derived from the hub's own synthesiser rather than asserted from memory, so a
    change to `_synthesize` fails here instead of silently making the guard moot.
    """
    import asyncio

    from agents.core.agent_runtime import _APPROVAL_REPLY
    from agents.core.orchestrator import Orchestrator

    orch = object.__new__(Orchestrator)
    orch.agents = {}
    orch.cognition = None
    wire = asyncio.run(Orchestrator._synthesize(orch, {"athena": _APPROVAL_REPLY}, None))

    assert wire != _APPROVAL_REPLY, "no longer wrapped; the containment guard can relax"
    assert _APPROVAL_REPLY in wire


def test_a_synthesised_approval_still_exits_non_zero():
    """The defect the review found, pinned at the CLI where it was fixed."""
    from agents.core.agent_runtime import _APPROVAL_REPLY

    hub = _FakeHub({"POST /chat": {"reply": f"[athena]: {_APPROVAL_REPLY}"}})
    code, out, err, hub = _run(["chat", "-z", "delete the archive"], hub=hub)

    assert code == EXIT_FAILED, (
        "the hub wrapped the approval notice and the verb called it an answer — this is "
        "the Hermes behaviour the row exists to invert"
    )
    assert out == ""
    assert "approval" in err.lower() and "nerva approvals" in err
    decided = [c for c in hub.calls if c[0] != "GET" and "/chat" not in c[1]]
    assert decided == [], f"the one-shot path must not decide anything: {decided}"


def test_a_sentinel_padded_with_control_bytes_is_still_not_an_answer():
    """The verdict reads the sanitised text, so escapes cannot smuggle a refusal past it."""
    from agents.core.agent_runtime import _APPROVAL_REPLY

    hub = _FakeHub({"POST /chat": {"reply": f"\x1b[2J{_APPROVAL_REPLY}\x07"}})
    code, out, _err, _hub = _run(["chat", "-z", "delete the archive"], hub=hub)

    assert code == EXIT_FAILED and out == ""


@pytest.mark.parametrize("attr", [
    "_DEADLINE_REPLY", "_CONTEXT_REPLY", "_WINDOW_REPLY", "_REPEAT_REPLY", "_FAILURE_REPLY",
])
def test_a_stopped_tool_loop_is_not_an_answer(attr):
    """`--help` promises "1 the turn did not complete". A tool loop that gave up part-way
    did not complete, and a script that stored its stop reason as the answer would record
    the run as a success."""
    from agents.core import agent_runtime

    hub = _FakeHub({"POST /chat": {"reply": getattr(agent_runtime, attr)}})
    code, out, err, _hub = _run(["chat", "-z", "tidy the logs"], hub=hub)

    assert code == EXIT_FAILED and out == "" and "tool loop" in err


def test_the_dynamic_turn_limit_stop_is_covered_by_the_prefix_rule():
    """One stop reason is built with an f-string, so no table of exact strings holds it."""
    hub = _FakeHub({"POST /chat": {
        "reply": "I stopped the tool loop after 12 model turns because it reached the limit."}})
    code, out, _err, _hub = _run(["chat", "-z", "tidy the logs"], hub=hub)

    assert code == EXIT_FAILED and out == ""


def test_the_sentinel_table_matches_every_reply_the_hub_can_send():
    """Stronger than the first version of this test, which only asserted the constants
    were KEYS in the table — blind to the reply being wrapped in transit, and blind to
    the five tool-loop stops that were missing from the table entirely."""
    from agents.cli.nerva import _not_an_answer
    from agents.core.agent_runtime import (
        _APPROVAL_REPLY,
        _CONTEXT_REPLY,
        _DEADLINE_REPLY,
        _FAILURE_REPLY,
        _REPEAT_REPLY,
        _WINDOW_REPLY,
    )
    from agents.core.conversation_clock import CONTEXT_REFUSED_REPLY
    from agents.core.llm.base import LOCAL_SELECTION_UNAVAILABLE_REPLY
    from agents.core.orchestrator import TURN_BUSY_REPLY
    from agents.core.session_continuation import CONTINUATION_REFUSED_REPLY

    for constant in (_APPROVAL_REPLY, TURN_BUSY_REPLY, CONTEXT_REFUSED_REPLY,
                     CONTINUATION_REFUSED_REPLY, LOCAL_SELECTION_UNAVAILABLE_REPLY,
                     _DEADLINE_REPLY, _CONTEXT_REPLY, _WINDOW_REPLY, _REPEAT_REPLY,
                     _FAILURE_REPLY):
        assert _not_an_answer(constant), (
            f"the hub now replies {constant!r}; add it to _NOT_AN_ANSWER in agents/cli/nerva.py"
        )
        assert _not_an_answer(f"[athena]: {constant}"), (
            f"{constant!r} is matched verbatim but not once the hub wraps it"
        )


def test_a_control_only_reply_is_not_an_answer():
    """The guard used to read the raw reply while the printer read the sanitised one, so
    a reply made only of escapes was "not empty" to the guard and an empty line on
    stdout — exit 0 over nothing at all."""
    hub = _FakeHub({"POST /chat": {"reply": "\x1b[2J\x07\x00"}})
    code, out, err, _hub = _run(["chat", "-z", "hi"], hub=hub)

    assert code == EXIT_FAILED and out == "" and "empty" in err


def test_an_unreadable_pending_list_is_not_exploded_into_fabricated_ids():
    """`list("71")` is `['7', '1']` — two approval ids that do not exist, handed to the
    operator as things to go and decide. A wrong id is worse than no id."""
    hub = _FakeHub({"POST /chat": {"reply": "Archived.", "pending_approvals": "71"}})
    code, out, err, _hub = _run(["chat", "-z", "archive"], hub=hub)

    assert code == EXIT_FAILED and out == ""
    assert "cannot read" in err and "nerva approvals" in err
    assert "approval 7, 1" not in err


def test_the_receipt_of_an_interactive_turn_does_not_claim_a_queued_turn_completed(tmp_path):
    """Without -z the verb still exits 0 and prints the reply — every existing caller
    keeps working. The receipt is new surface, so it says what the exit code cannot."""
    report = tmp_path / "usage.json"
    hub = _FakeHub({"POST /chat": {"reply": "Archived 4 of 5.", "pending_approvals": [71]}})
    code, out, _err, _hub = _run(
        ["chat", "--usage-file", str(report), "archive the lot"], hub=hub)

    assert code == EXIT_OK and "Archived 4 of 5." in out
    body = json.loads(report.read_text())
    assert body["completed"] is False and body["status"] == "queued_for_approval"
    assert body["pending_approvals"] == [71]


def test_an_interrupted_run_still_leaves_a_receipt(tmp_path):
    """--usage-file's help says "written even when it fails", and a timeout kill is the
    failure a cron wrapper most needs a receipt for."""
    report = tmp_path / "usage.json"

    class _Interrupted(_FakeHub):
        def post(self, path, body=None):
            raise KeyboardInterrupt

    code, out, _err, _hub = _run(
        ["chat", "-z", "--usage-file", str(report), "hi"], hub=_Interrupted())

    assert code == EXIT_INTERRUPTED and out == ""
    body = json.loads(report.read_text())
    assert body["status"] == "interrupted" and body["completed"] is False
    assert body["exit_code"] == EXIT_INTERRUPTED


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    """NamedTemporaryFile(delete=False) outlives a failed replace; without a cleanup a
    cron entry with a mistyped path drops one hidden report per run, forever."""
    from agents.cli import nerva

    monkeypatch.setattr(nerva.os, "replace", _raise_oserror)
    report = tmp_path / "usage.json"
    code, _out, err, _hub = _run(
        ["chat", "-z", "--usage-file", str(report), "hi"], hub=_FakeHub(ANSWER))

    assert code == EXIT_OK, "losing the receipt must not change the run's outcome"
    assert "could not write the usage file" in err
    assert list(tmp_path.glob(".nerva-usage-*")) == []


def _raise_oserror(*_args, **_kwargs):
    raise OSError(13, "Permission denied")


def test_an_unencodable_field_warns_instead_of_crashing_after_the_answer(tmp_path):
    """json.dump(..., ensure_ascii=False) on a surrogate raises UnicodeEncodeError — a
    ValueError, not an OSError, so it used to escape the handler and crash the verb
    after the answer was already on stdout."""
    report = tmp_path / "usage.json"
    hub = _FakeHub({"POST /chat": {"reply": "fine"}})
    code, out, err, _hub = _run(
        ["chat", "-z", "--usage-file", str(report), "--session", "a\udcffb", "hi"], hub=hub)

    assert code == EXIT_OK and out == "fine\n"
    assert "could not write the usage file" in err
    assert list(tmp_path.glob(".nerva-usage-*")) == []


def test_an_empty_usage_path_is_said_out_loud(tmp_path):
    """`--usage-file "$SPEND_FILE"` with SPEND_FILE unset asked for a receipt and got
    none; an unwritable path is warned about, and so is this."""
    code, _out, err, _hub = _run(["chat", "-z", "--usage-file", "", "hi"], hub=_FakeHub(ANSWER))

    assert code == EXIT_OK and "empty path" in err


def test_the_answer_survives_a_stdout_that_cannot_encode_it():
    """stdout's encoding belongs to the caller — a pipe under LC_ALL=C is ascii — and a
    raw write would raise *after* the turn succeeded, turning a 0 into an uncaught 1."""
    class _Ascii(io.StringIO):
        encoding = "ascii"

        def write(self, text):
            text.encode("ascii")  # what a real ascii stream does
            return super().write(text)

    out, err = io.StringIO(), io.StringIO()
    hub = _FakeHub({"POST /chat": {"reply": "café ☕"}})
    ctx = Context(environ={}, out=_Ascii(), err=err, inp=io.StringIO(""),
                  client_factory=lambda env: hub)
    assert main(["chat", "-z", "hi"], context=ctx) == EXIT_OK
    assert out.getvalue() == ""


def test_an_unterminated_escape_does_not_leak_its_payload():
    """The regex used to fail to match an unterminated OSC, so the ESC was dropped and
    `0;rm -rf /` was emitted as visible text — the exact thing whole-sequence stripping
    exists to prevent."""
    hub = _FakeHub({"POST /chat": {"reply": "before\x1b]0;rm -rf /\nafter"}})
    code, out, _err, _hub = _run(["chat", "-z", "hi"], hub=hub)

    assert code == EXIT_OK
    assert "rm -rf" not in out and "before" in out and "after" in out


def test_a_file_that_is_a_terminal_is_refused_rather_than_read(tmp_path, monkeypatch):
    """`-f -` is guarded, but `-f /dev/tty` is the same hang by another spelling."""
    from agents.cli import nerva

    path = tmp_path / "prompt.txt"
    path.write_text("hello")
    monkeypatch.setattr(nerva, "_is_tty", lambda stream: True)
    code, _out, err, hub = _run(["chat", "-z", "-f", str(path)], hub=_FakeHub(ANSWER))

    assert code == EXIT_USAGE and "terminal" in err and hub.calls == []


def test_a_multibyte_body_inside_the_bound_is_accepted(tmp_path):
    """The bound counts characters; `read` on a binary stream counts bytes, so a body of
    2,000 two-byte characters was cut mid-character and reported as "not UTF-8 text"."""
    from agents.cli.nerva import _read_body

    # 3,000 characters is inside the 4,096 bound; 6,000 bytes is not inside `bound + 1`,
    # so a byte-counting read cuts the body in half and then calls it binary.
    body = "é" * 3_000
    text, why = _read_body(io.BytesIO(body.encode()), "prompt.txt", bound=4_096)

    assert why == "" and text == body
