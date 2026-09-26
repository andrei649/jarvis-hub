"""H504 — TLS trust fails loudly when it is misconfigured, and is never quietly off.

Three halves, each against the real thing where it can be:

- **boot validation**: every CA variable that is set (and certifi) must exist, be the
  right kind, load and hold a certificate; a broken one stops the start with the
  variable's name and a command that repairs it;
- **model egress on the anchor**: every model backend's client verifies against the one
  trust anchor, so ``JARVIS_CA_BUNDLE`` reaches model calls and a bad ``SSL_CERT_FILE``
  can no longer surface as an unnamed ``FileNotFoundError`` — proved end to end against
  a real HTTPS server whose certificate only the test's own CA signs;
- **the per-target off switch**: only a target named in ``JARVIS_TLS_INSECURE_TARGETS``
  is built without verification, each such client is announced with a WARNING naming
  its URL, the hardened profile refuses the list, and a bad CA path never means off.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import ssl
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from ipaddress import IPv4Address
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core import tls_trust  # noqa: E402

CA_VARIABLES = ("JARVIS_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_DIR")
PROXY_VARIABLES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Nothing from the box: no CA variable, no insecure list, not hardened, no proxy."""
    for name in (*CA_VARIABLES, *PROXY_VARIABLES, tls_trust.INSECURE_TARGETS_ENV, "JARVIS_HARDENED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


# ── certificates the test controls ───────────────────────────────────────────


def _crypto():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    return x509, hashes, serialization, ec, NameOID


def _make_ca(tmp_path, name="nerva-h504-ca"):
    x509, hashes, serialization, ec, NameOID = _crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / f"{name}.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path, key, cert


def _make_leaf(tmp_path, ca_key, ca_cert):
    """A server certificate for 127.0.0.1 signed by the test CA: (cert path, key path)."""
    x509, hashes, serialization, ec, NameOID = _crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
        .issuer_name(ca_cert.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("127.0.0.1"))]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "leaf.pem", tmp_path / "leaf.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def _self_signed_leaf(tmp_path):
    """A self-signed server certificate with no CA flag — a pinned anchor some owners use."""
    x509, hashes, serialization, ec, NameOID = _crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pinned.lan")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "pinned.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def _crl_only(tmp_path):
    """A PEM that loads as trust material but holds no certificate: one CRL."""
    x509, hashes, serialization, ec, NameOID = _crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    crl = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "crl-only")]))
        .last_update(now - timedelta(days=1)).next_update(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "crl.pem"
    path.write_bytes(crl.public_bytes(serialization.Encoding.PEM))
    return path


def _subjects(context: ssl.SSLContext) -> set[str]:
    return {value for cert in context.get_ca_certs() for rdn in cert.get("subject", ()) for _k, value in rdn}


def _pool_context(client: httpx.AsyncClient) -> ssl.SSLContext:
    return client._transport._pool._ssl_context


# ── boot validation ──────────────────────────────────────────────────────────


def test_nothing_set_is_fine_and_a_good_value_in_every_variable_is_fine(tmp_path):
    assert tls_trust.validate_ca_environment({}) == []
    assert tls_trust.validate_ca_environment(dict.fromkeys(CA_VARIABLES, "  ")) == []
    ca, _key, _cert = _make_ca(tmp_path)
    env = dict.fromkeys(tls_trust.CA_FILE_VARIABLES, str(ca))
    env["SSL_CERT_DIR"] = f"{tmp_path}{os.pathsep}{tmp_path}"
    assert tls_trust.validate_ca_environment(env) == []


def test_a_pinned_self_signed_server_certificate_counts_as_an_anchor(tmp_path):
    """No CA flag, still a certificate OpenSSL will trust: never refuse the start for it."""
    assert tls_trust.validate_ca_environment({"JARVIS_CA_BUNDLE": str(_self_signed_leaf(tmp_path))}) == []


@pytest.mark.parametrize("variable", tls_trust.CA_FILE_VARIABLES)
def test_every_file_variable_is_checked_and_named(tmp_path, variable):
    empty = tmp_path / "empty.pem"
    empty.write_bytes(b"")
    junk = tmp_path / "junk.pem"
    junk.write_text("-----BEGIN CERTIFICATE-----\nnot base64 at all\n-----END CERTIFICATE-----\n", encoding="utf-8")
    text = tmp_path / "notes.txt"
    text.write_text("this is not a certificate bundle\n" * 4, encoding="utf-8")
    cases = {
        str(tmp_path / "missing.pem"): "does not exist",
        str(tmp_path): "is not a file",
        str(empty): "is too small to be a CA bundle (0 bytes)",
        str(junk): "does not load as a CA bundle (SSLError)",
        str(text): "does not load as a CA bundle (SSLError)",
        str(_crl_only(tmp_path)): "holds no certificate",
    }
    for value, problem in cases.items():
        rows = tls_trust.validate_ca_environment({variable: value})
        assert len(rows) == 1, (value, rows)
        row = rows[0]
        assert (row["variable"], row["value"], row["problem"]) == (variable, value, problem)
        assert variable in row["repair"]


def test_every_set_variable_is_reported_not_just_the_first(tmp_path):
    rows = tls_trust.validate_ca_environment({
        "JARVIS_CA_BUNDLE": str(tmp_path / "a.pem"), "CURL_CA_BUNDLE": str(tmp_path / "b.pem"),
        "SSL_CERT_DIR": str(tmp_path / "nope"),
    })
    assert [r["variable"] for r in rows] == ["JARVIS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_DIR"]


def test_ssl_cert_dir_must_name_directories(tmp_path):
    a_file = tmp_path / "file.pem"
    a_file.write_text("x", encoding="utf-8")
    assert tls_trust.validate_ca_environment({"SSL_CERT_DIR": str(tmp_path)}) == []
    rows = tls_trust.validate_ca_environment({"SSL_CERT_DIR": str(a_file)})
    assert rows[0]["problem"] == f"names {str(a_file)!r}, which is not a directory"
    missing = tmp_path / "gone"
    rows = tls_trust.validate_ca_environment({"SSL_CERT_DIR": f"{tmp_path}{os.pathsep}{missing}"})
    assert rows[0]["problem"] == f"names {str(missing)!r}, which is not a directory"
    assert rows[0]["variable"] == "SSL_CERT_DIR" and rows[0]["repair"].endswith("SSL_CERT_DIR")
    # an empty segment (a trailing separator) is not a directory to check
    assert tls_trust.validate_ca_environment({"SSL_CERT_DIR": f"{tmp_path}{os.pathsep}"}) == []


def test_certifi_itself_is_checked(tmp_path):
    assert tls_trust.validate_ca_environment({}) == [], "the installed certifi is fine"
    tiny = tmp_path / "cacert.pem"
    ca, _key, _cert = _make_ca(tmp_path)
    tiny.write_bytes(ca.read_bytes().ljust(600, b"\n"))   # a real certificate, but not a bundle
    cases = [
        (lambda: str(tmp_path / "gone.pem"), "does not exist"),
        (lambda: str(tiny), "is too small to be a CA bundle (600 bytes)"),
    ]
    for where, problem in cases:
        (row,) = tls_trust.validate_ca_environment({}, certifi_where=where)
        assert (row["variable"], row["problem"]) == ("certifi", problem)
        assert row["repair"] == "python -m pip install --force-reinstall certifi"

    def broken():
        raise ImportError("no certifi")

    (row,) = tls_trust.validate_ca_environment({}, certifi_where=broken)
    assert (row["variable"], row["value"], row["problem"]) == ("certifi", "", "is not importable (ImportError)")
    # a real bundle of exactly the minimum size passes
    padded = tmp_path / "ok.pem"
    padded.write_bytes(ca.read_bytes().ljust(tls_trust.CERTIFI_MIN_BYTES, b"\n"))
    assert padded.stat().st_size == tls_trust.CERTIFI_MIN_BYTES
    assert tls_trust.validate_ca_environment({}, certifi_where=lambda: str(padded)) == []


def test_the_process_environment_is_read_when_no_mapping_is_given(monkeypatch, tmp_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "missing.pem"))
    (row,) = tls_trust.validate_ca_environment()
    assert row["variable"] == "REQUESTS_CA_BUNDLE"
    assert tls_trust.validate_ca_environment({}) == [], "a given mapping, even empty, is the whole environment"


