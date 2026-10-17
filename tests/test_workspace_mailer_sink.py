"""The SMTP sink the S4 suites and the e2e journey rely on (``tests/support/smtp_sink.py``).

If the sink mis-parsed SMTP, every mailer test above it would prove nothing, so its
protocol handling is checked against stdlib ``smtplib`` and raw commands, and its CLI
mode (``READY`` line, JSON-lines output) is run as the e2e journey runs it.
"""

from __future__ import annotations

import json
import smtplib
import socket
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

from tests.support.smtp_sink import SmtpSink

SINK = Path(__file__).parent / "support" / "smtp_sink.py"


def _message(body: str = "Salut,\n.linie cu punct\nfinal") -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Test ăîșț"
    message["From"] = "a@acme.test"
    message["To"] = "b@client.ro"
    message.set_content(body)
    return message


def test_it_receives_what_smtplib_sends_and_undoes_dot_stuffing():
    with SmtpSink() as sink, smtplib.SMTP("127.0.0.1", sink.port, timeout=5) as client:
        client.send_message(_message())
        [mail] = sink.wait_for(1)
    assert mail.mail_from == "a@acme.test" and mail.rcpt_tos == ["b@client.ro"]
    assert mail.subject == "Test ăîșț"
    assert mail.part("plain") == "Salut,\n.linie cu punct\nfinal\n"


@pytest.mark.parametrize("mechanism", ["PLAIN", "LOGIN"])
def test_auth_mechanisms_and_refusals(mechanism):
    with SmtpSink(require_auth=("robot", "p4ss"), refuse=["nimeni@client.ro"]) as sink:
        with smtplib.SMTP("127.0.0.1", sink.port, timeout=5) as client:
            client.ehlo()
            client.user, client.password = "robot", "p4ss"
            method = client.auth_plain if mechanism == "PLAIN" else client.auth_login
            assert client.auth(mechanism, method)[0] == 235
            refused = client.sendmail("a@acme.test", ["b@client.ro", "nimeni@client.ro"], b"x")
        assert refused == {"nimeni@client.ro": (550, b"mailbox unavailable")}
        assert sink.wait_for(1)[0].auth_user == "robot"
        with smtplib.SMTP("127.0.0.1", sink.port, timeout=5) as client, \
                pytest.raises(smtplib.SMTPAuthenticationError):
            client.login("robot", "gresit")


def test_raw_commands_get_rfc_replies():
    with SmtpSink() as sink, socket.create_connection(("127.0.0.1", sink.port), timeout=5) as raw:
        reader = raw.makefile("rb")
        assert reader.readline().startswith(b"220 ")
        for command, expected in [(b"HELO x", b"250"), (b"NOOP", b"250"), (b"DATA", b"503"),
                                  (b"RCPT TO:<b@c.ro>", b"503"), (b"STARTTLS", b"454"),
                                  (b"VRFY a", b"502"), (b"RSET", b"250"), (b"QUIT", b"221")]:
            raw.sendall(command + b"\r\n")
            assert reader.readline().startswith(expected), command
        reader.close()


def test_cli_mode_prints_ready_and_writes_json_lines(tmp_path):
    out = tmp_path / "mail.jsonl"
    process = subprocess.Popen([sys.executable, str(SINK), "--port", "0", "--out", str(out)],
                               stdout=subprocess.PIPE, text=True)
    try:
        ready = process.stdout.readline().strip()
        assert ready.startswith("READY 127.0.0.1:")
        port = int(ready.rsplit(":", 1)[1])
        with smtplib.SMTP("127.0.0.1", port, timeout=5) as client:
            client.send_message(_message("corp"))
        [line] = out.read_text(encoding="utf-8").splitlines()
        stored = json.loads(line)
        assert stored["rcpt_tos"] == ["b@client.ro"] and stored["subject"] == "Test ăîșț"
        assert "corp" in stored["data"]
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
