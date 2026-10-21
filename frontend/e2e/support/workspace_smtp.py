"""Run the Workspace journey's SMTP sink: take it down, bring it back, or hold its greeting.

The journey proves that an approved email which cannot reach the mail server fails honestly
(spec §9): the approver and the requester are told why, in words, and nothing is lost. For that
the mail server has to really go away for a while (its port refuses connections, as when a relay
is down; the hub's email settings stay as the admin saved them) and come back on the same port
for the steps after it. Playwright owns this process (``playwright.workspace.config.ts`` → the
``smtp`` web server) and the spec cannot signal it, so the two talk through files in the run
directory:

* ``<run>/smtp.down`` exists → the sink stops listening (new connections are refused);
* the file is gone → the sink listens again on the same port;
* after every change ``<run>/smtp.state`` holds ``down`` or ``up`` (the spec waits for it, and
  then for the port itself to agree — support/workspace-helpers.ts → ``setSmtpSink``).

The journey also proves that a run page shows its email's outcome live (NWS-20): the server
stores the run ``succeeded`` before it talks to the mail server, and the page must say "being
emailed" until the mail server answers, then to whom it went — without a reload. A slow relay
is made deterministic with the sink's ``greeting_gate``:

* ``<run>/smtp.hold`` exists → every new connection waits for its ``220`` greeting (at most
  ``GATE_TIMEOUT`` seconds, ``tests/support/smtp_sink.py``), so a delivery stays under way;
* the file is gone → the greetings are released (held connections continue at once);
* ``<run>/smtp.hold.state`` holds ``held <n>`` or ``released <n>``, *n* being how many
  connections the sink has accepted so far, rewritten whenever either changes (the spec waits
  for a new connection before it looks at the page — ``holdSmtpGreeting`` /
  ``waitForSmtpConnection``).

Messages are kept exactly as ``tests/support/smtp_sink.py`` keeps them (the same class, one JSON
line per message in ``--out``). Prints ``READY 127.0.0.1:<port>`` once listening, like the sink,
and stops on SIGTERM or SIGINT.

Usage (from the repository root)::

    python frontend/e2e/support/workspace_smtp.py --port 18492 --out <run>/mail.jsonl --run-dir <run>
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests" / "support"))

from smtp_sink import SmtpSink  # noqa: E402 — found through the path set just above

#: How often the control files are looked at; the spec waits for the state files anyway.
POLL_SECONDS = 0.05


class Hold:
    """``<run>/smtp.hold`` → the sink's greeting gate, and its state file for the spec."""

    def __init__(self, sink: SmtpSink, gate: threading.Event, control: Path, state_file: Path) -> None:
        self.sink, self.gate, self.control, self.state_file = sink, gate, control, state_file
        self.shown = ""

    def follow(self) -> None:
        if self.control.exists():
            self.gate.clear()
        else:
            self.gate.set()
        state = f"{'released' if self.gate.is_set() else 'held'} {self.sink.connections}"
        if state != self.shown:
            write_state(self.state_file, state)
            self.shown = state


def write_state(path: Path, state: str) -> None:
    """Replace the state file in one step, so the spec never reads half of it."""
    partial = path.with_suffix(".tmp")
    partial.write_text(state, encoding="utf-8")
    partial.replace(path)


def serve(sink: SmtpSink, control: Path, state_file: Path, stop: threading.Event, hold: Hold) -> None:
    """Follow the control files until *stop* is set: listening while ``smtp.down`` is absent."""
    listening = True
    write_state(state_file, "up")
    hold.follow()
    while not stop.wait(POLL_SECONDS):
        hold.follow()
        wanted = not control.exists()
        if wanted == listening:
            continue
        if wanted:
            try:
                sink.start()
            except OSError as exc:  # the port is not free yet: still down, try again next poll
                print(f"SMTP sink could not listen again yet ({exc})", flush=True)
                continue
        else:
            sink.stop()
        listening = wanted
        write_state(state_file, "up" if listening else "down")
        print(f"SMTP sink {'listening again' if listening else 'stopped'} on port {sink.requested_port}",
              flush=True)
    hold.gate.set()  # a greeting still held is released, so nothing waits out GATE_TIMEOUT
    if listening:
        sink.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Workspace journey's SMTP sink, with an off switch.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True, help="append messages as JSON lines")
    parser.add_argument("--run-dir", type=Path, required=True, help="where smtp.down / smtp.hold and their states live")
    args = parser.parse_args(argv)
    control = args.run_dir / "smtp.down"
    state_file = args.run_dir / "smtp.state"
    hold_control = args.run_dir / "smtp.hold"
    # A file left by an interrupted run must not start this one with the server down or held.
    control.unlink(missing_ok=True)
    hold_control.unlink(missing_ok=True)
    gate = threading.Event()
    gate.set()
    sink = SmtpSink("127.0.0.1", args.port, out=args.out, greeting_gate=gate).start()
    hold = Hold(sink, gate, hold_control, args.run_dir / "smtp.hold.state")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print(f"READY {sink.host}:{sink.port}", flush=True)
    serve(sink, control, state_file, stop, hold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
