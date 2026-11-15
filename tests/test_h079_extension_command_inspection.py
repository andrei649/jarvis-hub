"""Signed extension inspector regressions against a real extension activation rig."""

from types import SimpleNamespace

import pytest

from agents.core.commands import Principal, SlashCommand, build_default_registry
from agents.core.extensions.doctor import inspect_acquisition
from tests.test_extension_runtime import COMMAND_EXTENSION, descriptor
from tests.test_extension_runtime import rig as rig  # noqa: F401


def _acquisition(rig):
    record = rig.packages.record
    record.manifest.update(name=record.name, version=record.version, entrypoint="run")
    record.active = True
    record.status = "active"
    rig.packages.list_records = lambda *, include_retained: [record]
    return SimpleNamespace(is_enabled=lambda: True, package_store=rig.packages,
                           extension_runtime=rig.runtime)


async def _activate(rig):
    rig.runtime.commands = build_default_registry()
    rig.packages.write(COMMAND_EXTENSION)
    manifest = descriptor(tools=[], commands=["boat_report"],
                          command_requires_args=["boat_report"])
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    return _acquisition(rig)


def _row(acquisition):
    return inspect_acquisition(acquisition)["extensions"][0]


@pytest.mark.asyncio
async def test_active_signed_command_inspected_without_extra_runner_or_import(rig):
    acquisition = await _activate(rig)
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert len(rig.runner.calls) == before
    assert row["signature_verified"] is True
    assert row["declared_commands"] == ["boat_report"]
    assert row["command_requires_args"] == ["boat_report"]
    assert row["callable_commands"] == ["boat_report"]
    assert row["execution_available"] is True and row["reason"] == "activated"
    result = await rig.runtime.commands.dispatch("/boat_report today", orch=None,
                                                  principal=Principal(admin=True))
    assert result.status == "answered" and result.reply == "Report: today"
    assert len(rig.runner.calls) == before + 1


@pytest.mark.asyncio
async def test_deactivation_removes_callable_projection(rig):
    acquisition = await _activate(rig)
    assert _row(acquisition)["callable_commands"] == ["boat_report"]
    await rig.runtime.deactivate("boats")
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["callable_commands"] == [] and row["execution_available"] is False
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_revoked_consent_does_not_advertise_stale_active_command(rig):
    acquisition = await _activate(rig)
    rig.consent.revoke("boats")  # Deliberately leave the in-memory activation present.
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["declared_commands"] == ["boat_report"]
    assert row["callable_commands"] == [] and row["execution_available"] is False
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_changed_package_does_not_attribute_stale_commands_to_current_record(rig):
    acquisition = await _activate(rig)
    rig.packages.record.package_hash = "d" * 64
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["declared_commands"] == [] and row["callable_commands"] == []
    assert row["execution_available"] is False
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_unavailable_consent_package_and_runtime_fail_closed(rig, monkeypatch):
    acquisition = await _activate(rig)
    before = len(rig.runner.calls)

    def unavailable(_manifest):
        raise OSError("private detail")

    monkeypatch.setattr(rig.consent, "check", unavailable)
    assert _row(acquisition)["callable_commands"] == []
    assert len(rig.runner.calls) == before
    monkeypatch.undo()

    rig.packages.available = False
    assert _row(acquisition)["callable_commands"] == []
    rig.packages.available = True
    rig.runtime.enabled = lambda: False
    assert _row(acquisition)["callable_commands"] == []
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_registry_replacement_cannot_be_advertised_as_extension_command(rig):
    acquisition = await _activate(rig)
    registry = rig.runtime.commands
    original = registry.get("boat_report")
    assert registry.unregister(original)
    registry.register(SlashCommand("boat_report", "replacement", lambda ctx: "wrong"))
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["callable_commands"] == [] and row["execution_available"] is False
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_cli_accepts_truthful_active_command_inspection(rig):
    """Expected red until the separately owned CLI validator is updated."""
    import io

    from agents.cli.nerva import Context, main

    acquisition = await _activate(rig)
    out, err = io.StringIO(), io.StringIO()
    context = Context(environ={}, out=out, err=err,
                      client_factory=lambda _: SimpleNamespace(get=lambda path:
                                                               inspect_acquisition(acquisition)))
    assert main(["extensions", "list", "--json"], context=context) == 0
    assert '"boat_report"' in out.getvalue()