def test_the_repair_is_a_command_for_this_shell():
    assert tls_trust._repair("SSL_CERT_FILE", windows=False) == \
        'export SSL_CERT_FILE="$(python -m certifi)"   # or: unset SSL_CERT_FILE'
    assert tls_trust._repair("CURL_CA_BUNDLE", windows=True) == \
        "$env:CURL_CA_BUNDLE = (python -m certifi)   # or: Remove-Item Env:CURL_CA_BUNDLE"
    assert tls_trust._repair("JARVIS_CA_BUNDLE", windows=False) == \
        "export JARVIS_CA_BUNDLE=/path/to/your-root-ca.pem   # or: unset JARVIS_CA_BUNDLE"
    assert tls_trust._repair("JARVIS_CA_BUNDLE", windows=True).startswith("$env:JARVIS_CA_BUNDLE = 'C:\\")
    assert tls_trust._repair("SSL_CERT_DIR", windows=False) == "unset SSL_CERT_DIR"
    assert tls_trust._repair("SSL_CERT_DIR", windows=True) == "Remove-Item Env:SSL_CERT_DIR"
    assert tls_trust._repair("certifi", windows=True) == "python -m pip install --force-reinstall certifi"


def test_the_repair_follows_the_host_when_not_told(monkeypatch):
    monkeypatch.setattr(tls_trust.os, "name", "nt")
    windows = tls_trust._repair("SSL_CERT_DIR")
    monkeypatch.setattr(tls_trust.os, "name", "posix")
    assert (windows, tls_trust._repair("SSL_CERT_DIR")) == ("Remove-Item Env:SSL_CERT_DIR", "unset SSL_CERT_DIR")


