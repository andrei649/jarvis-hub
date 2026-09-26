"""H504 — TLS trust that fails loudly when it is misconfigured, and never quietly off.

One place decides what every outbound client verifies against:

- **The anchor** (:func:`tls_verify`): the default store plus the owner's extra root
  (``JARVIS_CA_BUNDLE``, or ``SSL_CERT_FILE`` as the second spelling). It only ever
  adds; a path that is missing or will not load keeps the default store and says which
  variable held it.
- **Boot validation** (:func:`validate_ca_environment`, :func:`enforce_ca_environment`,
  run by the web lifespan): every CA variable that is set — ``JARVIS_CA_BUNDLE``,
  ``SSL_CERT_FILE``, ``REQUESTS_CA_BUNDLE``, ``CURL_CA_BUNDLE`` (files) and
  ``SSL_CERT_DIR`` (directories) — and certifi itself must exist, be the right kind,
  load into an SSLContext and hold at least one certificate. A broken one stops the start
  with the variable's name and a command that repairs it, instead of an unnamed
  ``FileNotFoundError`` on the first model call.
- **Per-target verification** (:func:`verify_for`): what a model backend's client gets.
  Always an SSLContext built from the anchor, so a client that keeps ``trust_env`` (for
  the owner's proxy) never has httpx read ``SSL_CERT_FILE`` on its own. The only way to
  turn verification off is to name the target — its provider id or its host — in
  ``JARVIS_TLS_INSECURE_TARGETS``; every client built that way logs a WARNING naming the
  URL, and the hardened profile refuses the list outright. A bad CA path never means off.
"""
from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger("jarvis.tls_trust")

