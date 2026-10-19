"""A tiny threaded SMTP server that keeps every message it receives (tests and e2e).

Why it exists. Python 3.12 removed ``smtpd`` and the repo has no ``aiosmtpd``, yet the
workspace mailer must be proven against a real SMTP conversation: EHLO, AUTH, MAIL,
RCPT, DATA and QUIT over a socket, exactly what ``smtplib`` speaks in production. This
sink implements that much of RFC 5321 (plain SMTP on 127.0.0.1, no TLS — STARTTLS is
answered ``454``) and stores what arrives.

In a test::

    from tests.support.smtp_sink import SmtpSink

    with SmtpSink() as sink:          # binds 127.0.0.1 on a free port
        ...                           # point the mailer at 127.0.0.1:sink.port
        sink.wait_for(1)
        assert sink.messages[0].subject == "Raport"

Options: ``refuse`` (addresses answered ``550`` at RCPT), ``require_auth=(user,
password)`` (AUTH PLAIN/LOGIN required before MAIL, ``535`` on a wrong pair),
``fail_data`` (``554`` after DATA), ``out`` (append each message to a JSON-lines file),
``greeting_delay`` (seconds every connection waits before the ``220`` greeting — a slow
relay; a plain attribute, so it can change while the sink runs) and ``greeting_gate`` (a
``threading.Event``: each connection holds its greeting until the event is set, for at most
:data:`GATE_TIMEOUT` seconds — what a test uses to look at a delivery while it is still
under way). :meth:`SmtpSink.wait_for_connections` blocks until a client has connected.

From the e2e journey (prints ``READY`` once listening, runs until killed)::

    python tests/support/smtp_sink.py --port 2525 --out /tmp/mail.jsonl [--greeting-delay 4]
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import socketserver
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

MAX_LINE = 4096
MAX_MESSAGE = 10 * 1024 * 1024
#: The longest a held greeting waits for ``greeting_gate`` (a test that forgets to set it
#: still ends: the client then gets its greeting late, as from a slow relay).
GATE_TIMEOUT = 30.0
_ADDRESS = re.compile(r"<([^<>]*)>")


@dataclass
class ReceivedMail:
    """One message as the sink received it."""

    mail_from: str
    rcpt_tos: list[str]
    data: bytes
    auth_user: str | None
    received_at: float

    def message(self) -> EmailMessage:
        """The parsed message (``email.policy.default``: headers decoded, parts walkable)."""
        parsed = message_from_bytes(self.data, policy=policy.default)
        assert isinstance(parsed, EmailMessage)
        return parsed

    @property
    def subject(self) -> str:
        return str(self.message()["Subject"] or "")

    def header(self, name: str) -> str:
        """A decoded header value ('' when absent)."""
        return str(self.message()[name] or "")

    def part(self, subtype: str) -> str:
        """The decoded ``text/<subtype>`` body with ``\\n`` line ends ('' when absent)."""
        body = self.message().get_body(preferencelist=(subtype,))
        return body.get_content().replace("\r\n", "\n") if body is not None else ""

    def to_json(self) -> dict:
        return {
            "mail_from": self.mail_from, "rcpt_tos": self.rcpt_tos, "subject": self.subject,
            "auth_user": self.auth_user, "received_at": self.received_at,
            "data": self.data.decode("utf-8", "replace"),
        }


class _Session:
    """State of one SMTP connection."""

    def __init__(self) -> None:
        self.mail_from: str | None = None
        self.rcpt_tos: list[str] = []
        self.auth_user: str | None = None

    def reset(self) -> None:
        self.mail_from = None
        self.rcpt_tos = []


def _address(argument: str) -> str:
    match = _ADDRESS.search(argument)
    return (match.group(1) if match else argument.split(":", 1)[-1]).strip()


def _b64(text: str) -> str:
    try:
        return base64.b64decode(text.strip(), validate=True).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return ""


class _Handler(socketserver.StreamRequestHandler):
    """Speaks the server side of one SMTP conversation."""

    server: _Server

    def _reply(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8") + b"\r\n")
        self.wfile.flush()

    def _line(self) -> str | None:
        raw = self.rfile.readline(MAX_LINE)
        if not raw:
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def handle(self) -> None:
        sink = self.server.sink
        session = _Session()
        sink._connected()
        gate = sink.greeting_gate
        if gate is not None:
            gate.wait(GATE_TIMEOUT)
        elif sink.greeting_delay > 0:
            time.sleep(sink.greeting_delay)
        self._reply("220 nerva-test-sink ESMTP ready")
        while True:
            line = self._line()
            if line is None:
                return
            verb, _, argument = line.partition(" ")
            verb = verb.upper()
            if verb == "QUIT":
                self._reply("221 bye")
                return
            self._dispatch(sink, session, verb, argument)

    def _dispatch(self, sink: SmtpSink, session: _Session, verb: str, argument: str) -> None:
        if verb == "EHLO":
            self._reply("250-nerva-test-sink")
            self._reply("250-AUTH PLAIN LOGIN")
            self._reply("250-8BITMIME")
            self._reply(f"250 SIZE {MAX_MESSAGE}")
        elif verb == "HELO":
            self._reply("250 nerva-test-sink")
        elif verb == "AUTH":
            self._auth(sink, session, argument)
        elif verb == "MAIL":
            if sink.require_auth is not None and session.auth_user is None:
                self._reply("530 authentication required")
                return
            session.reset()
            session.mail_from = _address(argument)
            self._reply("250 sender ok")
        elif verb == "RCPT":
            self._rcpt(sink, session, argument)
        elif verb == "DATA":
            self._data(sink, session)
        elif verb == "RSET":
            session.reset()
            self._reply("250 reset")
        elif verb == "NOOP":
            self._reply("250 ok")
        elif verb == "STARTTLS":
            self._reply("454 TLS not available on the test sink")
        else:
            self._reply("502 command not implemented")

    def _rcpt(self, sink: SmtpSink, session: _Session, argument: str) -> None:
        if session.mail_from is None:
            self._reply("503 MAIL first")
            return
        address = _address(argument)
        if address.lower() in sink.refuse:
            self._reply("550 mailbox unavailable")
            return
        session.rcpt_tos.append(address)
        self._reply("250 recipient ok")

    def _auth(self, sink: SmtpSink, session: _Session, argument: str) -> None:
        mechanism, _, initial = argument.partition(" ")
        mechanism = mechanism.upper()
        if mechanism == "PLAIN":
            if not initial:
                self._reply("334 ")
                initial = self._line() or ""
            parts = _b64(initial).split("\x00")
            user, password = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
        elif mechanism == "LOGIN":
            if not initial:
                self._reply("334 VXNlcm5hbWU6")
                initial = self._line() or ""
            user = _b64(initial)
            self._reply("334 UGFzc3dvcmQ6")
            password = _b64(self._line() or "")
        else:
            self._reply("504 mechanism not supported")
            return
        if sink.require_auth is not None and (user, password) != sink.require_auth:
            self._reply("535 authentication failed")
            return
        session.auth_user = user
        self._reply("235 authenticated")

    def _data(self, sink: SmtpSink, session: _Session) -> None:
        if session.mail_from is None or not session.rcpt_tos:
            self._reply("503 need MAIL and RCPT first")
            return
        self._reply("354 end with <CRLF>.<CRLF>")
        lines: list[bytes] = []
        size = 0
        while True:
            raw = self.rfile.readline(MAX_LINE + 2)
            if not raw:
                return
            if raw in (b".\r\n", b".\n"):
                break
            # RFC 5321 §4.5.2: a leading dot was doubled by the client.
            line = raw[1:] if raw.startswith(b"..") else raw
            size += len(line)
            if size <= MAX_MESSAGE:
                lines.append(line)
        if sink.fail_data:
            self._reply("554 transaction failed")
            session.reset()
            return
        sink._store(ReceivedMail(mail_from=session.mail_from, rcpt_tos=list(session.rcpt_tos),
                                 data=b"".join(lines), auth_user=session.auth_user,
                                 received_at=time.time()))
        session.reset()
        self._reply("250 message accepted")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], sink: SmtpSink) -> None:
        self.sink = sink
        super().__init__(address, _Handler)


class SmtpSink:
    """A running SMTP sink; use it as a context manager or call start()/stop()."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, *, refuse: Iterable[str] = (),
                 require_auth: tuple[str, str] | None = None, fail_data: bool = False,
                 out: Path | None = None, greeting_delay: float = 0.0,
                 greeting_gate: threading.Event | None = None) -> None:
        self.host = host
        self.requested_port = port
        self.refuse = {address.lower() for address in refuse}
        self.require_auth = require_auth
        self.fail_data = fail_data
        self.out = out
        self.greeting_delay = greeting_delay
        self.greeting_gate = greeting_gate
        #: How many SMTP connections were accepted so far.
        self.connections = 0
        self.messages: list[ReceivedMail] = []
        self._changed = threading.Condition()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the sink is not running")
        return int(self._server.server_address[1])

    def start(self) -> SmtpSink:
        self._server = _Server((self.host, self.requested_port), self)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True,
                                        name="smtp-sink")
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> SmtpSink:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _store(self, mail: ReceivedMail) -> None:
        with self._changed:
            self.messages.append(mail)
            if self.out is not None:
                with self.out.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(mail.to_json(), ensure_ascii=False) + "\n")
            self._changed.notify_all()

    def _connected(self) -> None:
        with self._changed:
            self.connections += 1
            self._changed.notify_all()

    def wait_for_connections(self, count: int, timeout: float = 5.0) -> None:
        """Block until at least *count* clients connected (``AssertionError`` on timeout)."""
        with self._changed:
            if not self._changed.wait_for(lambda: self.connections >= count, timeout=timeout):
                raise AssertionError(f"expected {count} connection(s), got {self.connections}")

    def wait_for(self, count: int, timeout: float = 5.0) -> list[ReceivedMail]:
        """Block until at least *count* messages arrived (``AssertionError`` on timeout)."""
        with self._changed:
            if not self._changed.wait_for(lambda: len(self.messages) >= count, timeout=timeout):
                raise AssertionError(f"expected {count} message(s), got {len(self.messages)}")
            return list(self.messages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local SMTP sink (no TLS).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2525)
    parser.add_argument("--out", type=Path, default=None, help="append messages as JSON lines")
    parser.add_argument("--greeting-delay", type=float, default=0.0, metavar="SECONDS",
                        help="wait this long before greeting each connection (a slow relay)")
    args = parser.parse_args(argv)
    sink = SmtpSink(args.host, args.port, out=args.out,
                    greeting_delay=max(0.0, args.greeting_delay)).start()
    print(f"READY {sink.host}:{sink.port}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        sink.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
