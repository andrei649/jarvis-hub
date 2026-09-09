"""Versioned, data-only extension declarations. Parsing never registers handlers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST_VERSION = 1
API_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
MAX_EXTENSIONS = 128
MAX_DECLARATIONS = 64
CAPABILITIES = frozenset({"tools", "commands", "events.observe"})
EVENTS = frozenset({"command.completed", "session.started", "session.ended", "tool.completed"})
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})(?:[-+][A-Za-z0-9.-]{1,40})?")
_DISTRIBUTION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?")
_PYTHON_VERSION = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9}){0,3}(?:(?:a|b|rc|\.post|\.dev)[0-9]{1,9})?")


class ManifestError(ValueError):
    """Only bounded reason codes escape to CLI/HTTP; never candidate source text."""


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    id: str
    version: str
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    commands: tuple[str, ...]
    events: tuple[str, ...]
    extension_requires: tuple[tuple[str, str], ...]
    python_requires: tuple[tuple[str, str], ...]

    @property
    def qualified_tools(self) -> tuple[str, ...]:
        return tuple(f"{self.id}.{name}" for name in self.tools)


def _names(value, *, allowed=None):
    if not isinstance(value, list) or len(value) > MAX_DECLARATIONS:
        raise ManifestError("invalid_declarations")
    if any(not isinstance(name, str) or (name not in allowed if allowed is not None else _NAME.fullmatch(name) is None) for name in value):
        raise ManifestError("invalid_declarations")
    if len(set(value)) != len(value):
        raise ManifestError("duplicate_declaration")
    return tuple(sorted(value))


def core_commands() -> frozenset[str]:
    # This imports only our in-tree registry, without invoking any handler.
    from ..commands import Principal, build_default_registry

    return frozenset(command.name.lower() for command in build_default_registry().visible(Principal(admin=True)))


def _dependencies(value, *, python=False):
    if not isinstance(value, dict) or len(value) > MAX_DECLARATIONS:
        raise ManifestError("invalid_dependencies")
    result = {}
    for name, version in value.items():
        pattern = _DISTRIBUTION if python else _NAME
        versions = _PYTHON_VERSION if python else _VERSION
        if not isinstance(name, str) or pattern.fullmatch(name) is None or not isinstance(version, str) or versions.fullmatch(version) is None:
            raise ManifestError("invalid_dependencies")
        canonical = re.sub(r"[-_.]+", "-", name).lower() if python else name
        if canonical in result:
            raise ManifestError("dependency_collision")
        result[canonical] = version
    return tuple(sorted(result.items()))


def parse_manifest(value) -> ExtensionManifest:
    fields = {"manifest_version", "api_version", "id", "version", "capabilities", "tools", "commands", "events", "requires"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ManifestError("invalid_manifest_fields")
    if type(value["manifest_version"]) is not int or value["manifest_version"] != MANIFEST_VERSION:
        raise ManifestError("unsupported_manifest_version")
    if type(value["api_version"]) is not int or value["api_version"] != API_VERSION:
        raise ManifestError("unsupported_api_version")
    if not isinstance(value["id"], str) or _NAME.fullmatch(value["id"]) is None:
        raise ManifestError("invalid_extension_id")
    if not isinstance(value["version"], str) or _VERSION.fullmatch(value["version"]) is None:
        raise ManifestError("invalid_extension_version")
    capabilities = _names(value["capabilities"], allowed=CAPABILITIES)
    tools, commands = _names(value["tools"]), _names(value["commands"])
    events = _names(value["events"], allowed=EVENTS)
    required = {name for name, declarations in (("tools", tools), ("commands", commands), ("events.observe", events)) if declarations}
    if set(capabilities) != required:
        raise ManifestError("capability_declaration_mismatch")
    if set(commands) & core_commands():
        raise ManifestError("command_collision")
    requires = value["requires"]
    if not isinstance(requires, dict) or set(requires) != {"extensions", "python"}:
        raise ManifestError("invalid_dependencies")
    return ExtensionManifest(value["id"], value["version"], capabilities, tools, commands, events,
                             _dependencies(requires["extensions"]), _dependencies(requires["python"], python=True))


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ManifestError("duplicate_json_key")
        result[name] = value
    return result


def load_manifest(path: str | Path) -> ExtensionManifest:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise ManifestError("manifest_not_regular_file")
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest_too_large")
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except ManifestError:
        raise
    except (OSError, ValueError, RecursionError):
        raise ManifestError("manifest_unreadable") from None
    return parse_manifest(value)


def validate_catalog(manifests, *, reserved_commands=(), reserved_tools=()) -> dict:
    if not isinstance(manifests, (list, tuple)) or len(manifests) > MAX_EXTENSIONS:
        raise ManifestError("extension_capacity")
    by_id, commands, tools = {}, set(core_commands()) | set(reserved_commands), set(reserved_tools)
    for manifest in manifests:
        if not isinstance(manifest, ExtensionManifest):
            raise ManifestError("invalid_manifest")
        if manifest.id in by_id:
            raise ManifestError("extension_collision")
        if set(manifest.commands) & commands:
            raise ManifestError("command_collision")
        if set(manifest.qualified_tools) & tools:
            raise ManifestError("tool_collision")
        by_id[manifest.id] = manifest
        commands.update(manifest.commands)
        tools.update(manifest.qualified_tools)
    order, issues, visiting, visited = [], [], set(), set()

    def visit(name):
        if name in visiting:
            raise ManifestError("dependency_cycle")
        if name in visited:
            return
        visiting.add(name)
        for dependency, version in by_id[name].extension_requires:
            target = by_id.get(dependency)
            if target is None:
                reason = "extension_dependency_missing"
            else:
                visit(dependency)
                reason = "extension_version_mismatch" if version != target.version else None
            if reason:
                issues.append({"extension": name, "reason": reason, "dependency": dependency, "required": version})
        visiting.remove(name)
        visited.add(name)
        order.append(name)

    for name in sorted(by_id):
        visit(name)
    return {"order": order, "issues": issues}


def validate_registration(manifest: ExtensionManifest, registered: dict) -> None:
    """S2 must compare an isolated registration response before exposing it.

    This checks declaration equality only, and never grants permission to dispatch.
    """
    expected = {"tools": manifest.qualified_tools, "commands": manifest.commands, "events": manifest.events}
    if not isinstance(registered, dict) or set(registered) != set(expected):
        raise ManifestError("registration_mismatch")
    for kind, names in expected.items():
        value = registered[kind]
        if not isinstance(value, (list, tuple)) or len(value) != len(names) or any(not isinstance(name, str) for name in value) or set(value) != set(names):
            raise ManifestError("registration_mismatch")
