"""Run the Workspace journey's model server, and let the journey stop it and start it again.

The journey proves that a model server which goes away is explained honestly (spec §8, §9):
the chat names the reason in Romanian, the top bar's chip says the model is unavailable, a
report run fails with the same reason, and everything recovers once the server is back. For
that the model server has to really go away for a while (its port refuses connections, as when
LM Studio or Ollama is stopped; the hub's settings stay as they are) and come back on the same
port. Playwright owns this process (``playwright.workspace.config.ts`` → the ``model`` web
server) and the spec cannot signal it, so the two talk through files in the run directory, as
for the SMTP sink (``workspace_smtp.py``):

* ``<run>/model.down`` exists → the server stops listening (new connections are refused, and
  the open ones are dropped, as in a real outage);
* the file is gone → the server listens again on the same port;
* after every change ``<run>/model.state`` holds ``down`` or ``up`` (the spec waits for it, and
  then for the port itself to agree — support/workspace-helpers.ts → ``setModelServer``).

The server is ``tests/support/fake_openai_server.py``'s, unchanged: the same answers, the same
trigger phrases, the same ``--token-delay``. Prints ``READY`` once listening, like that script,
and stops on SIGTERM or SIGINT.

Usage (from the repository root)::

    python frontend/e2e/support/workspace_model.py --port 18491 --token-delay 0.02 --run-dir <run>
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests" / "support"))

from fake_openai_server import FakeOpenAIServer  # noqa: E402 — found through the path above

#: How often the control file is looked at; the spec waits for the state file anyway.
POLL_SECONDS = 0.05


def write_state(path: Path, state: str) -> None:
    """Replace the state file in one step, so the spec never reads half of it."""
    partial = path.with_suffix(".tmp")
    partial.write_text(state, encoding="utf-8")
    partial.replace(path)


def serve(server: FakeOpenAIServer, control: Path, state_file: Path, stop: threading.Event) -> None:
    """Follow the control file until *stop* is set: listening while it is absent."""
    listening = True
    write_state(state_file, "up")
    while not stop.wait(POLL_SECONDS):
        wanted = not control.exists()
        if wanted == listening:
            continue
        if wanted:
            try:
                server.start()
            except OSError as exc:  # the port is not free yet: still down, try again next poll
                print(f"model server could not listen again yet ({exc})", flush=True)
                continue
        else:
            server.stop()
        listening = wanted
        write_state(state_file, "up" if listening else "down")
        print(f"model server {'listening again' if listening else 'stopped'}", flush=True)
    if listening:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Workspace journey's model server, with an off switch.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-delay", type=float, default=0.0, help="seconds between streamed chunks")
    parser.add_argument("--run-dir", type=Path, required=True, help="where model.down / model.state live")
    args = parser.parse_args(argv)
    control = args.run_dir / "model.down"
    state_file = args.run_dir / "model.state"
    # A file left by an interrupted run must not start this one with the server down.
    control.unlink(missing_ok=True)
    server = FakeOpenAIServer(port=args.port, token_delay=args.token_delay).start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print("READY", flush=True)
    print(f"fake OpenAI-compatible server listening on {server.url}", file=sys.stderr, flush=True)
    serve(server, control, state_file, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
