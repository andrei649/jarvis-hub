"""H566 / H571 — a third-party author's extension in, through one card per extension.

What the owner can do: hand Nerva an author's folder (or an extension an installed
Python distribution declares), see it verified in the sandbox, read an install card with
every risk and hash on it, accept it, and end with a signed package that still needs
consent and activation; pin a set of extensions into a pack and reproduce it elsewhere.

What an attacker cannot do: install anything without a person accepting that exact card
(a machine decider, an edited card, a moved payload, a replayed card and a card for an
unknown proposal are all refused); register a surface other than the declared one; ship
code the generator's static rules refuse; turn an owner-submitted package into a generic
acquired tool; install a pack whose bytes do not match its pins, or one that carries
consent or config.

The sandbox is simulated in one deliberate way: the runner below executes the real
commands the verifier builds — the author's unittest run and the system-owned contract
script, mutation included — with this interpreter against the real sealed files. What is
faked is the container, not the checks. Real Docker isolation is not proven here.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.cli.nerva import Context, main
from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
from agents.core.acquisition.package_store import AcquiredPackageStore
from agents.core.acquisition.promotion import (
    PromotionBroker,
    PromotionJournal,
    PromotionStore,
    _version_bound,
)
from agents.core.acquisition.quarantine import QuarantineStore
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile, SandboxExecution
from agents.core.acquisition.store import CapabilityRequestStore
from agents.core.autonomy import irreversible
from agents.core.extensions import submission
from agents.core.extensions.capabilities import CAPABILITY_REGISTRY
from agents.core.extensions.packs import PackError, export_pack, load_pack, parse_pack
from agents.core.extensions.submission import SubmissionError, read_directory, read_installed
from agents.core.routers import plugins
from agents.core.skills.marketplace import SkillMarketplace
from agents.core.tool_rpc import ToolRPCServer

PINNED_IMAGE = "python:3.12-slim@sha256:" + "a" * 64

DESCRIPTOR = {
    "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.2.0",
    "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
    "requires": {"extensions": {}, "python": {}},
}
SOURCE = '''
def register():
    return {"tools": ["boats.summarize"], "commands": [], "events": []}


def call(tool, payload):
    return {"summary": str(payload.get("text", ""))[:80]}
'''
TEST = '''
import unittest

from main import call, register


class BoatsTest(unittest.TestCase):
    def test_summarize(self):
        self.assertEqual(call("boats.summarize", {"text": "hi"}), {"summary": "hi"})
        self.assertEqual(register()["tools"], ["boats.summarize"])
'''


def author(tmp_path, name="boats", *, descriptor=None, source=SOURCE, test=TEST):
    folder = tmp_path / name
    folder.mkdir(parents=True)
    (folder / "extension.json").write_text(json.dumps(descriptor or DESCRIPTOR))
    (folder / "main.py").write_text(source)
    (folder / "test_extension.py").write_text(test)
    return folder


# ── a real pipeline with a local "container" ─────────────────────────────────

class LocalRunner:
    """Runs the verifier's real commands here: the mounts become host paths."""

    def __init__(self, scratch: Path):
        self.scratch = scratch
        self.runs = []

    async def run(self, command, *, container_name):
        image = command.index(PINNED_IMAGE)
        mounts = {}
        for item in command[:image]:
            if item.startswith("type=bind,"):
                fields = dict(part.split("=", 1) for part in item.split(",") if "=" in part)
                mounts[fields["target"]] = fields["source"]
        inner = list(command[image + 1:])
        source = mounts["/workspace/source"]
        if inner[:2] == ["python", "-I"] and inner[2].startswith("/workspace/contract/"):
            script = Path(mounts["/workspace/contract"]) / Path(inner[2]).name
            local = self.scratch / f"{container_name}.py"
            local.write_text(script.read_text().replace("/workspace/source", source))
            inner[2] = str(local)
        inner = [sys.executable if part == "python" else part.replace("/workspace/source", source)
                 for part in inner]
        started = time.monotonic()
        done = subprocess.run(inner, cwd=source, capture_output=True, text=True, timeout=60)
        self.runs.append((container_name, done.returncode))
        return SandboxExecution(done.returncode, done.stdout, done.stderr, False, time.monotonic() - started)