@pytest.mark.asyncio
async def test_existing_tool_projection_is_also_fenced_by_current_consent(rig):
    from tests.test_extension_runtime import EXTENSION

    rig.packages.write(EXTENSION)
    manifest = descriptor()
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    acquisition = _acquisition(rig)
    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["callable_tools"] == ["boats.summarize"]
    rig.consent.revoke("boats")
    row = _row(acquisition)
    assert row["callable_tools"] == [] and row["execution_available"] is False
    assert len(rig.runner.calls) == before


MIXED_EXTENSION = '''
def register():
    return {"tools": ["boats.summarize"], "commands": ["boat_report"], "events": ["session.started"]}
def call(tool, payload):
    return {"tool": tool, "seen": payload}
def command(name, args):
    return "Report: " + args
'''


async def _activate_mixed(rig):
    from agents.core.commands import build_default_registry

    rig.runtime.commands = build_default_registry()
    record = rig.packages.write(MIXED_EXTENSION)
    record.manifest.update(name=record.name, version=record.version, entrypoint="run")
    record.active = True
    record.status = "active"
    rig.packages.list_records = lambda *, include_retained: [record]
    manifest = descriptor(tools=["summarize"], commands=["boat_report"],
                          events=["session.started"], command_requires_args=["boat_report"])
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    return _acquisition(rig)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["replaced_registration", "quick_collision"])
async def test_command_only_collision_keeps_valid_tool_projection(rig, monkeypatch, failure):
    acquisition = await _activate_mixed(rig)
    registry = rig.runtime.commands
    if failure == "replaced_registration":
        from agents.core.commands import SlashCommand

        owned = rig.runtime._command_registrations["boats"][0]
        assert registry.unregister(owned)
        registry.register(SlashCommand("boat_report", "replacement", lambda _ctx: "replacement"))
    else:
        import agents.core.quick_commands as quick_commands

        monkeypatch.setattr(quick_commands, "named", lambda name: name in {"boat_report", "boat-report"})

    before = len(rig.runner.calls)
    row = _row(acquisition)
    assert row["declared_tools"] == ["boats.summarize"]
    assert row["declared_commands"] == ["boat_report"]
    assert row["declared_events"] == ["session.started"]
    assert row["command_requires_args"] == ["boat_report"]
    assert row["capabilities"] == ["commands", "events.observe", "tools"]
    assert row["callable_tools"] == ["boats.summarize"]
    assert row["callable_commands"] == []
    assert row["execution_available"] is True and row["reason"] == "activated"
    assert len(rig.runner.calls) == before


@pytest.mark.asyncio
async def test_mixed_tool_and_command_projection_revocation_or_package_change_hides_both(rig):
    acquisition = await _activate_mixed(rig)
    rig.consent.revoke("boats")
    row = _row(acquisition)
    assert row["callable_tools"] == [] and row["callable_commands"] == []
    assert row["execution_available"] is False

    # Regrant and activate afresh, then change the signed package identity.
    await rig.runtime.deactivate("boats")
    acquisition = await _activate_mixed(rig)
    rig.packages.record.package_hash = "d" * 64
    row = _row(acquisition)
    assert row["declared_tools"] == ["boats.run"]
    assert row["declared_commands"] == []
    assert row["callable_tools"] == [] and row["callable_commands"] == []
    assert row["execution_available"] is False



def test_offline_acquisition_failure_is_bounded_and_read_only():
    from types import SimpleNamespace

    from agents.core.extensions.doctor import inspect_acquisition

    assert inspect_acquisition(None) == {
        "mode": "inspection_only", "extensions": [], "reason": "acquisition_unavailable"}
    runtime = SimpleNamespace(is_enabled=lambda: True,
                              package_store=SimpleNamespace(
                                  list_records=lambda **_kwargs: (_ for _ in ()).throw(
                                      RuntimeError("secret package detail"))))
    report = inspect_acquisition(runtime)
    assert report == {"mode": "inspection_only", "extensions": [],
                      "reason": "acquisition_inspection_unavailable"}
    assert "secret package detail" not in repr(report)
