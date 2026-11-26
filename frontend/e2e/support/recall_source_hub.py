"""Prepare and serve the synthetic HTTPS hub for playwright.recall-source.config.ts.

``--prepare`` creates one disposable home, vault note, owner secret and TLS cert,
then prints only its directory. ``--serve`` reads that fixture and starts the real
hub on its assigned 127.0.0.2 port. The only permitted outbound connection is
the existing local Ollama at 127.0.0.1:11434; no model is called by this helper.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[3]
PREFIX = "nerva-recall-browser-"
LOOPBACK = {"127.0.0.1", "127.0.0.2", "localhost", "::1"}


def prepare() -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    model = os.environ.get("NERVA_MEMORY_MODEL", "").strip()
    if not model or any(char.isspace() for char in model) or ":cloud" in model.lower():
        raise SystemExit("NERVA_MEMORY_MODEL must name an installed local Ollama model")
    run = Path(tempfile.mkdtemp(prefix=PREFIX)).resolve()
    for name in ("profile", "keys", "user", "tmp", "vault"):
        (run / name).mkdir()
    with socket.socket() as probe:
        probe.bind(("127.0.0.2", 0))
        port = probe.getsockname()[1]
    if port <= 1024 or port == 8080:
        raise SystemExit("unsafe recall-source port")

    marker = secrets.token_hex(6)
    token = "fixture-" + secrets.token_hex(24)
    (run / "vault" / "Calibration.md").write_text(
        f"# Calibration\n\nThe glass heron calibration code is {marker}.\n", encoding="utf-8")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Nerva loopback test")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.2"))]), critical=False)
            .sign(key, hashes.SHA256()))
    (run / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (run / "key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    data = {
        "port": port, "url": f"https://127.0.0.2:{port}", "model": model,
        "marker": marker, "token": token,
    }
    use_fixture_environment(run, data)
    from agents.core.llm.physical_local import ollama_local_selector

    data["wire_model"] = ollama_local_selector(model)
    (run / "fixture.json").write_text(json.dumps(data), encoding="utf-8")
    print(run, flush=True)


def fixture() -> tuple[Path, dict]:
    raw = os.environ.get("NERVA_RECALL_RUN_DIR", "")
    run = Path(raw).resolve() if raw else Path("/")
    if not raw or not run.is_dir() or not run.name.startswith(PREFIX) or run.parent != Path(tempfile.gettempdir()).resolve():
        raise SystemExit("NERVA_RECALL_RUN_DIR must be a prepared disposable fixture")
    data = json.loads((run / "fixture.json").read_text(encoding="utf-8"))
    port = data.get("port")
    if not isinstance(port, int) or port <= 1024 or port == 8080 or data.get("url") != f"https://127.0.0.2:{port}":
        raise SystemExit("invalid recall-source fixture")
    return run, data


def scrubbed_environment(run: Path, data: dict) -> dict[str, str]:
    hidden = ("JARVIS_", "NERVA_", "E2E_", "OLLAMA_", "ANTHROPIC_", "CLAUDE_", "GEMINI_",
              "GOOGLE_API", "GOOGLE_GENAI", "OPENAI_", "OPENROUTER_", "DEEPINFRA_",
              "DEEPSEEK_", "XAI_", "MISTRAL_", "GROQ_", "TOGETHER_", "FIREWORKS_",
              "COHERE_", "PERPLEXITY_", "AZURE_OPENAI")
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(hidden)
           and not key.upper().endswith(("_API_KEY", "_API_TOKEN", "_AUTH_TOKEN"))
           and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
    env.update({
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
        "NO_PROXY": "127.0.0.1,127.0.0.2,localhost,::1",
        "JARVIS_HOME": str(run / "profile"), "JARVIS_KEY_DIR": str(run / "keys"),
        "JARVIS_USER_HOME": str(run / "user"), "HOME": str(run / "user"),
        "USERPROFILE": str(run / "user"), "TEMP": str(run / "tmp"), "TMP": str(run / "tmp"),
        "JARVIS_OS_VAULT_PATH": str(run / "vault"), "JARVIS_PORT": str(data["port"]),
        "JARVIS_HOST": "127.0.0.1", "JARVIS_LOG_LEVEL": "warning",
        "JARVIS_ADMIN_TOKEN": data["token"],
        "JARVIS_STRICT_LOCAL": "1", "JARVIS_OLLAMA_URL": "http://127.0.0.1:11434",
        "JARVIS_LM_STUDIO_URL": "http://127.0.0.1:9", "JARVIS_OS_REPOSITORY_DOCS": "0",
        "JARVIS_LLM_WARMUP": "0", "JARVIS_DRIVE_AI_SYNC": "0", "MEMORY_EMBED_TURNS": "0",
        "NERVA_MEMORY_MODEL": data["model"], "NERVA_TEST_CERT": str(run / "cert.pem"),
        "NERVA_TEST_KEY": str(run / "key.pem"),
    })
    return env


def install_network_guard(port: int) -> None:
    def guard(event: str, args: tuple) -> None:
        if event == "socket.getaddrinfo" and args[0] not in LOOPBACK | {None}:
            raise PermissionError("synthetic hub permits loopback only")
        if event == "socket.bind":
            address = args[1]
            if isinstance(address, tuple) and not (
                (address[0] in LOOPBACK and address[1] == 0)
                or (address[0] == "127.0.0.2" and address[1] == port)
            ):
                raise PermissionError("synthetic hub may bind only its test listener")
        if event == "socket.connect":
            address = args[1]
            # Windows asyncio may create a private pipe with socketpair's fallback.
            if (isinstance(address, tuple) and sys._getframe(1).f_code is socket._fallback_socketpair.__code__
                    and address[0] in {"127.0.0.1", "::1"} and address[1] != 8080):
                return
            if isinstance(address, tuple) and (address[0], address[1]) not in {
                ("127.0.0.2", port), ("127.0.0.1", 11434),
            }:
                raise PermissionError("synthetic hub may contact only itself and local Ollama")
    sys.addaudithook(guard)


def require_physical_ollama_model(model: str) -> None:
    """Read Ollama's metadata, refusing local names that forward to a cloud host."""
    request = Request("http://127.0.0.1:11434/api/show",
                      data=json.dumps({"model": model}).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=8) as response:
            raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("model metadata too large")
        shown = json.loads(raw)
        if (not isinstance(shown, dict) or shown.get("remote_model") or shown.get("remote_host")
                or not isinstance(shown.get("model_info"), dict) or not shown["model_info"]):
            raise ValueError("model is remote or has no physical model metadata")
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit("local Ollama model could not be verified") from exc


