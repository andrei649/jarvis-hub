"""Required argument menu metadata is optional and separately consented."""

from __future__ import annotations

import os

import pytest

from agents.core.extensions.consent import CHANGED, GRANTED, ExtensionConsentStore, declared_digest
from agents.core.extensions.manifest import ExtensionManifest, ManifestError, parse_manifest


def _descriptor(**changes):
    value = {
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["commands"], "tools": [],
        "commands": ["boat_report", "boat_ping"], "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    return {**value, **changes}


@pytest.fixture
def consent(tmp_path):
    previous_umask = os.umask(0o077)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    try:
        yield ExtensionConsentStore(private / "consent.json")
    finally:
        os.umask(previous_umask)


def test_absent_and_empty_metadata_preserve_old_manifest_and_consent_digest():
    old = parse_manifest(_descriptor())
    empty = parse_manifest(_descriptor(command_requires_args=[]))
    assert old.command_requires_args == empty.command_requires_args == ()
    assert old == empty
    assert declared_digest(old) == declared_digest(empty) == (
        "1494a978005c08d06327f312e5143cff84a325364f1879fb82f705e7267aa93e")
    positional = ExtensionManifest(old.id, old.version, old.capabilities, old.tools,
                                   old.commands, old.events, old.extension_requires,
                                   old.python_requires)
    assert positional.command_requires_args == () and positional == old


def test_subset_is_sorted_and_new_declaration_requires_new_consent(consent):
    old = parse_manifest(_descriptor())
    assert consent.grant(old).state == GRANTED
    required = parse_manifest(_descriptor(command_requires_args=["boat_report", "boat_ping"]))
    assert required.command_requires_args == ("boat_ping", "boat_report")
    assert required.commands == old.commands
    assert declared_digest(required) != declared_digest(old)
    changed = consent.check(required)
    assert changed.state == CHANGED and changed.allowed is False
    assert changed.added == ("command_requires_args:boat_ping", "command_requires_args:boat_report")
    assert changed.removed == ()
    assert consent.grant(required).state == GRANTED
    removed = consent.check(old)
    assert removed.state == CHANGED and removed.allowed is False
    assert removed.removed == changed.added


@pytest.mark.parametrize("metadata", [
    None, "boat_report", ("boat_report",), {"boat_report": True},
    ["boat_report", "boat_report"], ["undeclared"], ["Boat_Report"],
    ["boat_report", 42], ["boat_report"] * 65,
])
def test_malformed_unknown_duplicate_and_oversized_metadata_refused(metadata):
    with pytest.raises(ManifestError, match="invalid_declarations|duplicate_declaration"):
        parse_manifest(_descriptor(command_requires_args=metadata))


def test_only_the_optional_field_is_added_to_manifest_schema():
    with pytest.raises(ManifestError, match="invalid_manifest_fields"):
        parse_manifest(_descriptor(command_requires_args=[], unrelated=True))
    no_commands = _descriptor(commands=[], capabilities=[], command_requires_args=[])
    assert parse_manifest(no_commands).command_requires_args == ()
    no_commands["command_requires_args"] = ["boat_report"]
    with pytest.raises(ManifestError, match="invalid_declarations"):
        parse_manifest(no_commands)