class Acquisition:
    def __init__(self, broker, root):
        self.broker = broker
        self.root = root

    def is_enabled(self):
        return True

    def ensure_promotion(self):
        return self.broker

    def verification_root(self):
        return self.root / "verification-runs"


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)
    tool_rpc = ToolRPCServer()
    gates = []
    broker = PromotionBroker(
        enabled=lambda: True,
        quarantine=QuarantineStore(root=tmp_path / "quarantine"),
        requests=CapabilityRequestStore(root=tmp_path / "requests"),
        proposals=PromotionStore(root=tmp_path / "proposals"),
        packages=packages,
        journal=PromotionJournal(root=tmp_path / "journal"),
        tool_rpc=tool_rpc,
        runtime=SimpleNamespace(),
        marketplace=SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "market.db")),
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
        kernel_gate=lambda payload: gates.append(dict(payload)) or "queue",
    )
    tasks = []

    def govern_enqueue(**kwargs):
        tasks.append(kwargs)
        return len(tasks)

    acquisition = Acquisition(broker, tmp_path)
    orch = SimpleNamespace(autonomy=SimpleNamespace(govern_enqueue=govern_enqueue),
                           acquisition=acquisition, intent_log=None)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return SimpleNamespace(orch=orch, acquisition=acquisition, broker=broker, packages=packages,
                           tool_rpc=tool_rpc, tasks=tasks, gates=gates, runner=LocalRunner(scratch))


def _task(hub, index=0, **overrides):
    queued = hub.tasks[index]
    values = {"id": index + 1, "kind": queued["kind"], "payload": dict(queued["payload"]),
              "decided_by": "owner", "decision": "accept"}
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_an_authors_folder_is_verified_carded_and_installed_only_on_a_persons_accept(tmp_path, hub):
    authored = read_directory(author(tmp_path))
    result = await submission.submit(hub.acquisition, authored, orch=hub.orch, runner=hub.runner)
    # The author's tests, the declared-surface contract and its mutation really ran.
    assert [code for _name, code in hub.runner.runs][:2] == [0, 0] and hub.runner.runs[2][1] != 0
    assert hub.gates and hub.gates[0]["kind"] == "skill.install"
    [queued] = hub.tasks
    assert queued["kind"] == "extensions.install" and queued["risk_tier"] == 3 and queued["autonomy_level"] == "ask"
    payload = queued["payload"]
    assert payload["source_sha256"] == authored.source_sha256 and payload["version"] == "1.2.0"
    assert CAPABILITY_REGISTRY["tools"].risk in payload["preview"]["capabilities"][0]
    assert result["pending"] == 1 and hub.packages.get("boats") is None   # nothing installed yet

    # A machine decider, an edit and a moved payload never install.
    assert (await irreversible.execute(_task(hub, decided_by="policy"), orch=hub.orch))["reason"] == "human_decision_required"
    assert (await irreversible.execute(_task(hub, decision="edit"), orch=hub.orch))["reason"] == "edit_not_supported"
    moved = _task(hub)
    moved.payload["package_hash"] = "f" * 64
    assert (await irreversible.execute(moved, orch=hub.orch))["reason"] == "payload_changed"
    assert (await irreversible.execute(_task(hub, id=99), orch=hub.orch))["reason"] == "not_requested"
    assert hub.packages.get("boats") is None

    installed = await irreversible.execute(_task(hub), orch=hub.orch)
    assert installed["status"] == "installed" and installed["version"] == "1.2.0"
    record = hub.packages.get("boats")
    assert record.version == "1.2.0" and record.manifest["model_route"] == "owner-submitted"
    assert hub.packages.verify("boats")
    # Installing grants nothing: no generic acquired tool, consent and activation still ahead.
    assert not hub.tool_rpc.allows("boats")
    assert (await irreversible.execute(_task(hub), orch=hub.orch))["reason"] == "already_applied"


@pytest.mark.asyncio
async def test_code_that_registers_another_surface_fails_the_sandbox_contract(tmp_path, hub):
    sneaky = SOURCE.replace('["boats.summarize"]', '["boats.summarize", "boats.exfiltrate"]')
    test = TEST.replace('["boats.summarize"])', '["boats.summarize", "boats.exfiltrate"])')
    authored = read_directory(author(tmp_path, source=sneaky, test=test))
    with pytest.raises(SubmissionError) as refused:
        await submission.submit(hub.acquisition, authored, orch=hub.orch, runner=hub.runner)
    assert refused.value.reason == "verification_failed"
    assert refused.value.detail == "system-owned contract test failed"
    assert hub.tasks == []


