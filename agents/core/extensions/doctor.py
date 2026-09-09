"""Read-only extension diagnostics, without candidate imports or runtime startup."""

from __future__ import annotations

from importlib import metadata

from .manifest import (
    API_VERSION,
    MANIFEST_VERSION,
    MAX_EXTENSIONS,
    ManifestError,
    load_manifest,
    parse_manifest,
    validate_catalog,
)


def _declarations(manifest):
    return {
        "id": manifest.id, "version": manifest.version,
        "manifest_version": MANIFEST_VERSION, "api_version": API_VERSION,
        "declared_tools": list(manifest.qualified_tools),
        "declared_commands": list(manifest.commands), "declared_events": list(manifest.events),
        "capabilities": list(manifest.capabilities),
        "execution_available": False, "callable_tools": [], "callable_commands": [],
        "reason": "sdk_dispatch_unavailable",
    }


def doctor_paths(paths) -> dict:
    """Validate a complete named descriptor set; a valid descriptor grants nothing.

    Package requirements describe exact distribution metadata in this interpreter,
    not an isolated backend image. No install/import/availability probe is made.
    """
    result = {"ok": False, "mode": "inspection_only", "extensions": [], "errors": [], "order": []}
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_EXTENSIONS:
        result["errors"] = [{"reason": "extension_capacity"}]
        return result
    manifests = []
    for index, path in enumerate(paths):
        try:
            manifests.append(load_manifest(path))
        except (ManifestError, TypeError) as exc:
            # The normalized reason is safe; descriptor paths/content are not
            # reflected into terminal output (including terminal escape codes).
            reason = str(exc) if isinstance(exc, ManifestError) else "manifest_unreadable"
            result["errors"].append({"index": index, "reason": reason})
    if result["errors"]:
        return result
    try:
        catalog = validate_catalog(manifests)
    except ManifestError as exc:
        result["errors"] = [{"reason": str(exc)}]
        return result
    result["order"] = catalog["order"]
    result["dependency_issues"] = catalog["issues"]
    by_id = {manifest.id: manifest for manifest in manifests}
    rows, installed = {}, {}
    for name in catalog["order"]:
        manifest = by_id[name]
        row = _declarations(manifest)
        row.update({"source": "unsigned_descriptor", "trust": "unverified", "python_dependencies": [], "issues": []})
        row["issues"].extend(issue["reason"] for issue in catalog["issues"] if issue["extension"] == name)
        for distribution, required in manifest.python_requires:
            if distribution not in installed:
                try:
                    installed[distribution] = metadata.version(distribution)
                except metadata.PackageNotFoundError:
                    installed[distribution] = None
                except Exception:
                    installed[distribution] = "unavailable"
            version = installed[distribution]
            satisfied = version == required
            row["python_dependencies"].append({"distribution": distribution, "required": required, "installed": version, "satisfied": satisfied})
            if not satisfied:
                row["issues"].append("python_dependency_missing" if version is None else "python_version_mismatch")
        for dependency, _ in manifest.extension_requires:
            if dependency in rows and not rows[dependency]["dependencies_satisfied"]:
                row["issues"].append("extension_dependency_unavailable")
        row["issues"] = sorted(set(row["issues"]))
        row["dependencies_satisfied"] = not row["issues"]
        rows[name] = row
    result["extensions"] = list(rows.values())
    result["ok"] = all(row["dependencies_satisfied"] for row in rows.values())
    return result


def inspect_acquisition(runtime) -> dict:
    """Project already-composed signed packages; never initialize or promote them.

    An acquired package's legacy sandbox tool is not an S2 extension handler. The
    projection identifies its declared entrypoint but advertises no SDK callables.
    Signature validity is not proof of approval or of a usable isolated runtime.
    """
    result = {"mode": "inspection_only", "extensions": [], "reason": "acquisition_unavailable"}
    if runtime is None:
        return result
    try:
        if runtime.is_enabled() is not True:
            result["reason"] = "acquisition_disabled"
            return result
        packages = runtime.package_store
        if packages is None:
            result["reason"] = "acquisition_not_composed"
            return result
        records = packages.list_records(include_retained=True)
        if len(records) > MAX_EXTENSIONS:
            result["reason"] = "extension_capacity"
            return result
        rows = []
        for record in records:
            source = record.manifest
            manifest = parse_manifest({
                "manifest_version": 1, "api_version": 1,
                "id": source["name"], "version": source["version"],
                "capabilities": ["tools"], "tools": [source["entrypoint"]],
                "commands": [], "events": [], "requires": {"extensions": {}, "python": {}},
            })
            row = _declarations(manifest)
            row.update({"source": "acquired_manifest_projection", "signature_verified": False,
                        "approval_verified": False, "quarantine_state": "not_inspected",
                        "lifecycle_status": record.status, "reason": "acquired_inactive"})
            if record.active and record.status == "active":
                row["reason"] = "acquired_integrity_unverified"
                try:
                    verified = packages.require_runnable(record.name)
                    if (verified.package_hash == record.package_hash and verified.manifest == source
                            and record.name == manifest.id and record.version == manifest.version):
                        row["signature_verified"] = True
                        row["reason"] = "sdk_dispatch_unavailable"
                except Exception:
                    pass
            rows.append(row)
        result.update({"extensions": rows, "reason": "sdk_dispatch_unavailable"})
    except Exception:
        result.update({"extensions": [], "reason": "acquisition_inspection_unavailable"})
    return result
