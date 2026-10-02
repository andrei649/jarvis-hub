"""Image retry authority is disclosed before the terminal sends image bytes."""
import io

import pytest

from agents.cli import nerva
from tests.test_nerva_chat_image import LOCAL, PNG_BYTES, REMOTE, Fake, _run

NOTICE = "May retry once with the same images and model after an empty response (at most two model calls)."


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(PNG_BYTES)
    return path


@pytest.mark.parametrize("remote", [False, True])
def test_retry_disclosure_precedes_native_cli_submission(png, remote):
    out, err = io.StringIO(), io.StringIO()
    status = REMOTE if remote else LOCAL

    class ObservedHub(Fake):
        def post(self, path, body=None, *, timeout=None):
            assert NOTICE in err.getvalue(), "retry budget must be visible before images leave CLI"
            return super().post(path, body, timeout=timeout)

    hub = ObservedHub(status={**status, "empty_retries": 1, "retry_notice": NOTICE})
    ctx = nerva.Context(environ={}, out=out, err=err, client_factory=lambda env: hub)
    argv = ["chat", "-z", "--image", str(png)]
    if remote:
        argv += ["--remote-vision", REMOTE["destination"]]
    code = nerva.main([*argv, "Describe this"], context=ctx)
    assert code == nerva.EXIT_OK and out.getvalue() == "A screenshot.\n"
    assert hub.calls[-1][2]["expected_binding"] == status["binding"]
    assert hub.calls[-1][2]["remote_ack"] is remote


@pytest.mark.parametrize("metadata", [
    {"empty_retries": 0, "retry_notice": NOTICE},
    {"empty_retries": True, "retry_notice": NOTICE},
    {"empty_retries": "1", "retry_notice": NOTICE},
    {"empty_retries": 1},
    {"retry_notice": NOTICE},
    {"empty_retries": 1, "retry_notice": " "},
    {"empty_retries": 1, "retry_notice": "x" * 501},
    {"empty_retries": 1, "retry_notice": "private\x1b[2J"},
    {"empty_retries": 1, "retry_notice": "private\nnew line"},
    {"empty_retries": 1, "retry_notice": None},
])
def test_malformed_retry_metadata_never_sends_images(png, metadata):
    hub = Fake(status={**LOCAL, **metadata})
    code, out, err = _run(["-z", "--image", str(png), "Describe this"], hub)
    assert code == nerva.EXIT_FAILED and out == ""
    assert [method for method, _, _ in hub.calls] == ["GET"]
    assert "retry policy" in err and "nothing was sent" in err
    assert "private" not in err


def test_remote_retry_notice_does_not_replace_destination_ack(png):
    hub = Fake(status={**REMOTE, "empty_retries": 1, "retry_notice": NOTICE})
    code, out, err = _run(["-z", "--image", str(png), "Describe this"], hub)
    assert code == nerva.EXIT_USAGE and out == ""
    assert NOTICE in err and "--remote-vision" in err
    assert [method for method, _, _ in hub.calls] == ["GET"]


def test_legacy_status_keeps_the_original_terminal_answer(png):
    code, out, err = _run(["-z", "--image", str(png), "Describe this"], Fake())
    assert code == nerva.EXIT_OK and out == "A screenshot.\n"
    assert "retry" not in err
