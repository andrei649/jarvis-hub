"""Own one pinned Hermes worker generation and its loopback transport."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import socket
import subprocess  # nosec B404 - fixed worker argv and verified managed interpreter
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from pathlib import Path

from .distribution import load_pin, runtime_environment, validate_python, verify_source

WORKER_SCRIPT = Path(__file__).resolve().with_name("worker.py")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        return None


class RuntimeProcess:
    START_TIMEOUT = 35.0
    STOP_TIMEOUT = 7.0

    def __init__(self, source: Path, home: Path, python: Path):
        self.source = Path(source).absolute()
        self.home = Path(home).absolute()
        self.python = Path(python).absolute()
        self._process: subprocess.Popen | None = None
        self._generation: str | None = None
        self._token: str | None = None
        self._url: str | None = None
        self._lock = asyncio.Lock()
        self._log = None

    def status(self) -> dict:
        process = self._process
        ready = bool(process and process.poll() is None and self._url)
        return {
            "ready": ready,
            "url": None,  # Public status does not reveal the private worker endpoint.
            "generation": self._generation if ready else None,
            "pid": process.pid if ready else None,
        }

    @staticmethod
    def _check_bridge(bridge_url: str, bridge_token: str) -> None:
        parsed = urllib.parse.urlsplit(bridge_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Hermes bridge must use HTTP loopback")
        if not bridge_token:
            raise ValueError("Hermes bridge token is required")

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def _private_descriptor(self) -> dict:
        return {
            "ready": True, "url": self._url, "token": self._token,
            "generation": self._generation, "pid": self._process.pid,
        }

    @staticmethod
    def _readiness(url: str, token: str, generation: str, commit: str) -> bool:
        request = urllib.request.Request(
            f"{url}/__jarvis__/ready",
            headers={"X-Jarvis-Runtime-Token": token},
        )
        # Never forward the private token to an ambient proxy or redirected host.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=0.6) as response:  # nosec B310 - generated loopback URL, no proxy or redirects
                if response.status != 200:
                    return False
                data = json.loads(response.read(4096))
        except (OSError, ValueError, urllib.error.URLError):
            return False
        return data.get("ready") is True and data.get("generation") == generation and data.get("source_sha") == commit

    async def start(self, *, bridge_url: str, bridge_token: str) -> dict:
        self._check_bridge(bridge_url, bridge_token)
        async with self._lock:
            if self._process and self._process.poll() is None:
                if self._url is None:
                    raise RuntimeError("Hermes worker is still starting")
                return self._private_descriptor()
            await self._stop_locked()
            verify_source(self.source)
            validate_python(self.python, self.source, self.home)
            if WORKER_SCRIPT.is_symlink() or not WORKER_SCRIPT.is_file():
                raise RuntimeError("Hermes worker script is unavailable")
            if self.home.is_symlink() or not self.home.is_dir():
                raise ValueError("Hermes private home is unavailable")
            self.home.chmod(0o700)
            generation = secrets.token_hex(16)
            token = secrets.token_urlsafe(32)
            port = self._free_port()
            url = f"http://127.0.0.1:{port}"
            env = runtime_environment(self.home)
            env.update({
                "JARVIS_HERMES_BRIDGE_URL": bridge_url,
                "JARVIS_HERMES_BRIDGE_TOKEN": bridge_token,
                "JARVIS_HERMES_GENERATION": generation,
                "HERMES_DASHBOARD_SESSION_TOKEN": token,
            })
            logs = self.home / "logs"
            logs.mkdir(mode=0o700, exist_ok=True)
            log_path = logs / f"worker-{generation}.log"
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self._log = os.fdopen(descriptor, "wb")
            argv = [str(self.python), str(WORKER_SCRIPT), "--source", str(self.source),
                    "--home", str(self.home), "--host", "127.0.0.1", "--port", str(port)]
            try:
                self._process = subprocess.Popen(  # nosec B603 - fixed argv, verified worker and Python, no shell
                    argv, cwd=self.source, env=env, stdin=subprocess.DEVNULL,
                    stdout=self._log, stderr=subprocess.STDOUT, close_fds=True,
                    start_new_session=os.name == "posix",
                )
                self._generation = generation
                self._token = token
                deadline = time.monotonic() + self.START_TIMEOUT
                commit = load_pin()["commit"]
                while time.monotonic() < deadline:
                    if self._process.poll() is not None:
                        raise RuntimeError(f"Hermes worker exited during startup ({self._process.returncode})")
                    if await asyncio.to_thread(self._readiness, url, token, generation, commit):
                        self._url = url
                        return self._private_descriptor()
                    await asyncio.sleep(0.1)
                raise TimeoutError("Hermes worker readiness timed out")
            except BaseException:
                await self._stop_locked()
                raise

    async def _stop_locked(self) -> None:
        process = self._process
        if process:
            if os.name == "posix":
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            elif process.poll() is None:
                process.terminate()
            if process.poll() is None:
                try:
                    await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=self.STOP_TIMEOUT)
                except TimeoutError:
                    if os.name == "posix":
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    await asyncio.to_thread(process.wait)
        if self._log:
            self._log.close()
            self._log = None
        self._process = None
        self._generation = None
        self._url = None
        self._token = None

    async def stop(self) -> dict:
        async with self._lock:
            await self._stop_locked()
            return self.status()