CA_BUNDLE_ENV = "JARVIS_CA_BUNDLE"
_CA_BUNDLE_FALLBACK_ENV = "SSL_CERT_FILE"
INSECURE_TARGETS_ENV = "JARVIS_TLS_INSECURE_TARGETS"
#: Variables naming one CA file, in the order they are checked.
CA_FILE_VARIABLES = ("JARVIS_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
CA_DIR_VARIABLE = "SSL_CERT_DIR"
CERTIFI_MIN_BYTES = 1024


def _env(name: str) -> str:
    from agents.core.env_config import env_str

    return (env_str(name) or "").strip()


# ── the anchor ───────────────────────────────────────────────────────────────


def _source() -> tuple[str, str]:
    """(variable, value) of the owner's extra anchor, or ("", "")."""
    for name in (CA_BUNDLE_ENV, _CA_BUNDLE_FALLBACK_ENV):
        value = _env(name)
        if value:
            return name, value
    return "", ""


def tls_verify():
    """What httpx verifies against: the default trust store, plus the owner's anchor.

    Only ever ADDS. There is no value of either variable that turns verification off,
    and none that removes an anchor the box already trusted: an inspecting proxy or a
    private CA needs its root trusted, not the check skipped, and a knob that could
    skip it would quietly make every SSRF and egress guard decorative. A path that does
    not exist, or a bundle that will not load, degrades to the default store with a
    warning naming the variable that held it — the stricter side of the mistake, and a
    visible one.
    """
    name, extra = _source()
    if not extra:
        return True
    if not Path(extra).is_file():
        logger.warning("%s does not name a readable file; keeping the default trust store", name)
        return True
    try:
        context = ssl.create_default_context()
        try:
            import certifi

            context.load_verify_locations(cafile=certifi.where())
        except Exception:   # pragma: no cover - certifi ships with httpx
            logger.debug("certifi anchors unavailable; system store only")
        context.load_verify_locations(cafile=extra)
        return context
    except Exception as exc:
        logger.warning("%s could not be loaded (type=%s); keeping the default trust store",
                       name, type(exc).__name__)
        return True


def trust_context() -> ssl.SSLContext:
    """The anchor as an SSLContext, always: :func:`tls_verify`'s, else certifi's own."""
    verdict = tls_verify()
    if isinstance(verdict, ssl.SSLContext):
        return verdict
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


# ── boot validation ──────────────────────────────────────────────────────────


def _repair(variable: str, *, windows: bool | None = None) -> str:
    """A command that repairs *variable*, for the shell this host runs."""
    win = (os.name == "nt") if windows is None else windows
    if variable == "certifi":
        return "python -m pip install --force-reinstall certifi"
    if variable == CA_BUNDLE_ENV:
        if win:
            return f"$env:{variable} = 'C:\\path\\to\\your-root-ca.pem'   # or: Remove-Item Env:{variable}"
        return f"export {variable}=/path/to/your-root-ca.pem   # or: unset {variable}"
    if variable == CA_DIR_VARIABLE:
        return f"Remove-Item Env:{variable}" if win else f"unset {variable}"
    if win:
        return f"$env:{variable} = (python -m certifi)   # or: Remove-Item Env:{variable}"
    return f'export {variable}="$(python -m certifi)"   # or: unset {variable}'


def _set_in(variable: str) -> str:
    """Where the hub's .env load put *variable* (a file path), or "" for the process."""
    try:
        from agents.core import env_provenance

        layer = env_provenance.provenance({variable: ""}).get(variable, {}).get("layer")
        if layer in (env_provenance.REPO_ENV, env_provenance.USER_ENV):
            info = env_provenance.files().get(layer) or {}
            return str(info.get("path") or env_provenance.LABELS[layer])
    except Exception:                   # the hint is a courtesy; the check stands without it
        logger.debug("CA variable provenance unavailable", exc_info=True)
    return ""


def _count_certs(load: Callable[[ssl.SSLContext], None]) -> int:
    """How many certificates *load* put in a fresh store — any certificate, not only a
    CA-flagged one: a pinned self-signed server certificate is a valid anchor too."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    load(context)
    return int(context.cert_store_stats().get("x509", 0))


def _check_file(value: str, *, min_bytes: int = 1) -> str | None:
    path = Path(value)
    if not path.exists():
        return "does not exist"
    if not path.is_file():
        return "is not a file"
    try:
        size = path.stat().st_size
        if size < min_bytes:
            return f"is too small to be a CA bundle ({size} bytes)"
        count = _count_certs(lambda ctx: ctx.load_verify_locations(cafile=str(path)))
    except (OSError, ValueError) as exc:   # unreadable, vanished, or not PEM/DER (ssl.SSLError is an OSError)
        return f"does not load as a CA bundle ({type(exc).__name__})"
    if count < 1:
        return "holds no certificate"
    return None


def _check_dirs(value: str) -> str | None:
    for part in value.split(os.pathsep):         # an empty entry is ".", a directory
        if not Path(part).is_dir():
            return f"names {part!r}, which is not a directory"
    return None


def validate_ca_environment(environ: Mapping[str, str] | None = None, *,
                            certifi_where: Callable[[], str] | None = None) -> list[dict]:
    """Every problem with the CA variables that are set, and with certifi: each
    ``{variable, value, problem, repair, set_in}`` (``set_in``: the .env file that set
    it, or "" for the process environment). An unset or blank variable is fine."""
    def read(name: str) -> str:
        return (environ.get(name) or "").strip() if environ is not None else _env(name)

    problems = []
    for variable in CA_FILE_VARIABLES:
        value = read(variable)
        if value:
            problem = _check_file(value)
            if problem:
                problems.append({"variable": variable, "value": value, "problem": problem,
                                 "repair": _repair(variable), "set_in": _set_in(variable)})
    value = read(CA_DIR_VARIABLE)
    if value:
        problem = _check_dirs(value)
        if problem:
            problems.append({"variable": CA_DIR_VARIABLE, "value": value, "problem": problem,
                             "repair": _repair(CA_DIR_VARIABLE), "set_in": _set_in(CA_DIR_VARIABLE)})
    try:
        if certifi_where is None:
            import certifi

            certifi_where = certifi.where
        where = certifi_where()
        problem = _check_file(where, min_bytes=CERTIFI_MIN_BYTES)
    except Exception as exc:
        where, problem = "", f"is not importable ({type(exc).__name__})"
    if problem:
        problems.append({"variable": "certifi", "value": where, "problem": problem, "repair": _repair("certifi"),
                         "set_in": ""})
    return problems


def format_problems(problems: list[dict]) -> str:
    lines = ["TLS trust is misconfigured; the hub will not start until it is fixed:"]
    for p in problems:
        lines.append(f"  {p['variable']}={p['value']!r} {p['problem']}.")
        lines.append(f"    fix: {p['repair']}")
        if p.get("set_in"):
            lines.append(f"    (it is set in {p['set_in']}: fix or remove that line there)")
    return "\n".join(lines)


def enforce_ca_environment(environ: Mapping[str, str] | None = None) -> None:
    """Stop the start when a CA variable that is set cannot be trusted as written."""
    problems = validate_ca_environment(environ)
    if problems:
        raise SystemExit(format_problems(problems))
    listed = insecure_targets(environ)
    if listed:
        from agents.core.security import hardened

        if hardened.enabled():
            logger.error("%s is ignored in the hardened profile: TLS verification stays on for %s",
                         INSECURE_TARGETS_ENV, ", ".join(sorted(listed)))
        else:
            logger.warning("TLS verification will be DISABLED for %s (%s)",
                           ", ".join(sorted(listed)), INSECURE_TARGETS_ENV)


# ── per-target verification ──────────────────────────────────────────────────


def insecure_targets(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """The provider ids and hosts ``JARVIS_TLS_INSECURE_TARGETS`` names, lower-cased."""
    raw = (environ.get(INSECURE_TARGETS_ENV) or "") if environ is not None else _env(INSECURE_TARGETS_ENV)
    return frozenset(part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip())


def _host(base_url: object) -> str:
    if not isinstance(base_url, str) or not base_url:
        return ""
    try:
        return (urlsplit(base_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def verify_for(target: str, base_url: object = None):
    """What a client for *target* (a provider id) at *base_url* verifies against: the
    anchor's SSLContext, or ``False`` only when the owner named this target or its host
    in ``JARVIS_TLS_INSECURE_TARGETS`` (never in the hardened profile). Each insecure
    client is announced with a WARNING naming the URL."""
    listed = insecure_targets()
    host = _host(base_url)
    named = str(target or "").strip().lower()
    if listed and (named in listed or (host and host in listed)):
        from agents.core.security import hardened

        if hardened.enabled():
            logger.error("TLS verification stays ON for %s (%s): %s is ignored in the hardened profile",
                         base_url or named, named, INSECURE_TARGETS_ENV)
        else:
            logger.warning("TLS verification DISABLED for %s (%s): %s names it",
                           base_url or named, named, INSECURE_TARGETS_ENV)
            return False
    return trust_context()


__all__ = [
    "CA_BUNDLE_ENV", "CA_DIR_VARIABLE", "CA_FILE_VARIABLES", "INSECURE_TARGETS_ENV", "enforce_ca_environment",
    "format_problems", "insecure_targets", "tls_verify", "trust_context", "validate_ca_environment", "verify_for",
]
