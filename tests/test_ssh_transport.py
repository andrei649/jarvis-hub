"""Governed remote terminal transport: pinned host key, key-only, argv verbatim.

Pins the safety order of the ``ssh`` backend of ``GovernedTargetRunner``:
hardline → target policy → durable approval → ``JARVIS_TERMINAL_SSH_HOST`` flag
→ argv-only parse → ``terminal.exec`` contract against the operator-declared
remote roots → Action Kernel GRANT → ``SshTransport``. The hardening of the
OpenSSH invocation itself is pinned option by option, because every one of them
is load-bearing: drop ``-F /dev/null`` and a file on this box reintroduces
``ProxyCommand``; drop ``StrictHostKeyChecking=yes`` and a lookalike host is
trusted on first use. All hermetic: no socket is opened and no ssh binary runs.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from agents.core.environments import TargetAuditChain, TargetRegistry, TerminalTarget
from agents.core.environments.execution import SSH_HOST_FLAG, GovernedTargetRunner
from agents.core.environments.ssh_transport import SshHost, SshTransport, parse_hosts
from agents.core.environments.targets import default_targets
from agents.core.kernel import Decision, Verdict

# ── fakes ───────────────────────────────────────────────────────────────────


class _FakeStream:
    def __init__(self, data: bytes = b"", *, block: asyncio.Event | None = None):
        self._data = data
        self._block = block

    async def read(self, n: int) -> bytes:
        if self._block is not None:
            await self._block.wait()
            return b""
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk


class _FakeProc:
    def __init__(self, *, stdout=b"", stderr=b"", returncode=0, block=None):
        self.stdout = _FakeStream(stdout, block=block)
        self.stderr = _FakeStream(stderr, block=block)
        self.returncode = None if block is not None else returncode
        self._final = returncode
        self._block = block
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9
        if self._block is not None:
            self._block.set()

    async def wait(self):
        if self._block is not None:
            await self._block.wait()
        if self.returncode is None:
            self.returncode = self._final
        return self.returncode


class _FakeSpawn:
    def __init__(self, **proc_kwargs):
        self.calls: list[dict] = []
        self.proc_kwargs = proc_kwargs
        self.last_proc = None

    async def __call__(self, *argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        self.last_proc = _FakeProc(**self.proc_kwargs)
        return self.last_proc


class _FakeSandbox:
    def active_backend(self):
        return "docker"

    async def execute_shell(self, command):  # pragma: no cover - never reached here
        raise AssertionError("ssh targets must never reach the docker sandbox")


class _RecordingTransport:
    """Records what the runner hands the transport; never spawns."""

    max_timeout = 600

    def __init__(self, host: SshHost):
        self._host = host
        self.calls: list[dict] = []

    def host_for(self, target):
        return self._host if target == self._host.target else None

    def bound_timeout(self, timeout):
        return 60 if timeout is None else timeout

    def resolve_cwd(self, target, cwd=None):
        return SshTransport.resolve_cwd(self, target, cwd)  # type: ignore[arg-type]

    async def run(self, argv, *, target, cwd=None, timeout=None, max_output=None):
        self.calls.append({"argv": list(argv), "target": target, "cwd": cwd, "timeout": timeout})
        return {"ok": True, "exit_code": 0, "stdout": "ok", "stderr": ""}


@pytest.fixture
def known_hosts(tmp_path):
    path = tmp_path / "known_hosts"
    path.write_text("10.0.0.4 ssh-ed25519 AAAA\n", encoding="utf-8")
    return path


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "id_pi"
    path.write_text("PRIVATE", encoding="utf-8")
    return path


def _host(**over) -> SshHost:
    base = {
        "target": "pi-house", "user": "pi", "hostname": "10.0.0.4",
        "port": 22, "roots": ("/home/pi/work",),
    }
    base.update(over)
    return SshHost(**base)


def _transport(known_hosts, *, host=None, spawn=None, **kw) -> SshTransport:
    host = host or _host()
    return SshTransport({host.target: host}, known_hosts=str(known_hosts),
                        spawn=spawn or _FakeSpawn(), **kw)


# ── the declared inventory is the only way in ───────────────────────────────


@pytest.mark.parametrize("field,value", [
    ("hostname", "-oProxyCommand=curl evil"),   # option injection through the host slot
    ("hostname", "-oProxyCommand"),             # refused only by the leading-'-' rule
    ("hostname", "10.0.0.4 extra"),
    ("hostname", ""),
    ("user", "-oIdentityFile=/tmp/x"),
    ("user", "pi pi"),
    ("user", ""),
    ("target", "../escape"),
    ("port", 0),
    ("port", 70000),
    ("port", True),
    ("identity_file", "relative/key"),
])
def test_a_host_row_refuses_every_shape_that_could_become_an_ssh_option(field, value):
    with pytest.raises(ValueError):
        _host(**{field: value})


@pytest.mark.parametrize("roots", [(), ("relative/dir",), ("",), ("/ok", "/bad\nnewline")])
def test_roots_are_required_and_absolute(roots):
    with pytest.raises(ValueError):
        _host(roots=roots)


def test_parse_hosts_builds_the_inventory_and_refuses_unknown_keys():
    hosts = parse_hosts({"pi-house": {
        "user": "pi", "hostname": "10.0.0.4", "port": 2222,
        "identity_file": "/keys/id_pi", "roots": ["/home/pi/work", "/srv"],
    }})
    assert hosts["pi-house"] == SshHost(
        target="pi-house", user="pi", hostname="10.0.0.4", port=2222,
        identity_file="/keys/id_pi", roots=("/home/pi/work", "/srv"),
    )
    with pytest.raises(ValueError):
        parse_hosts({"x": {"user": "a", "hostname": "h", "roots": ["/r"], "shell": "/bin/sh"}})
    with pytest.raises(ValueError):
        parse_hosts({"x": "user@host"})
    with pytest.raises(ValueError):
        parse_hosts(["pi-house=pi@10.0.0.4"])


def test_a_transport_without_a_pinned_known_hosts_file_cannot_be_built():
    with pytest.raises(ValueError):
        SshTransport({"pi-house": _host()}, known_hosts="")
    with pytest.raises(ValueError):
        SshTransport({"pi-house": _host()}, known_hosts="relative/known_hosts")
    with pytest.raises(ValueError):
        SshTransport({}, known_hosts="/etc/known_hosts")
    with pytest.raises(ValueError):
        SshTransport({"other": _host()}, known_hosts="/etc/known_hosts")


# ── the OpenSSH invocation, option by option ────────────────────────────────


def test_the_ssh_argv_ignores_local_config_first_and_pins_the_host_key(known_hosts):
    argv = _transport(known_hosts).ssh_argv(_host(identity_file="/keys/id_pi"), "exec true")
    # -F /dev/null must come before anything else, or ~/.ssh/config wins.
    assert argv[1:3] == ["-F", "/dev/null"]
    options = {argv[i + 1] for i, item in enumerate(argv) if item == "-o"}
    for required in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={known_hosts}",
        "GlobalKnownHostsFile=/dev/null",
        "NumberOfPasswordPrompts=0",
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "ForwardAgent=no",
        "ForwardX11=no",
        "ClearAllForwardings=yes",
        "PermitLocalCommand=no",
        "RequestTTY=no",
        "ControlPath=none",
        "ProxyCommand=none",
        "IdentityFile=/keys/id_pi",
        "User=pi",
        "Port=22",
    ):
        assert required in options, required


def test_host_key_checking_is_never_relaxed_and_the_host_is_not_an_option(known_hosts):
    argv = _transport(known_hosts).ssh_argv(_host(), "exec true")
    joined = " ".join(argv)
    assert "StrictHostKeyChecking=no" not in joined
    assert "StrictHostKeyChecking=accept-new" not in joined
    # hostname second-to-last, remote command last, and the hostname can never
    # start with '-' because SshHost refuses it.
    assert argv[-2] == "10.0.0.4"
    assert argv[-1] == "exec true"
    assert not argv[-2].startswith("-")


# ── argv survives the remote login shell unchanged ──────────────────────────


@pytest.mark.parametrize("hostile", [
    "a; rm -rf /",
    "$(curl evil)",
    "`id`",
    "a && b",
    "x\nnewline",
    "* glob",
    "'quote",
])
def test_shell_metacharacters_in_an_argument_stay_one_inert_argument(known_hosts, hostile):
    import shlex

    remote = _transport(known_hosts).remote_command(["echo", hostile], "/home/pi/work")
    assert remote.startswith("cd -- /home/pi/work && exec echo ")
    # The whole point: the remote shell reconstructs the argv that was screened
    # here, so the metacharacters are data in argv[2] and never syntax.
    assert shlex.split(remote) == ["cd", "--", "/home/pi/work", "&&", "exec", "echo", hostile]


def test_the_remote_command_execs_the_argv_and_quotes_the_directory(known_hosts):
    t = _transport(known_hosts)
    assert t.remote_command(["ls", "-la"]) == "exec ls -la"
    assert t.remote_command(["ls"], "/home/pi/my work") == "cd -- '/home/pi/my work' && exec ls"
    assert t.remote_command(["ls"], "/home/pi/work") == "cd -- /home/pi/work && exec ls"


# ── the remote cwd is contained by the roots the operator declared ──────────


def test_resolve_cwd_defaults_to_the_first_root_and_contains_the_rest(known_hosts):
    t = _transport(known_hosts, host=_host(roots=("/home/pi/work", "/srv/data")))
    assert t.resolve_cwd("pi-house") == "/home/pi/work"
    assert t.resolve_cwd("pi-house", "/home/pi/work/sub") == "/home/pi/work/sub"
    assert t.resolve_cwd("pi-house", "/srv/data") == "/srv/data"
    assert t.resolve_cwd("pi-house", "/etc") is None
    assert t.resolve_cwd("pi-house", "/home/pi/work/../../etc") is None
    assert t.resolve_cwd("pi-house", "relative") is None
    assert t.resolve_cwd("pi-house", "/home/pi/work\nrm") is None
    assert t.resolve_cwd("unknown", "/home/pi/work") is None


def test_a_sibling_directory_sharing_a_prefix_is_not_inside_the_root(known_hosts):
    t = _transport(known_hosts)
    assert t.resolve_cwd("pi-house", "/home/pi/workshop") is None


# ── every refusal happens before a process exists ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,reason", [
    ({"target": "unknown"}, "ssh_target_not_declared"),
    ({"target": "pi-house", "cwd": "/etc"}, "cwd_outside_roots"),
    ({"target": "pi-house", "timeout": 0}, "invalid_timeout"),
    ({"target": "pi-house", "timeout": 10_000}, "invalid_timeout"),
    ({"target": "pi-house", "max_output": 1}, "invalid_max_output"),
])
async def test_named_refusals_never_spawn_ssh(known_hosts, kwargs, reason):
    spawn = _FakeSpawn()
    result = await _transport(known_hosts, spawn=spawn).run(["true"], **kwargs)
    assert result == {"ok": False, "reason": reason} or result["reason"] == reason
    assert spawn.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("argv", [[], "true", ["" ], [None], ["a\x00b"], ["x"] * 4096])
async def test_a_malformed_argv_is_refused_before_spawn(known_hosts, argv):
    spawn = _FakeSpawn()
    result = await _transport(known_hosts, spawn=spawn).run(argv, target="pi-house")
    assert result["reason"] == "invalid_argv"
    assert spawn.calls == []


@pytest.mark.asyncio
async def test_the_hardline_is_rechecked_here_so_a_direct_caller_cannot_skip_it(known_hosts):
    spawn = _FakeSpawn()
    result = await _transport(known_hosts, spawn=spawn).run(
        ["rm", "-rf", "/"], target="pi-house")
    assert result["reason"].startswith("hardline_denied:")
    assert spawn.calls == []


@pytest.mark.asyncio
async def test_a_missing_known_hosts_file_or_key_refuses_at_call_time(tmp_path):
    spawn = _FakeSpawn()
    t = SshTransport({"pi-house": _host()}, known_hosts=str(tmp_path / "absent"), spawn=spawn)
    assert (await t.run(["true"], target="pi-house"))["reason"] == "known_hosts_missing"
    assert spawn.calls == []

    known = tmp_path / "known_hosts"
    known.write_text("x\n", encoding="utf-8")
    t2 = SshTransport({"pi-house": _host(identity_file="/keys/absent")},
                      known_hosts=str(known), spawn=spawn)
    assert (await t2.run(["true"], target="pi-house"))["reason"] == "identity_file_missing"
    assert spawn.calls == []


# ── what a real run reports ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_successful_run_reports_the_target_the_host_and_the_argv_digest(known_hosts):
    spawn = _FakeSpawn(stdout=b"hello\n", stderr=b"", returncode=0)
    result = await _transport(known_hosts, spawn=spawn).run(["echo", "hello"], target="pi-house")
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["target"] == "pi-house"
    assert result["host"] == "10.0.0.4"
    assert result["cwd"] == "/home/pi/work"
    assert len(result["argv_sha256"]) == 64
    assert spawn.calls[0]["argv"][-1] == "cd -- /home/pi/work && exec echo hello"
    assert spawn.calls[0]["stdin"] is asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_openssh_own_error_code_is_reported_as_a_transport_error(known_hosts):
    spawn = _FakeSpawn(stdout=b"", stderr=b"Host key verification failed.\n", returncode=255)
    result = await _transport(known_hosts, spawn=spawn).run(["true"], target="pi-house")
    assert result["ok"] is False
    assert result["exit_code"] == 255
    assert result["reason"] == "ssh_error"
    assert "Host key verification failed" in result["stderr"]


@pytest.mark.asyncio
async def test_a_remote_failure_is_passed_through_not_relabelled(known_hosts):
    spawn = _FakeSpawn(stdout=b"", stderr=b"no such file\n", returncode=2)
    result = await _transport(known_hosts, spawn=spawn).run(["cat", "x"], target="pi-house")
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert "reason" not in result


@pytest.mark.asyncio
async def test_a_hung_connection_is_killed_and_named(known_hosts):
    spawn = _FakeSpawn(block=asyncio.Event())
    t = _transport(known_hosts, spawn=spawn, default_timeout=1)
    result = await t.run(["sleep", "600"], target="pi-house")
    assert result["reason"] == "timeout"
    assert spawn.last_proc.killed is True


@pytest.mark.asyncio
async def test_remote_output_is_capped_in_host_memory(known_hosts):
    spawn = _FakeSpawn(stdout=b"x" * 100_000, stderr=b"e" * 50, returncode=0)
    t = _transport(known_hosts, spawn=spawn, max_output=1_000)
    result = await t.run(["cat", "big"], target="pi-house")
    assert result["truncated"] is True
    assert len(result["stdout"]) < 10_000


# ── the runner: same gate order as the local host ───────────────────────────


def _registry(tmp_path):
    return TargetRegistry(
        (TerminalTarget(
            name="pi-house",
            backend="ssh",
            enabled=True,
            allowed_agents=frozenset({"jarvis"}),
            capabilities=frozenset({"terminal.exec"}),
            approval_required=frozenset({"terminal.exec"}),
        ),),
        audit=TargetAuditChain(path=tmp_path / "audit.jsonl"),
    )


def _granting_authorizer(action, capability=None):
    return Decision(verdict=Verdict.GRANT, reason="test")


@pytest.mark.asyncio
async def test_with_the_flag_off_the_refusal_is_byte_identical_to_before(tmp_path, monkeypatch):
    monkeypatch.delenv(SSH_HOST_FLAG, raising=False)
    runner = GovernedTargetRunner(
        _registry(tmp_path), _FakeSandbox(), approval_check=lambda _id: True)
    result = await runner.run(
        target="pi-house", agent="jarvis", command="echo hi", approved_task_id=1)
    assert result["reason"] == "ssh_transport_not_implemented"


@pytest.mark.asyncio
async def test_a_command_needing_a_shell_is_refused_before_the_transport(tmp_path, monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    transport = _RecordingTransport(_host())
    runner = GovernedTargetRunner(
        _registry(tmp_path), _FakeSandbox(), ssh_transport=transport,
        authorizer=_granting_authorizer, approval_check=lambda _id: True)
    result = await runner.run(
        target="pi-house", agent="jarvis", command="echo a | tee b", approved_task_id=1)
    assert result["ok"] is False
    assert transport.calls == []


@pytest.mark.asyncio
async def test_without_a_kernel_grant_nothing_reaches_the_wire(tmp_path, monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    transport = _RecordingTransport(_host())
    runner = GovernedTargetRunner(
        _registry(tmp_path), _FakeSandbox(), ssh_transport=transport,
        approval_check=lambda _id: True)
    result = await runner.run(
        target="pi-house", agent="jarvis", command="echo hi", approved_task_id=1)
    assert result["ok"] is False
    assert result["reason"] in {"kernel_unavailable", "action_kernel_disabled"}
    assert transport.calls == []


@pytest.mark.asyncio
async def test_an_approval_required_target_without_a_durable_task_never_runs(tmp_path, monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    transport = _RecordingTransport(_host())
    runner = GovernedTargetRunner(
        _registry(tmp_path), _FakeSandbox(), ssh_transport=transport,
        authorizer=_granting_authorizer, approval_check=lambda _id: True)
    result = await runner.run(target="pi-house", agent="jarvis", command="echo hi")
    assert result["ok"] is False
    assert transport.calls == []


@pytest.mark.asyncio
async def test_the_contract_caps_an_argv_parse_argv_would_accept(tmp_path, monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    transport = _RecordingTransport(_host())
    runner = GovernedTargetRunner(
        _registry(tmp_path), _FakeSandbox(), ssh_transport=transport,
        authorizer=_granting_authorizer, approval_check=lambda _id: True)
    # 200 tokens: a valid shell-free command line, and far past MAX_ARGV_ITEMS.
    command = "echo " + " ".join(str(i) for i in range(200))
    result = await runner.run(
        target="pi-house", agent="jarvis", command=command, approved_task_id=1)
    assert result["ok"] is False
    assert result["reason"] == "contract_denied:invalid_argv"
    assert transport.calls == []


def test_the_transport_adds_no_python_ssh_library():
    """Half of the old honesty claim survives this change and should stay sayable.

    ``NERVA_VISION.md`` and ``test_vision_execution_claim_honesty`` pin two
    facts that used to travel together: that ``ssh`` refuses, and that there is
    no paramiko/asyncssh in the repo. The first is now false — this module is
    the transport — and correcting that sentence is an owner edit, because
    ``NERVA_VISION.md`` is a protected path. The second is still true and this
    pins it: the wire is the OpenSSH client as a subprocess, so no Python SSH
    library, no new hash-pinned dependency, and no in-process crypto.
    """
    import agents.core.environments.ssh_transport as mod

    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    for library in ("paramiko", "asyncssh", "fabric", "libssh"):
        assert library not in source, library
    assert SshTransport({"pi-house": _host()}, known_hosts="/x/known_hosts").ssh_path == "ssh"


# ── the policy inventory ────────────────────────────────────────────────────


def test_with_the_flag_unset_the_inventory_is_byte_identical(monkeypatch):
    monkeypatch.delenv(SSH_HOST_FLAG, raising=False)
    monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOSTS", '{"box":{"user":"a","hostname":"h",'
                                                    '"roots":["/r"]}}')
    names = [t.name for t in default_targets()]
    assert names == ["local-host", "bonobo-windows", "pi-house", "isolated-sandbox"]
    assert all(t.enabled is False for t in default_targets() if t.backend == "ssh")


def test_a_declared_machine_becomes_a_conservative_policy_row(monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOSTS",
                       '{"bonobo":{"user":"a","hostname":"10.0.0.9","roots":["/home/a"]}}')
    rows = {t.name: t for t in default_targets()}
    assert "bonobo" in rows
    row = rows["bonobo"]
    assert row.backend == "ssh"
    assert row.enabled is True
    assert "terminal.exec" in row.approval_required
    assert "file.write" not in row.capabilities


def test_a_malformed_inventory_yields_no_rows_rather_than_a_permissive_guess(monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOSTS", '{"bad":{"user":"a","hostname":"h"}}')
    names = [t.name for t in default_targets()]
    assert names == ["local-host", "bonobo-windows", "pi-house", "isolated-sandbox"]


def test_a_declared_name_cannot_replace_a_reviewed_builtin_row(monkeypatch):
    monkeypatch.setenv(SSH_HOST_FLAG, "1")
    monkeypatch.setenv("JARVIS_TERMINAL_SSH_HOSTS",
                       '{"isolated-sandbox":{"user":"a","hostname":"h","roots":["/r"]}}')
    rows = [t for t in default_targets() if t.name == "isolated-sandbox"]
    assert len(rows) == 1
    assert rows[0].backend == "docker"
