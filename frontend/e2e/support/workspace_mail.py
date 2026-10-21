"""Decode the SMTP sink's messages for the Workspace journey.

``tests/support/smtp_sink.py --out <file>`` appends one JSON line per message with the raw
RFC 5322 bytes in ``data``. A body sent as UTF-8 travels base64 or quoted-printable encoded,
so the spec cannot read it with a regex; this script parses each message with the standard
library's ``email`` package (the same parser real mail clients rely on) and prints a JSON
array of ``{mail_from, rcpt_tos, subject, from, to, text, html}``.

``python frontend/e2e/support/workspace_mail.py <mail.jsonl>``
"""

from __future__ import annotations

import json
import sys
from email import message_from_bytes, policy
from pathlib import Path


def part(message, subtype: str) -> str:
    body = message.get_body(preferencelist=(subtype,))
    return body.get_content().replace("\r\n", "\n") if body is not None else ""


def decode(line: str) -> dict:
    record = json.loads(line)
    message = message_from_bytes(record["data"].encode("utf-8"), policy=policy.default)
    return {
        "mail_from": record["mail_from"],
        "rcpt_tos": record["rcpt_tos"],
        "subject": str(message["Subject"] or ""),
        "from": str(message["From"] or ""),
        "to": str(message["To"] or ""),
        "text": part(message, "plain"),
        "html": part(message, "html"),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: workspace_mail.py <mail.jsonl>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    print(json.dumps([decode(line) for line in lines if line.strip()], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