@pytest.mark.parametrize(("source", "test", "reason"), [
    ("import os\n" + SOURCE, TEST, "source_rejected"),
    (SOURCE.replace("def call(", "def other("), TEST.replace("call(", "register(").replace(
        "from main import register, register", "from main import register"), "source_rejected"),
    (SOURCE, "import unittest\nfrom main import register\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        register()\n",
     "test_rejected"),
    (SOURCE + "\nKEY = 'sk-ant-api03-" + "A" * 90 + "'\n", TEST, "source_contains_secret"),
    (SOURCE.replace('return {"tools": ["boats.summarize"], "commands": [], "events": []}',
                    "raise NotImplementedError()"), TEST, "source_rejected"),
])
def test_the_generators_static_rules_refuse_before_any_container(tmp_path, source, test, reason):
    authored = read_directory(author(tmp_path, source=source, test=test))
    with pytest.raises(SubmissionError) as refused:
        submission.check_source(authored)
    assert refused.value.reason == reason


def test_the_author_folder_is_read_without_following_links_and_bounded(tmp_path):
    folder = author(tmp_path)
    (folder / "main.py").unlink()
    (folder / "main.py").symlink_to(tmp_path / "elsewhere.py")
    (tmp_path / "elsewhere.py").write_text(SOURCE)
    with pytest.raises(SubmissionError, match="file_unreadable"):
        read_directory(folder)
    big = author(tmp_path, "big", source="x = 1\n" * 20000)
    with pytest.raises(SubmissionError, match="file_too_large"):
        read_directory(big)
    with pytest.raises(SubmissionError):
        read_directory(tmp_path / "missing")


def test_the_install_version_is_bound_to_the_package_hash(tmp_path):
    authored = read_directory(author(tmp_path))
    package, _contract = submission.build_package(authored)
    assert _version_bound(package, "1.2.0") and not _version_bound(package, "9.9.9")
    assert not _version_bound(package, "0.1.0")
    generated = SimpleNamespace(model_route="strict-local", name="x", goal_hash="0")
    assert _version_bound(generated, "0.1.0") and not _version_bound(generated, "1.2.0")


def test_the_install_card_kind_is_an_irreversible_kind():
    assert "extensions.install" in irreversible.kinds()


# ── the route ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_install_route_is_admin_only_and_queues_a_card(tmp_path, hub, monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "u")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "a")
    monkeypatch.setattr(web, "orch", hub.orch)
    monkeypatch.setattr(plugins, "_extension_sandbox_runner", lambda: hub.runner)
    app = FastAPI()
    app.include_router(plugins.router)
    body = {"manifest": DESCRIPTOR, "source": SOURCE, "test": TEST, "provenance": {"kind": "directory"}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 1)),
                                 base_url="http://test") as client:
        assert (await client.post("/api/plugins/extensions/install", json=body,
                                  headers={"X-User-Token": "u"})).status_code in (401, 403)
        headers = {"X-User-Token": "u", "X-Admin-Token": "a"}
        bad = await client.post("/api/plugins/extensions/install", json={**body, "manifest": {}}, headers=headers)
        assert bad.status_code == 422 and bad.json()["reason"] == "invalid_manifest_fields"
        hostile = await client.post("/api/plugins/extensions/install",
                                    json={**body, "provenance": {"kind": "url", "distribution": "x"}}, headers=headers)
        assert hostile.status_code == 422 and hostile.json()["reason"] == "invalid_provenance"
        ok = await client.post("/api/plugins/extensions/install", json=body, headers=headers)
    assert ok.status_code == 200 and ok.json()["ok"] is True and ok.json()["pending"] == 1
    assert hub.packages.get("boats") is None


# ── the CLI and installed distributions ──────────────────────────────────────

def _cli(args, replies=None):
    posted = []

    def post(route, body):
        posted.append((route, body))
        return (replies or {}).get(body["manifest"]["id"], {"ok": True, "pending": len(posted),
                                                            "extension": body["manifest"]["id"],
                                                            "version": body["manifest"]["version"]})

    out, err = io.StringIO(), io.StringIO()
    context = Context(environ={}, out=out, err=err, client_factory=lambda _: SimpleNamespace(post=post))
    return main(["extensions", *args], context=context), out.getvalue(), err.getvalue(), posted


