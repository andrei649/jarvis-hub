"""H273 second review (A1) — the doctor's admin credential goes only where /readyz vouched.

The doctor's hub read sent ``JARVIS_ADMIN_TOKEN`` whenever it was set, through urllib's
default opener: it followed a cross-origin redirect with the header attached, and went
through an ``http_proxy`` that answered /readyz itself. Now:

- every request to the hub goes through ``doctor.hub_open``: it never follows a redirect
  (a 3xx is an error, and the doctor predicts instead), and it never goes through a proxy
  to a hub on this machine;
- the admin credential is sent only to a loopback hub, and only after the route refused
  the request without it (a hub in its localhost dev posture answers without one);
- the credentialed read goes to the configured hub, and ``run_doctor`` wires it.

The redirect and the proxy are real local servers: only a real socket and the real
urllib machinery show where a header actually goes.
"""
import http.server
import json
import sys
import threading
import urllib.error
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from scripts import doctor  # noqa: E402

SOURCES = {"sources": [{"key": "PROV_FROM_HUB", "layer": "repo_env", "shadowed": [], "label": "repo .env"}],
           "files": {}}


class _Server:
    """A loopback HTTP server that records every request and answers from ``respond``."""

    def __init__(self, respond):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                status, body, headers = respond(self.path, {k.lower(): v for k, v in self.headers.items()})
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servers():
    made = []

    def make(respond):
        server = _Server(respond)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


def _needs_token(token):
    """A hub whose sources route needs the admin credential (a hub with one configured)."""
    def respond(path, headers):
        if path == "/readyz":
            return 200, b"ok", {}
        if path == doctor.ENV_SOURCES_PATH:
            if headers.get("x-admin-token") != token:
                return 401, b'{"detail":"admin token required"}', {"Content-Type": "application/json"}
            return 200, json.dumps(SOURCES).encode(), {"Content-Type": "application/json"}
        return 404, b"", {}
    return respond


def test_a_redirect_is_refused_and_the_credential_never_reaches_another_origin(tmp_path, servers):
    other = servers(lambda path, headers: (200, json.dumps(SOURCES).encode(), {}))

    def hub_respond(path, headers):
        if path == "/readyz":
            return 200, b"ok", {}
        return 302, b"", {"Location": other.url + path}

    hub = servers(hub_respond)
    env = {"NERVA_HUB_URL": hub.url, "JARVIS_ADMIN_TOKEN": "adm-SECRET-redirect"}
    readyz = doctor.check_readyz(doctor.hub_open, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=doctor.hub_open, readyz=readyz)
    assert other.requests == []                                        # nothing followed the 302
    assert check.detail.startswith("predicted")


def test_a_loopback_hub_is_never_reached_through_a_proxy(tmp_path, servers, monkeypatch):
    proxy = servers(lambda path, headers: (200, json.dumps(SOURCES).encode(), {}))
    hub = servers(_needs_token("adm-SECRET-proxy"))
    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, proxy.url)
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    env = {"NERVA_HUB_URL": hub.url, "JARVIS_ADMIN_TOKEN": "adm-SECRET-proxy"}
    readyz = doctor.check_readyz(doctor.hub_open, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=doctor.hub_open, readyz=readyz)
    assert proxy.requests == []
    assert check.detail.startswith(f"read from the running hub at {hub.url}")


def test_a_loopback_hub_is_asked_without_the_credential_first(tmp_path, servers):
    def dev_posture(path, headers):                                     # no admin token configured
        if path == "/readyz":
            return 200, b"ok", {}
        return 200, json.dumps(SOURCES).encode(), {"Content-Type": "application/json"}

    hub = servers(dev_posture)
    env = {"NERVA_HUB_URL": hub.url, "JARVIS_ADMIN_TOKEN": "adm-SECRET-dev"}
    readyz = doctor.check_readyz(doctor.hub_open, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=doctor.hub_open, readyz=readyz)
    assert check.detail.startswith("read from the running hub")
    assert all("x-admin-token" not in headers for _path, headers in hub.requests)