def test_a_value_from_a_dotenv_file_names_that_file(monkeypatch, tmp_path):
    from agents.core import env_provenance

    dotenv = tmp_path / ".env"
    monkeypatch.setattr(env_provenance, "provenance",
                        lambda environ=None: {"SSL_CERT_FILE": {"layer": env_provenance.USER_ENV, "shadowed": []}})
    monkeypatch.setattr(env_provenance, "files", lambda: {env_provenance.USER_ENV: {"path": str(dotenv)}})
    (row,) = tls_trust.validate_ca_environment({"SSL_CERT_FILE": str(tmp_path / "gone.pem")})
    assert row["set_in"] == str(dotenv)
    assert f"(it is set in {dotenv}: fix or remove that line there)" in tls_trust.format_problems([row])
    # no recorded path: the layer's label
    monkeypatch.setattr(env_provenance, "files", lambda: {})
    (row,) = tls_trust.validate_ca_environment({"SSL_CERT_FILE": str(tmp_path / "gone.pem")})
    assert row["set_in"] == "data-home .env"
    # the process environment: nothing to add
    monkeypatch.setattr(env_provenance, "provenance",
                        lambda environ=None: {"SSL_CERT_FILE": {"layer": env_provenance.PROCESS, "shadowed": []}})
    (row,) = tls_trust.validate_ca_environment({"SSL_CERT_FILE": str(tmp_path / "gone.pem")})
    assert row["set_in"] == ""
    assert "it is set in" not in tls_trust.format_problems([row])

    def boom(environ=None):
        raise RuntimeError("provenance down")

    monkeypatch.setattr(env_provenance, "provenance", boom)
    (row,) = tls_trust.validate_ca_environment({"SSL_CERT_FILE": str(tmp_path / "gone.pem")})
    assert row["set_in"] == "" and row["problem"] == "does not exist", "the check stands without the hint"


