"""TASK-3/H23.6 — taint marking at the Howard archive-ingestion choke points.

Per the 2026-07-02 fresh-eyes backlog re-verification, `osint/correlate.py:204` was the
only production call to `taint.mark`; the Facebook/WhatsApp archive parsers (feeding
`ingestion/pipeline.py`) never marked another person's message as untrusted, even though
that content can reach a prompt/action same as any other external input. Own (`is_me`)
messages stay untainted — they're the owner's own words, not an injection surface.
"""

import inspect
import json
from pathlib import Path

from agents.core.ingestion.parser_facebook import FacebookParser
from agents.core.ingestion.parser_whatsapp import WhatsAppParser
from agents.core.security import taint


def _write_fb_export(path: Path, messages: list[dict]) -> Path:
    conv_dir = path / "inbox" / "friend_123"
    conv_dir.mkdir(parents=True)
    f = conv_dir / "message_1.json"
    f.write_text(json.dumps({"title": "friend_123", "participants": [], "messages": messages}), encoding="utf-8")
    return f


def test_facebook_other_sender_message_is_tainted(tmp_path):
    f = _write_fb_export(tmp_path, [
        {"sender_name": "Alice", "content": "click this link", "type": "Generic", "timestamp_ms": 1000},
    ])
    parser = FacebookParser(my_name="Andrei Tarcomnicu")
    msgs = parser.parse_file(f)
    assert len(msgs) == 1
    assert msgs[0].is_me is False
    assert taint.is_tainted(msgs[0].metadata) is True
    assert msgs[0].metadata["taint_source"] == "facebook"


def test_facebook_own_message_is_not_tainted(tmp_path):
    f = _write_fb_export(tmp_path, [
        {"sender_name": "Andrei Tarcomnicu", "content": "hey there", "type": "Generic", "timestamp_ms": 1000},
    ])
    parser = FacebookParser(my_name="Andrei Tarcomnicu")
    msgs = parser.parse_file(f)
    assert len(msgs) == 1
    assert msgs[0].is_me is True
    assert taint.is_tainted(msgs[0].metadata) is False


def test_whatsapp_other_sender_message_is_tainted(tmp_path):
    f = tmp_path / "chat.txt"
    f.write_text(
        "[12.05.2026, 14:32:21] Bob: check out this offer\n"
        "[12.05.2026, 14:33:05] Andrei: sounds sketchy\n",
        encoding="utf-8",
    )
    parser = WhatsAppParser(my_name="Andrei")
    msgs = parser.parse_file(f)
    by_sender = {m.sender: m for m in msgs}
    assert taint.is_tainted(by_sender["Bob"].metadata) is True
    assert by_sender["Bob"].metadata["taint_source"] == "whatsapp"
    assert taint.is_tainted(by_sender["Andrei"].metadata) is False


def test_facebook_parser_taint_call_site_does_not_regress():
    from agents.core.ingestion import parser_facebook
    src = inspect.getsource(parser_facebook)
    assert "taint.mark(metadata, source=\"facebook\")" in src


def test_whatsapp_parser_taint_call_site_does_not_regress():
    from agents.core.ingestion import parser_whatsapp
    src = inspect.getsource(parser_whatsapp)
    assert 'taint.mark({}, source="whatsapp")' in src