def use_fixture_environment(run: Path, data: dict) -> None:
    clean = scrubbed_environment(run, data)
    os.environ.clear()
    os.environ.update(clean)
    sys.path.insert(0, str(REPO))


def serve() -> None:
    run, data = fixture()
    use_fixture_environment(run, data)
    install_network_guard(data["port"])
    os.chdir(REPO)
    from agents.core.llm.physical_local import ollama_local_selector

    wire_model = ollama_local_selector(data["model"])
    if data["wire_model"] != wire_model:
        raise SystemExit("recall-source fixture model selector changed")
    # Check the installed tag, then use the exact physical-local selector for generation.
    require_physical_ollama_model(data["model"].removesuffix(":local"))

    from contextlib import asynccontextmanager

    from agents.core import agent, paths, settings_db

    agent.soul_path_for = lambda ident: REPO / "agents" / str(ident) / "SOUL.md"
    agent.identity_path = lambda: REPO / "agents" / "_identity" / "IDENTITY.md"
    if not agent.soul_path_for("jarvis").is_file() or not agent.identity_path().is_file():
        raise SystemExit("public agent templates unavailable")
    if paths.data_root().resolve() != run / "profile" or settings_db.DB_PATH.parent.resolve() != run / "profile":
        raise SystemExit("hub data path escaped fixture")
    settings_db.init_db(force=True)
    settings_db.put_category("llm", {"backend_type": "ollama", "default_model": wire_model,
                                    "cloud_fallback": "never", "tool_loop_enabled": False})
    settings_db.put_category("cognition", {"enabled": True, "memory_enabled": True})
    settings_db.put_category("memory", {"core_enabled": True, "recall_enabled": False})

    import uvicorn

    from agents import web
    from agents.core.llm.base import OllamaBackend

    original_lifespan = web.app.router.lifespan_context

    @asynccontextmanager
    async def isolated_lifespan(app):
        async with original_lifespan(app) as state:
            router = web.orch.llm_router
            router.set_active_model(wire_model)
            if (not router._local_available or router._cloud_available or router._claude_available
                    or router._backend_name != "ollama" or router.ollama_url != "http://127.0.0.1:11434"):
                raise RuntimeError("fixture requires the local Ollama route only")
            select = router.select_backend

            def local_backend(agent_id, prompt):
                backend, chosen, route = select(agent_id, prompt)
                if not isinstance(backend, OllamaBackend) or chosen != wire_model or not route.startswith("local"):
                    raise RuntimeError("nonlocal or unexpected model route")
                return backend, chosen, route

            router.select_backend = local_backend
            yield state

    web.app.router.lifespan_context = isolated_lifespan

    def announce_ready() -> None:
        context = ssl.create_default_context(cafile=str(run / "cert.pem"))
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
        for _ in range(120):
            try:
                with opener.open(data["url"] + "/readyz", timeout=1) as response:
                    if response.status == 200:
                        print("READY recall-source loopback", flush=True)
                        return
            except OSError:
                pass
            time.sleep(1)

    threading.Thread(target=announce_ready, daemon=True).start()
    uvicorn.run(web.app, host="127.0.0.2", port=data["port"],
                ssl_certfile=str(run / "cert.pem"), ssl_keyfile=str(run / "key.pem"),
                log_level="warning")


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    elif sys.argv[1:] == ["--serve"]:
        serve()
    else:
        raise SystemExit("usage: recall_source_hub.py --prepare|--serve")