def test_cli_install_sends_the_validated_files_and_names_the_card(tmp_path):
    code, out, _err, posted = _cli(["install", str(author(tmp_path))])
    assert code == 0 and "install card #1" in out and "nerva approvals accept 1" in out
    [(route, body)] = posted
    assert route == "/api/plugins/extensions/install"
    assert body["source"] == SOURCE and body["test"] == TEST and body["manifest"] == DESCRIPTOR
    assert _cli(["install"])[0] == 1
    assert _cli(["install", str(tmp_path / "boats"), "--installed", "boats"])[0] == 1


def _site(tmp_path):
    site = tmp_path / "site"
    package = site / "nerva_boats"
    info = site / "nerva_boats-1.2.0.dist-info"
    package.mkdir(parents=True)
    info.mkdir()
    sentinel = tmp_path / "imported"
    (package / "__init__.py").write_text(f"open({str(sentinel)!r}, 'w').write('x')\n")
    (package / "extension.json").write_text(json.dumps(DESCRIPTOR))
    (package / "main.py").write_text(SOURCE)
    (package / "test_extension.py").write_text(TEST)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: nerva-boats\nVersion: 1.2.0\n")
    (info / "entry_points.txt").write_text("[nerva.extensions]\nboats = nerva_boats:extension\n")
    (info / "RECORD").write_text("\n".join(f"nerva_boats/{name},," for name in
                                           ("__init__.py", "extension.json", "main.py", "test_extension.py")) + "\n")
    return list(metadata.distributions(path=[str(site)])), sentinel, info


def test_an_installed_distribution_is_submitted_from_its_files_and_never_imported(tmp_path):
    dists, sentinel, info = _site(tmp_path)
    authored = read_installed("boats", distributions=dists)
    assert authored.code == SOURCE and authored.provenance == {"kind": "distribution", "distribution": "nerva-boats",
                                                               "version": "1.2.0"}
    assert not sentinel.exists()
    (info / "RECORD").write_text("nerva_boats/extension.json,,\nnerva_boats/main.py,,\n")
    with pytest.raises(SubmissionError, match="file_not_recorded"):
        read_installed("boats", distributions=list(metadata.distributions(path=[str(tmp_path / "site")])))
    with pytest.raises(SubmissionError, match="extension_not_installed"):
        read_installed("tides", distributions=dists)


# ── packs ────────────────────────────────────────────────────────────────────

TIDES = {**DESCRIPTOR, "id": "tides", "version": "2.0.0", "tools": ["forecast"],
         "requires": {"extensions": {"boats": "1.2.0"}, "python": {}}}
TIDES_SOURCE = SOURCE.replace("boats.summarize", "tides.forecast")
TIDES_TEST = TEST.replace("boats.summarize", "tides.forecast")


def _pack(tmp_path):
    tides = author(tmp_path, "tides", descriptor=TIDES, source=TIDES_SOURCE, test=TIDES_TEST)
    boats = author(tmp_path, "boats")
    pack_path = tmp_path / "nerva-pack.json"
    export_pack([tides, boats], pack_path)
    return pack_path


def test_a_pack_pins_exact_bytes_and_installs_one_card_per_extension_in_dependency_order(tmp_path):
    pack_path = _pack(tmp_path)
    pack = json.loads(pack_path.read_text())
    assert all(len(entry["source_sha256"]) == 64 and entry["directory"] in {"boats", "tides"}
               for entry in pack["extensions"])
    assert [item.manifest.id for item in load_pack(pack_path)] == ["boats", "tides"]
    code, out, _err, posted = _cli(["pack", "install", str(pack_path)])
    assert code == 0 and [body["manifest"]["id"] for _route, body in posted] == ["boats", "tides"]
    assert out.count("install card #") == 2
    assert all(body["provenance"] == {"kind": "pack"} for _route, body in posted)


def test_a_pack_whose_bytes_moved_is_refused_whole_before_anything_is_sent(tmp_path):
    pack_path = _pack(tmp_path)
    (tmp_path / "tides" / "main.py").write_text(TIDES_SOURCE + "\n# changed\n")
    code, _out, err, posted = _cli(["pack", "install", str(pack_path)])
    assert code == 1 and posted == [] and "pin_mismatch" in err


