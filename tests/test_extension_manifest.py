"""Declarative extension inputs cannot import code or create authority."""

import copy
import importlib
import json

import pytest


def api():
    return importlib.import_module("agents.core.extensions.manifest")


def descriptor(name="boats", **changes):
    return {
        "manifest_version": 1, "api_version": 1, "id": name, "version": "1.0.0",
        "capabilities": ["tools", "commands", "events.observe"],
        "tools": ["summarize"], "commands": [name + "_summary"],
        "events": ["tool.completed"], "requires": {"extensions": {}, "python": {}},
        **changes,
    }


def test_valid_descriptor_is_immutable_and_namespaces_declared_tools():
    source = descriptor()
    manifest = api().parse_manifest(source)
    source["tools"].append("injected")
    assert manifest.qualified_tools == ("boats.summarize",)
    assert manifest.commands == ("boats_summary",)
    with pytest.raises((AttributeError, TypeError)):
        manifest.id = "changed"


@pytest.mark.parametrize("change", [
    {"manifest_version": True}, {"manifest_version": 2}, {"api_version": "1"},
    {"api_version": 2}, {"id": "../boats"}, {"version": "latest"},
    {"capabilities": ["network"]}, {"capabilities": ["tools"]},
    {"tools": ["summarize", "summarize"]}, {"tools": ["os.system"]},
    {"commands": ["pause"]}, {"commands": ["HELP"]},
    {"events": ["before_authorize"]}, {"hooks": {"start": "sh setup.sh"}},
    {"entrypoint": "danger.py"}, {"url": "https://example.com/plugin.git"},
    {"requires": {"python": {"pkg @ https://evil": "1.0"}, "extensions": {}}},
    {"requires": {"python": {"requests": ">=1"}, "extensions": {}}},
])
def test_invalid_or_unsupported_contract_is_rejected(change):
    with pytest.raises(api().ManifestError):
        api().parse_manifest(descriptor(**change))


def test_descriptor_reads_are_bounded_and_reject_duplicate_json_keys(tmp_path):
    path = tmp_path / "extension.json"
    path.write_text('{"id":"boats","id":"other"}')
    with pytest.raises(api().ManifestError, match="duplicate_json_key"):
        api().load_manifest(path)
    path.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(api().ManifestError, match="manifest_too_large"):
        api().load_manifest(path)


def test_catalog_orders_dependencies_and_reports_missing_exact_versions():
    mod = api()
    base = mod.parse_manifest(descriptor("base"))
    child = mod.parse_manifest(descriptor("boats", requires={
        "extensions": {"base": "1.0.0", "missing": "2.0.0"}, "python": {},
    }))
    report = mod.validate_catalog([child, base])
    assert report["order"] == ["base", "boats"]
    assert report["issues"] == [{"extension": "boats", "reason": "extension_dependency_missing", "dependency": "missing", "required": "2.0.0"}]
    wrong = mod.parse_manifest(descriptor("base", version="2.0.0"))
    assert any(x["reason"] == "extension_version_mismatch" for x in mod.validate_catalog([child, wrong])["issues"])


def test_cycles_and_cross_extension_command_collisions_fail():
    mod = api()
    left = mod.parse_manifest(descriptor("left", requires={"extensions": {"right": "1.0.0"}, "python": {}}))
    right = mod.parse_manifest(descriptor("right", requires={"extensions": {"left": "1.0.0"}, "python": {}}))
    with pytest.raises(mod.ManifestError, match="dependency_cycle"):
        mod.validate_catalog([left, right])
    duplicate = mod.parse_manifest(descriptor("other", commands=["left_summary"]))
    with pytest.raises(mod.ManifestError, match="command_collision"):
        mod.validate_catalog([left, duplicate])
    with pytest.raises(mod.ManifestError, match="extension_collision"):
        mod.validate_catalog([left, left])


def test_explicit_host_reserved_commands_and_tools_cannot_be_shadowed():
    mod = api()
    manifest = mod.parse_manifest(descriptor())
    with pytest.raises(mod.ManifestError, match="command_collision"):
        mod.validate_catalog([manifest], reserved_commands=["boats_summary"])
    with pytest.raises(mod.ManifestError, match="tool_collision"):
        mod.validate_catalog([manifest], reserved_tools=["boats.summarize"])


def test_registration_contract_refuses_missing_extra_and_duplicate_declarations():
    mod = api()
    manifest = mod.parse_manifest(descriptor())
    registered = {"tools": ["boats.summarize"], "commands": ["boats_summary"], "events": ["tool.completed"]}
    mod.validate_registration(manifest, registered)
    for key in registered:
        bad = copy.deepcopy(registered)
        bad[key] = []
        with pytest.raises(mod.ManifestError, match="registration_mismatch"):
            mod.validate_registration(manifest, bad)
        bad[key] = registered[key] * 2
        with pytest.raises(mod.ManifestError, match="registration_mismatch"):
            mod.validate_registration(manifest, bad)
    with pytest.raises(mod.ManifestError, match="registration_mismatch"):
        mod.validate_registration(manifest, {**registered, "shell": ["sh"]})


def test_dependency_distribution_names_are_canonical_and_alias_duplicates_fail():
    mod = api()
    manifest = mod.parse_manifest(descriptor(requires={"extensions": {}, "python": {"A_B": "1.2.3"}}))
    assert manifest.python_requires == (("a-b", "1.2.3"),)
    with pytest.raises(mod.ManifestError, match="dependency_collision"):
        mod.parse_manifest(descriptor(requires={"extensions": {}, "python": {"A_B": "1.2.3", "a-b": "1.2.3"}}))


def test_loading_descriptor_never_executes_adjacent_python(tmp_path):
    (tmp_path / "__init__.py").write_text("raise RuntimeError('must not import')")
    (tmp_path / "main.py").write_text("raise RuntimeError('must not run')")
    path = tmp_path / "extension.json"
    path.write_text(json.dumps(descriptor()))
    assert api().load_manifest(path).id == "boats"


@pytest.mark.parametrize("raw", [b"\xff", b"[]", b"[" * 2000])
def test_malformed_encoding_shape_and_recursion_are_named_errors(tmp_path, raw):
    path = tmp_path / "extension.json"
    path.write_bytes(raw)
    with pytest.raises(api().ManifestError):
        api().load_manifest(path)


def test_directory_and_oversized_catalog_are_refused(tmp_path):
    with pytest.raises(api().ManifestError, match="manifest_not_regular_file"):
        api().load_manifest(tmp_path)
    with pytest.raises(api().ManifestError, match="extension_capacity"):
        api().validate_catalog([object()] * 129)
