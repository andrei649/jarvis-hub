"""Remote host terminal transport: argv only, key-only, pinned host key, capped.

The remote half of the governed terminal. The policy plane above it already
exists — ``TargetRegistry.authorize`` decides per (target, agent, capability),
``terminal_contract`` screens the argv, and the Action Kernel requires a durable
approval — but until this module existed ``execution.py`` answered every remote
request with ``ssh_transport_not_implemented``. This is the wire, and nothing
more: it does not decide who may run what.

What it refuses to do, on purpose:

- **No shell string ever leaves this process.** ``run`` takes an argv and
  rebuilds it with :func:`shlex.join`, so the remote login shell reconstructs
  exactly the argv that was screened here. A caller cannot smuggle ``;`` or
  ``$(...)`` through an argument.
- **No ``~/.ssh/config``.** ``-F /dev/null`` is the first option, so a file on
  this box cannot reintroduce ``ProxyCommand``, a different ``User`` or a
  forwarding the owner never approved.
- **No unknown host keys.** ``StrictHostKeyChecking=yes`` against an explicit
  ``UserKnownHostsFile``; a host absent from that file is a refusal, never a
  prompt and never a trust-on-first-use.
- **No passwords, no agent.** ``BatchMode=yes``,
  ``NumberOfPasswordPrompts=0``, ``IdentitiesOnly=yes``, ``IdentityAgent=none``
  — the declared key or nothing. A hung password prompt is not a failure mode
  this transport can have.
- **No forwarding.** Agent, X11 and every port forward are off explicitly.
- **No arbitrary hosts.** A target name resolves through the operator-declared
  inventory or it is refused; the model never names a hostname.

Default-off. ``from_env()`` reads:

- ``JARVIS_TERMINAL_SSH_HOSTS`` — the inventory, a JSON object keyed by target
  name: ``{"pi-house": {"user": "pi", "hostname": "10.0.0.4", "port": 22,
  "identity_file": "/home/owner/.ssh/id_pi", "roots": ["/home/pi/work"]}}``.
  ``roots`` is required and has no default: an operator who has not said where
  commands may run has not declared a usable target.
- ``JARVIS_TERMINAL_SSH_KNOWN_HOSTS`` — the pinned host-key file. Required: no
  file, no transport.
- ``JARVIS_TERMINAL_SSH_CONNECT_TIMEOUT_S`` — TCP/handshake budget (default 10).

The enabling flag ``JARVIS_TERMINAL_SSH_HOST`` is checked by the runner, not
here: a transport object existing is not a permission to run.

Honest limits, so nobody reads a guarantee that is not here:

- The remote ``cwd`` is validated as an absolute path and quoted, but it is not
  jailed — the boundary on the far side is the remote account's own
  permissions. Give the target a dedicated unprivileged user.
- OpenSSH exits 255 for its own errors, and a remote command may also exit 255;
  this transport reports 255 as ``ssh_error`` and carries the remote stderr, so
  a remote command that genuinely exits 255 is reported as a transport error.
- The remote side is assumed to be a POSIX shell. A Windows target is refused
  rather than quoted wrongly.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agents.core.env_config import env_int, env_json_object, env_str

from .output_limits import read_capped_stream, render_capped
from .terminal_contract import (
    DEFAULT_TIMEOUT_S,
    MAX_ARG_CHARS,
    MAX_ARGV_ITEMS,
    MAX_TIMEOUT_S,
    argv_fingerprint,
    hardline_match,
)

DEFAULT_MAX_OUTPUT_BYTES = 16_000
_MAX_OUTPUT_CEILING = 1_000_000
DEFAULT_CONNECT_TIMEOUT_S = 10
MAX_CONNECT_TIMEOUT_S = 120

_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_USER_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,31}")
# DNS names and IPv4 literals. A leading '-' can never match, which is what
# keeps a hostname from being read by ssh as an option; IPv6 literals are out
# of scope for this version rather than quoted wrongly.
_HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?")

Spawn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class SshHost:
    """One operator-declared remote target. Every field is validated here."""

    target: str
    user: str
    hostname: str
    port: int = 22
    identity_file: str = ""
    roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        target = str(self.target or "").strip()
        user = str(self.user or "").strip()
        hostname = str(self.hostname or "").strip()
        if _TARGET_RE.fullmatch(target) is None:
            raise ValueError("target name must be a safe 1-64 character token")
        if _USER_RE.fullmatch(user) is None:
            raise ValueError("user must be a safe 1-32 character login name")
        if _HOST_RE.fullmatch(hostname) is None:
            raise ValueError("hostname must be a DNS name or IPv4 literal")
        if isinstance(self.port, bool) or not isinstance(self.port, int) \
                or not (1 <= self.port <= 65535):
            raise ValueError("port must be an integer between 1 and 65535")
        identity = str(self.identity_file or "").strip()
        if identity:
            path = Path(identity).expanduser()
            if not path.is_absolute():
                raise ValueError("identity_file must be an absolute path")
            identity = str(path)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "user", user)
        object.__setattr__(self, "hostname", hostname)
        roots = self.roots
        if isinstance(roots, (str, bytes)) or not isinstance(roots, Sequence) or not roots:
            raise ValueError("roots must be a non-empty sequence of absolute remote paths")
        cleaned: list[str] = []
        for root in roots:
            text = str(root or "").strip()
            if not text.startswith("/") or "\x00" in text or "\n" in text or "\r" in text:
                raise ValueError("each root must be an absolute remote path")
            cleaned.append(PurePosixPath(text).as_posix())
        object.__setattr__(self, "identity_file", identity)
        object.__setattr__(self, "roots", tuple(dict.fromkeys(cleaned)))


def parse_hosts(inventory: Mapping[str, Any]) -> dict[str, SshHost]:
    """Build the inventory from the decoded ``JARVIS_TERMINAL_SSH_HOSTS`` object.

    A malformed entry raises rather than being skipped: an operator who mistyped
    a hostname should see it at startup, not discover that a target silently
    does not exist at the moment an approved command tries to run.
    """
    if not isinstance(inventory, Mapping):
        raise ValueError("ssh inventory must be a JSON object keyed by target name")
    hosts: dict[str, SshHost] = {}
    for name, row in inventory.items():
        if not isinstance(row, Mapping):
            raise ValueError(f"ssh target {name!r} must map to an object")
        unknown = set(row) - {"user", "hostname", "port", "identity_file", "roots"}
        if unknown:
            raise ValueError(f"ssh target {name!r} has unknown keys: {sorted(unknown)}")
        roots = row.get("roots", ())
        host = SshHost(
            target=str(name),
            user=str(row.get("user", "")),
            hostname=str(row.get("hostname", "")),
            port=row.get("port", 22),
            identity_file=str(row.get("identity_file", "")),
            roots=tuple(roots) if not isinstance(roots, (str, bytes)) else (roots,),
        )
        hosts[host.target] = host
    return hosts


def default_connect_timeout() -> int:
    return min(
        env_int("JARVIS_TERMINAL_SSH_CONNECT_TIMEOUT_S", DEFAULT_CONNECT_TIMEOUT_S, minimum=1),
        MAX_CONNECT_TIMEOUT_S,
    )


def default_timeout() -> int:
    return min(env_int("JARVIS_TERMINAL_TIMEOUT_S", DEFAULT_TIMEOUT_S, minimum=1), MAX_TIMEOUT_S)


class SshTransport:
    """Run one argv on a declared remote host over OpenSSH, key-only and pinned."""

    backend = "ssh"

    def __init__(
        self,
        hosts: Mapping[str, SshHost],
        *,
        known_hosts: str | Path,
        default_timeout: int = DEFAULT_TIMEOUT_S,
        max_timeout: int = MAX_TIMEOUT_S,
        max_output: int = DEFAULT_MAX_OUTPUT_BYTES,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT_S,
        ssh_path: str = "ssh",
        spawn: Spawn | None = None,
    ) -> None:
        if not isinstance(hosts, Mapping) or not hosts:
            raise ValueError("hosts must be a non-empty mapping of target -> SshHost")
        for name, host in hosts.items():
            if not isinstance(host, SshHost):
                raise ValueError("hosts values must be SshHost instances")
            if name != host.target:
                raise ValueError("hosts keys must match their target name")
        pinned = str(known_hosts or "").strip()
        if not pinned:
            raise ValueError("known_hosts is required: an unpinned host key is not a transport")
        known_path = Path(pinned).expanduser()
        if not known_path.is_absolute():
            raise ValueError("known_hosts must be an absolute path")
        for label, value in (("default_timeout", default_timeout), ("max_timeout", max_timeout)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if max_timeout > MAX_TIMEOUT_S:
            raise ValueError(f"max_timeout must not exceed {MAX_TIMEOUT_S}")
        if default_timeout > max_timeout:
            raise ValueError("default_timeout must not exceed max_timeout")
        if isinstance(connect_timeout, bool) or not isinstance(connect_timeout, int) or not (
            1 <= connect_timeout <= MAX_CONNECT_TIMEOUT_S
        ):
            raise ValueError(f"connect_timeout must be between 1 and {MAX_CONNECT_TIMEOUT_S}")
        if isinstance(max_output, bool) or not isinstance(max_output, int) or not (
            8 <= max_output <= _MAX_OUTPUT_CEILING
        ):
            raise ValueError("max_output must be between 8 and 1,000,000 bytes")
        if not str(ssh_path or "").strip():
            raise ValueError("ssh_path must not be blank")
        self._hosts = dict(hosts)
        self._known_hosts = known_path
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.max_output = max_output
        self.connect_timeout = connect_timeout
        self.ssh_path = str(ssh_path).strip()
        self._spawn = spawn or asyncio.create_subprocess_exec

    @classmethod
    def from_env(cls, **kwargs: Any) -> SshTransport:
        """Build from the ``JARVIS_TERMINAL_SSH_*`` inventory; raise when unusable."""
        hosts = kwargs.pop("hosts", None)
        if hosts is None:
            hosts = parse_hosts(env_json_object("JARVIS_TERMINAL_SSH_HOSTS"))
        kwargs.setdefault("known_hosts", env_str("JARVIS_TERMINAL_SSH_KNOWN_HOSTS"))
        kwargs.setdefault("default_timeout", default_timeout())
        kwargs.setdefault("connect_timeout", default_connect_timeout())
        return cls(hosts, **kwargs)

    @property
    def targets(self) -> tuple[str, ...]:
        return tuple(sorted(self._hosts))

    def host_for(self, target: str) -> SshHost | None:
        return self._hosts.get(str(target or "").strip())

    @staticmethod
    def validate_argv(argv: Any) -> str | None:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
            return "invalid_argv"
        items = list(argv)
        if not items or len(items) > MAX_ARGV_ITEMS:
            return "invalid_argv"
        for item in items:
            if not isinstance(item, str) or item == "" or len(item) > MAX_ARG_CHARS:
                return "invalid_argv"
            if "\x00" in item:
                return "invalid_argv"
        return None

    def resolve_cwd(self, target: str, cwd: Any = None) -> str | None:
        """Return the remote cwd when it sits inside a declared root, else ``None``.

        Purely textual: this box cannot stat a path on the far side, so the
        check is containment under the roots the operator declared, and the
        real boundary remains the remote account's own permissions.
        """
        host = self.host_for(target)
        if host is None:
            return None
        if cwd is None:
            return host.roots[0]
        text = str(cwd)
        if not text or len(text) > MAX_ARG_CHARS:
            return None
        if "\x00" in text or "\n" in text or "\r" in text:
            return None
        if not text.startswith("/"):
            return None
        candidate = PurePosixPath(text)
        if any(part == ".." for part in candidate.parts):
            return None
        resolved = candidate.as_posix()
        for root in host.roots:
            base = PurePosixPath(root)
            if candidate == base or base in candidate.parents:
                return resolved
        return None

    def bound_timeout(self, timeout: int | None) -> int | None:
        if timeout is None:
            return self.default_timeout
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            return None
        if timeout > self.max_timeout:
            return None
        return timeout

    def remote_command(self, argv: Sequence[str], cwd: str | None = None) -> str:
        """Rebuild the argv as a quoted string the remote shell reconstructs exactly."""
        joined = shlex.join(str(item) for item in argv)
        if cwd:
            return f"cd -- {shlex.quote(str(cwd))} && exec {joined}"
        return f"exec {joined}"

    def ssh_argv(self, host: SshHost, remote: str) -> list[str]:
        """The hardened OpenSSH invocation. Order matters: ``-F`` comes first."""
        argv = [
            self.ssh_path,
            "-F", "/dev/null",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self._known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "NumberOfPasswordPrompts=0",
            "-o", "PubkeyAuthentication=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none",
            "-o", "ForwardAgent=no",
            "-o", "ForwardX11=no",
            "-o", "ForwardX11Trusted=no",
            "-o", "ClearAllForwardings=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "PermitLocalCommand=no",
            "-o", "RequestTTY=no",
            "-o", "ControlMaster=no",
            "-o", "ControlPath=none",
            "-o", "ProxyCommand=none",
            "-o", f"ConnectTimeout={self.connect_timeout}",
            "-o", f"Port={host.port}",
            "-o", f"User={host.user}",
        ]
        if host.identity_file:
            argv += ["-o", f"IdentityFile={host.identity_file}"]
        argv += [host.hostname, remote]
        return argv

    async def run(
        self,
        argv: Sequence[str],
        *,
        target: str,
        cwd: str | Path | None = None,
        timeout: int | None = None,
        max_output: int | None = None,
    ) -> dict[str, Any]:
        """Execute ``argv`` on ``target``; every refusal is a named reason, never an exception."""
        host = self.host_for(target)
        if host is None:
            return {"ok": False, "reason": "ssh_target_not_declared"}
        invalid = self.validate_argv(argv)
        if invalid is not None:
            return {"ok": False, "reason": invalid}
        argv_list = [str(item) for item in argv]
        hardline = hardline_match(argv_list)
        if hardline is not None:
            return {"ok": False, "reason": f"hardline_denied:{hardline}"}
        workdir = self.resolve_cwd(host.target, cwd)
        if workdir is None:
            return {"ok": False, "reason": "cwd_outside_roots"}
        bounded = self.bound_timeout(timeout)
        if bounded is None:
            return {"ok": False, "reason": "invalid_timeout"}
        cap = self.max_output if max_output is None else max_output
        if isinstance(cap, bool) or not isinstance(cap, int) or not (8 <= cap <= self.max_output):
            return {"ok": False, "reason": "invalid_max_output"}
        if not self._known_hosts.is_file():
            return {"ok": False, "reason": "known_hosts_missing"}
        if host.identity_file and not Path(host.identity_file).is_file():
            return {"ok": False, "reason": "identity_file_missing"}

        from agents.core.environments import prepare_python_child_env

        env = prepare_python_child_env({})
        fingerprint = argv_fingerprint(argv_list)
        base = {
            "target": host.target,
            "host": host.hostname,
            "argv_sha256": fingerprint,
        }
        remote = self.remote_command(argv_list, workdir)
        start = time.monotonic()
        try:
            proc = await self._spawn(
                *self.ssh_argv(host, remote),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError:
            return {"ok": False, "reason": "ssh_client_not_found", **base}
        except PermissionError:
            return {"ok": False, "reason": "ssh_client_not_permitted", **base}
        except OSError:
            return {"ok": False, "reason": "spawn_failed", **base}

        try:
            (out_head, out_tail, out_total), (err_head, err_tail, err_total) = await asyncio.wait_for(
                asyncio.gather(
                    read_capped_stream(proc.stdout, max_content_bytes=cap),
                    read_capped_stream(proc.stderr, max_content_bytes=cap),
                ),
                timeout=bounded,
            )
            await asyncio.wait_for(proc.wait(), timeout=bounded)
        except TimeoutError:
            await self._kill(proc)
            return {
                "ok": False,
                "reason": "timeout",
                "exit_code": -1,
                "duration": round(time.monotonic() - start, 3),
                "timeout": bounded,
                **base,
            }
        stdout = render_capped(out_head, out_tail, out_total, max_content_bytes=cap, label="STDOUT")
        stderr = render_capped(err_head, err_tail, err_total, max_content_bytes=cap, label="STDERR")
        exit_code = proc.returncode if isinstance(proc.returncode, int) else -1
        result = {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout.text,
            "stderr": stderr.text,
            "truncated": bool(stdout.truncated or stderr.truncated),
            "duration": round(time.monotonic() - start, 3),
            **base,
        }
        result["cwd"] = workdir
        if exit_code == 255:
            # OpenSSH's own failure code. A remote command that exits 255 is
            # reported this way too; the stderr above says which it was.
            result["reason"] = "ssh_error"
        return result

    @staticmethod
    async def _kill(proc: Any) -> None:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            return
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(proc.wait(), timeout=5)


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_S",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "MAX_CONNECT_TIMEOUT_S",
    "SshHost",
    "SshTransport",
    "default_connect_timeout",
    "default_timeout",
    "parse_hosts",
]