@pytest.mark.parametrize(("mutate", "reason"), [
    (lambda pack: pack.update(consent={"boats": "granted"}), "pack_carries_consent_or_config"),
    (lambda pack: pack["extensions"][0].update(config={"api_key": "x"}), "pack_carries_consent_or_config"),
    (lambda pack: pack["extensions"][0].update(granted_capabilities=["tools"]), "pack_carries_consent_or_config"),
    (lambda pack: pack["extensions"][0].update(source_sha256="main"), "pin_not_exact"),
    (lambda pack: pack["extensions"][0].update(source_sha256="A" * 64), "pin_not_exact"),
    (lambda pack: pack["extensions"][0].update(directory="../outside"), "directory_outside_pack"),
    (lambda pack: pack["extensions"][0].update(directory="/etc"), "directory_outside_pack"),
    (lambda pack: pack["extensions"][0].update(distribution="nerva-boats"), "entry_needs_one_source"),
    (lambda pack: pack["extensions"].append(dict(pack["extensions"][0])), "extension_collision"),
    (lambda pack: pack.update(pack_version=2), "unsupported_pack_version"),
])
def test_a_pack_carries_only_exact_pins(tmp_path, mutate, reason):
    pack = json.loads(_pack(tmp_path).read_text())
    mutate(pack)
    with pytest.raises(PackError) as refused:
        parse_pack(json.dumps(pack).encode())
    assert refused.value.reason == reason


def test_a_pack_is_bounded_and_symlinked_folders_are_refused(tmp_path):
    with pytest.raises(PackError, match="pack_too_large"):
        parse_pack(b" " * (1024 * 1024 + 1))
    pack_path = _pack(tmp_path)
    pack = json.loads(pack_path.read_text())
    (tmp_path / "linked").symlink_to(tmp_path / "boats")
    pack["extensions"][0]["directory"] = "linked"
    pack_path.write_text(json.dumps(pack))
    with pytest.raises(PackError) as refused:
        load_pack(pack_path)
    assert refused.value.reason in {"directory_outside_pack", "pin_mismatch", "version_mismatch"}


# ── after the card: the installed package activates through the existing gates ──

class _RuntimeProfile:
    def __init__(self, real):
        self.image, self.config_hash = real.image, real.config_hash
        self.timeout_seconds, self.max_output_bytes = 30.0, 32 * 1024

    def seal_mount(self, path):
        pass

    def build_command(self, *, source_dir, contract_dir, container_name, command):
        return ["docker", "run", str(source_dir), str(contract_dir), container_name, *command]


class _InvokeRunner:
    async def run(self, command, *, container_name):
        source_dir, contract_dir = Path(command[2]), Path(command[3])
        script = (contract_dir / "invoke.py").read_text(encoding="utf-8")
        local = contract_dir / "local_invoke.py"
        local.write_text(script.replace("/workspace/source", str(source_dir)).replace(
            "/workspace/contract", str(contract_dir)), encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(local)], capture_output=True, text=True, timeout=60)
        return SimpleNamespace(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr, timed_out=False)


@pytest.mark.asyncio
async def test_the_installed_package_still_needs_consent_then_activates_as_declared(tmp_path, hub):
    from agents.core.extensions.consent import ExtensionConsentStore
    from agents.core.extensions.runtime import ExtensionRuntime, ExtensionRuntimeError

    authored = read_directory(author(tmp_path))
    await submission.submit(hub.acquisition, authored, orch=hub.orch, runner=hub.runner)
    assert (await irreversible.execute(_task(hub), orch=hub.orch))["status"] == "installed"
    consent = ExtensionConsentStore(tmp_path / "consent.json")
    runtime = ExtensionRuntime(packages=hub.packages, profile=_RuntimeProfile(hub.broker.profile),
                               runtime_root=tmp_path / "runs", runner=_InvokeRunner(), consent=consent,
                               enabled=lambda: True)
    with pytest.raises(ExtensionRuntimeError, match="consent"):
        await runtime.activate(authored.manifest)
    consent.grant(authored.manifest)
    activation = await runtime.activate(authored.manifest)
    assert activation.as_dict()["callable_tools"] == ["boats.summarize"] and activation.version == "1.2.0"
    assert await runtime.dispatch("boats.summarize", {"text": "a blue boat"}) == {"summary": "a blue boat"}