def test_enforce_stops_the_start_with_the_name_the_value_the_problem_and_the_fix(tmp_path):
    missing = tmp_path / "corp-root.pem"
    with pytest.raises(SystemExit) as exc:
        tls_trust.enforce_ca_environment({"SSL_CERT_FILE": str(missing)})
    message = str(exc.value)
    assert message.splitlines()[0] == "TLS trust is misconfigured; the hub will not start until it is fixed:"
    assert f"SSL_CERT_FILE={str(missing)!r} does not exist." in message
    assert "fix: " + tls_trust._repair("SSL_CERT_FILE") in message
    assert tls_trust.enforce_ca_environment({}) is None


def test_enforce_announces_the_insecure_list_at_start(caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        tls_trust.enforce_ca_environment({tls_trust.INSECURE_TARGETS_ENV: "lab.lan, ollama"})
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "TLS verification will be DISABLED for lab.lan, ollama (JARVIS_TLS_INSECURE_TARGETS)"


def test_enforce_says_the_hardened_profile_ignores_the_list(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        tls_trust.enforce_ca_environment({tls_trust.INSECURE_TARGETS_ENV: "ollama"})
    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert "ignored in the hardened profile" in record.getMessage() and "ollama" in record.getMessage()


def test_the_hub_validates_at_start_beside_the_other_boot_guards():
    from agents import web

    life = inspect.getsource(web.lifespan)
    assert "enforce_ca_environment()" in life
    assert life.index("enforce_boot_posture()") < life.index("enforce_ca_environment()")
    # before anything dials out or opens a store
    assert life.index("enforce_ca_environment()") < life.index("ensure_user_home")


# ── the anchor ───────────────────────────────────────────────────────────────


def test_the_warning_names_the_variable_that_held_the_bad_value(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "gone.pem"))
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        assert tls_trust.tls_verify() is True
    (record,) = caplog.records
    assert record.getMessage().startswith("SSL_CERT_FILE does not name a readable file")

    junk = tmp_path / "junk.pem"
    junk.write_text("junk", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(junk))
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        assert tls_trust.tls_verify() is True
    (record,) = caplog.records
    assert record.getMessage().startswith("JARVIS_CA_BUNDLE could not be loaded")


def test_the_plugin_client_module_still_exports_the_one_anchor():
    from agents.core import http_client

    assert http_client.tls_verify is tls_trust.tls_verify
    assert http_client.CA_BUNDLE_ENV == "JARVIS_CA_BUNDLE"


def test_trust_context_is_always_a_verifying_context(monkeypatch, tmp_path):
    for value in (None, str(tmp_path / "gone.pem"), str(_make_ca(tmp_path)[0])):
        if value is None:
            monkeypatch.delenv("JARVIS_CA_BUNDLE", raising=False)
        else:
            monkeypatch.setenv("JARVIS_CA_BUNDLE", value)
        context = tls_trust.trust_context()
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
        assert len(context.get_ca_certs()) > 100, "certifi's anchors are in it"
    assert "nerva-h504-ca" in _subjects(context)


def test_the_anchor_is_certifi_plus_the_owners_root(monkeypatch, tmp_path):
    """certifi's roots are in every context this module builds — with the owner's root
    added, and alone when there is none (never the bare system store)."""
    import certifi

    fake_certifi, _k, _c = _make_ca(tmp_path, "stand-in-certifi-root")
    monkeypatch.setattr(certifi, "where", lambda: str(fake_certifi))
    owner, _k, _c = _make_ca(tmp_path, "owner-root")
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(owner))
    assert {"stand-in-certifi-root", "owner-root"} <= _subjects(tls_trust.tls_verify())
    monkeypatch.delenv("JARVIS_CA_BUNDLE")
    assert _subjects(tls_trust.trust_context()) == {"stand-in-certifi-root"}


# ── the per-target switch ────────────────────────────────────────────────────


def test_an_unlisted_target_verifies_against_the_anchor(monkeypatch, tmp_path):
    ca, _key, _cert = _make_ca(tmp_path)
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(ca))
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "someone-else, other.lan")
    context = tls_trust.verify_for("anthropic", "https://api.anthropic.com")
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED
    assert "nerva-h504-ca" in _subjects(context)