def test_the_credential_follows_a_refusal_on_loopback(tmp_path, servers):
    hub = servers(_needs_token("adm-SECRET-loop"))
    env = {"NERVA_HUB_URL": hub.url, "JARVIS_ADMIN_TOKEN": "adm-SECRET-loop"}
    readyz = doctor.check_readyz(doctor.hub_open, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=doctor.hub_open, readyz=readyz)
    assert check.detail.startswith("read from the running hub")
    sources = [headers for path, headers in hub.requests if path == doctor.ENV_SOURCES_PATH]
    assert [h.get("x-admin-token") for h in sources] == [None, "adm-SECRET-loop"]


def _fake(seen, *, answers_without_token=False):
    """A fake opener for a hub at any address: /readyz is ok, the sources route needs the
    admin credential unless ``answers_without_token``."""
    class _Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def opener(request, timeout=None):
        url = getattr(request, "full_url", request)
        headers = {k.lower(): v for k, v in dict(getattr(request, "headers", {}) or {}).items()}
        seen.append((url, headers))
        if url.endswith("/readyz"):
            return _Resp(b"ok")
        if url.endswith(doctor.ENV_SOURCES_PATH):
            if answers_without_token or headers.get("x-admin-token"):
                return _Resp(json.dumps(SOURCES).encode())
            raise urllib.error.HTTPError(url, 401, "admin token required", {}, None)
        raise urllib.error.URLError("nothing here")
    return opener


def test_a_hub_off_this_machine_never_gets_the_admin_credential(tmp_path):
    seen = []
    opener = _fake(seen)
    env = {"NERVA_HUB_URL": "http://hub.lan:8080", "JARVIS_ADMIN_TOKEN": "adm-SECRET-lan"}
    readyz = doctor.check_readyz(opener, env=env)
    check = doctor.check_config_sources(tmp_path, env, opener=opener, readyz=readyz)
    assert all("x-admin-token" not in headers for _url, headers in seen)
    assert check.detail.startswith("predicted")
    assert "only to a hub on this machine" in check.detail


def test_the_credentialed_read_goes_to_the_configured_hub(tmp_path):
    seen = []
    opener = _fake(seen)
    env = {"NERVA_HUB_URL": "http://127.0.0.1:9123", "JARVIS_ADMIN_TOKEN": "adm-SECRET-9123"}
    readyz = doctor.check_readyz(opener, env=env)
    doctor.check_config_sources(tmp_path, env, opener=opener, readyz=readyz)
    credentialed = [url for url, headers in seen if headers.get("x-admin-token")]
    assert credentialed == ["http://127.0.0.1:9123" + doctor.ENV_SOURCES_PATH]


def test_run_doctor_reads_the_hubs_table(tmp_path):
    seen = []
    report = doctor.run_doctor(tmp_path, env={"JARVIS_ADMIN_TOKEN": "adm-SECRET-run"},
                               opener=_fake(seen), version_info=(3, 12, 0, "final", 0))
    check = next(c for c in report.checks if c.name == "config_sources")
    assert check.detail.startswith("read from the running hub")


def test_run_doctor_reaches_the_hub_only_through_the_safe_opener(tmp_path, monkeypatch):
    used = []

    def recording(request, timeout=None):
        used.append(getattr(request, "full_url", request))
        raise urllib.error.URLError("not running")

    monkeypatch.setattr(doctor, "hub_open", recording)
    monkeypatch.setattr(doctor, "check_runtimes", lambda opener: doctor.Check("runtimes", doctor.OK, "stubbed"))
    doctor.run_doctor(tmp_path, env={"NERVA_HUB_URL": "http://127.0.0.1:9555"}, version_info=(3, 12, 0, "final", 0))
    assert used and all(url.startswith("http://127.0.0.1:9555") for url in used)