@pytest.mark.parametrize(("listed", "target", "base_url"), [
    ("ollama", "ollama", "https://gpu.lan:11434"),
    ("OLLAMA", "Ollama", None),
    ("gpu.lan", "ollama", "https://gpu.lan:11434/v1"),
    ("GPU.LAN.", "lm-studio", "https://gpu.lan./v1"),
    ("x, gpu.lan ,y", "ollama", "https://gpu.lan"),
])
def test_a_listed_target_is_off_and_announced_with_its_url(monkeypatch, caplog, listed, target, base_url):
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, listed)
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        assert tls_trust.verify_for(target, base_url) is False
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert message.startswith("TLS verification DISABLED for ")
    assert str(base_url or target.lower()) in message and tls_trust.INSECURE_TARGETS_ENV in message


@pytest.mark.parametrize(("listed", "target", "base_url"), [
    ("lan", "ollama", "https://gpu.lan"),               # a suffix is not the host
    ("gpu.lan", "ollama", "https://gpu.lan.evil.test"),  # nor is a prefix
    ("gpu.lan", "ollama", "not a url"),
    ("gpu.lan", "ollama", "https://[gpu.lan/v1"),       # urlsplit refuses it
    ("gpu.lan", "ollama", 12),
    (" , ,", "", ""),
    ("ollama", "", "https://ollama.test"),              # the id is not a host
])
def test_only_an_exact_id_or_host_is_listed(monkeypatch, caplog, listed, target, base_url):
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, listed)
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        assert isinstance(tls_trust.verify_for(target, base_url), ssl.SSLContext)
    assert caplog.records == []


def test_the_hardened_profile_refuses_the_list(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "ollama")
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        verdict = tls_trust.verify_for("ollama", "https://gpu.lan")
    assert isinstance(verdict, ssl.SSLContext) and verdict.verify_mode == ssl.CERT_REQUIRED
    (record,) = caplog.records
    assert record.levelno == logging.ERROR and "https://gpu.lan" in record.getMessage()


def test_a_bad_ca_path_never_turns_verification_off(monkeypatch, tmp_path):
    for variable in ("JARVIS_CA_BUNDLE", "SSL_CERT_FILE"):
        for value in ("/nope/missing.pem", str(tmp_path), "0", "false", "off", "none"):
            monkeypatch.setenv(variable, value)
            verdict = tls_trust.verify_for("anthropic", "https://api.anthropic.com")
            assert isinstance(verdict, ssl.SSLContext), (variable, value)
            assert verdict.verify_mode == ssl.CERT_REQUIRED and verdict.check_hostname is True
        monkeypatch.delenv(variable)


def test_insecure_targets_parses_the_list():
    env = tls_trust.INSECURE_TARGETS_ENV
    assert tls_trust.insecure_targets({}) == frozenset()
    assert tls_trust.insecure_targets({env: " A.lan. ,, b ,"}) == frozenset({"a.lan", "b"})


# ── model egress on the anchor ───────────────────────────────────────────────


def test_every_model_client_gets_the_anchor(monkeypatch, tmp_path):
    from agents.core.llm.egress import llm_async_client

    ca, _key, _cert = _make_ca(tmp_path)
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(ca))
    for kwargs in ({}, {"trust_env": False}, {"base_url": "https://gpu.lan"}):
        client = llm_async_client("anthropic", **kwargs)
        context = _pool_context(client)
        assert "nerva-h504-ca" in _subjects(context), kwargs
        assert context.verify_mode == ssl.CERT_REQUIRED


def test_a_bad_ssl_cert_file_no_longer_breaks_the_client_with_an_unnamed_error(monkeypatch, tmp_path):
    """The regression the row names: httpx read SSL_CERT_FILE itself (trust_env) and raised
    a FileNotFoundError that named no file."""
    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.egress import llm_async_client

    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "nonexistent.pem"))
    with pytest.raises(FileNotFoundError):         # what httpx alone does with it
        httpx.AsyncClient()
    client = llm_async_client("gemini", timeout=5.0)
    assert _pool_context(client).verify_mode == ssl.CERT_REQUIRED
    backend = ClaudeBackend("sk-test")
    assert _pool_context(backend.client).verify_mode == ssl.CERT_REQUIRED


def test_the_real_backends_verify_against_the_anchor(monkeypatch, tmp_path):
    """Anthropic keeps trust_env (the owner's proxy); xAI and OpenAI Responses turn it off —
    all three now carry the owner's root."""
    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.xai import XAIBackend

    ca, _key, _cert = _make_ca(tmp_path)
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(ca))
    for backend in (ClaudeBackend("sk-test"), XAIBackend("xai-test")):
        assert "nerva-h504-ca" in _subjects(_pool_context(backend.client)), type(backend).__name__


def test_a_callers_own_transport_or_verify_is_left_alone(monkeypatch):
    from agents.core.llm.egress import llm_async_client

    calls = []
    monkeypatch.setattr(tls_trust, "verify_for", lambda *a, **k: calls.append(a) or True)
    llm_async_client("xai", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    own = ssl.create_default_context()
    client = llm_async_client("anthropic", verify=own)
    assert calls == []
    assert _pool_context(client) is own
    llm_async_client("anthropic", transport=None, base_url="https://x.test")
    assert calls == [("anthropic", "https://x.test")]


def test_a_listed_backend_client_is_built_without_verification_and_announced(monkeypatch, caplog):
    from agents.core.llm.egress import llm_async_client

    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "lm-studio")
    with caplog.at_level(logging.WARNING, logger="jarvis.tls_trust"):
        client = llm_async_client("lm-studio", base_url="https://gpu.lan:1234/v1")
    context = _pool_context(client)
    assert context.verify_mode == ssl.CERT_NONE and context.check_hostname is False
    assert any("https://gpu.lan:1234/v1" in r.getMessage() for r in caplog.records)


# ── end to end: a real HTTPS server only the test's CA signed ────────────────


@pytest.fixture
def https_server(tmp_path):
    ca, ca_key, ca_cert = _make_ca(tmp_path)
    cert, key = _make_leaf(tmp_path, ca_key, ca_cert)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"data": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_address[1]}", ca
    finally:
        server.shutdown()
        server.server_close()


async def _get(backend: str, url: str) -> int:
    from agents.core.llm.egress import llm_async_client

    async with llm_async_client(backend, base_url=url, timeout=5.0) as client:
        return (await client.get("/v1/models")).status_code


def test_end_to_end_the_owners_root_reaches_a_model_call(monkeypatch, https_server):
    url, ca = https_server
    # without the owner's root, the private CA is (rightly) refused
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED|certificate verify failed"):
        asyncio.run(_get("lm-studio", url))
    # with it, the same call succeeds — JARVIS_CA_BUNDLE now applies to model egress
    monkeypatch.setenv("JARVIS_CA_BUNDLE", str(ca))
    assert asyncio.run(_get("lm-studio", url)) == 200
    # SSL_CERT_FILE, the second spelling, too
    monkeypatch.delenv("JARVIS_CA_BUNDLE")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    assert asyncio.run(_get("lm-studio", url)) == 200


def test_end_to_end_only_the_listed_target_skips_the_check(monkeypatch, https_server):
    url, _ca = https_server
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "127.0.0.1")
    assert asyncio.run(_get("lm-studio", url)) == 200
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "ollama")
    with pytest.raises(httpx.ConnectError):
        asyncio.run(_get("lm-studio", url))
    monkeypatch.setenv(tls_trust.INSECURE_TARGETS_ENV, "127.0.0.1")
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    with pytest.raises(httpx.ConnectError):
        asyncio.run(_get("lm-studio", url))


# ── docs ─────────────────────────────────────────────────────────────────────


def test_the_switch_is_documented():
    flags = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    assert "JARVIS_TLS_INSECURE_TARGETS" in flags
    assert "JARVIS_TLS_INSECURE_TARGETS" in (ROOT / ".env.example").read_text(encoding="utf-8")
