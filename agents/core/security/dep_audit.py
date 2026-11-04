"""H022 dependency inventory and OSV audit for installed, declared, and MCP pins.

Adapted parser and audit patterns from hermes_cli/security_audit.py and
hermes_cli/subcommands/security.py at 59b2aeef6c7a (Copyright 2025
NousResearch); see the adjacent dep_audit.LICENSE.

The CLI enumerates this interpreter's distributions, owner-declared extension
manifests, and exact pinned npx/uvx package refs in saved MCP commands. Catalog
entries are declarations, never proof that an extension is installed or active.
Unpinned or unsupported MCP commands are named as unaudited. Missing legacy
catalog metadata is reported as unavailable coverage, never silently clean.

Unknown advisory severity fails every threshold. The admin hub runs OSV lookups
through the shared PluginHTTPClient with live plugin.egress kernel authorization
and durable egress accounting. Only package name/version pairs leave the machine.
Database text is sanitized for terminal output; tests inject offline clients.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import metadata as _metadata
from pathlib import Path, PurePath
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

DEFAULT_OSV_URL = "https://api.osv.dev"
#: OSV rejects batches above this; https://google.github.io/osv.dev/post-v1-querybatch/
BATCH_LIMIT = 1000
SEVERITIES: tuple[str, ...] = ("critical", "high", "moderate", "low", "unknown")
_RANK = {level: index for index, level in enumerate(SEVERITIES)}
_LEVELS = {"critical": "critical", "high": "high", "moderate": "moderate",
           "medium": "moderate", "low": "low"}
MCP_REASON = "no exact pinned npx/uvx package refs selected; other commands are listed as unaudited"
_NPM_EXACT = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
#: Longest advisory summary a terminal line carries; ``--json`` keeps the whole text.
SUMMARY_WIDTH = 160
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TOKEN = re.compile(r"[^A-Za-z0-9._+-]")


def _clean(text: Any, width: int | None = None) -> str:
    """Terminal-safe text: control characters (ESC, CR, LF, …) become spaces; optionally cut."""
    out = _CONTROL.sub(" ", "" if text is None else str(text))
    if width is not None and len(out) > width:
        out = out[: max(width - 1, 0)] + "…"
    return out


def _safe_token(text: Any, fallback: str = "unknown") -> str:
    """A filesystem-derived name reduced to ``[A-Za-z0-9._+-]``; anything else is *fallback*."""
    token = "" if text is None else str(text)
    return token if token and not _TOKEN.search(token) and len(token) <= 120 else fallback


class OSVUnavailable(RuntimeError):
    """The database could not be consulted. Nothing about the components is claimed."""


# ── components ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Component:
    surface: str          # installed | extension | mcp
    name: str             # canonical PyPI name or exact npm package
    version: str
    origin: str           # importlib.metadata, or the extension id that declared the pin
    ecosystem: str = "PyPI"

    def to_dict(self) -> dict[str, str]:
        return {"surface": self.surface, "name": self.name, "version": self.version,
                "origin": self.origin, "ecosystem": self.ecosystem}


def _dist_location(dist: Any) -> str:
    """The ``*.dist-info`` directory name, reduced to a safe token — enough to find it, nothing more."""
    path = getattr(dist, "_path", None)
    return _safe_token(PurePath(str(path)).name if path is not None else None)


def enumerate_installed(
    distributions: Iterable[Any] | None = None,
) -> tuple[list[Component], list[dict[str, Any]]]:
    """Every distribution this interpreter can see, canonicalised and de-duplicated.

    A distribution whose metadata cannot be read (a ``METADATA`` file that is not UTF-8,
    for instance) is skipped *and named in the errors*: one broken package must neither
    take the audit down nor drop out of it silently.
    """
    seen: dict[tuple[str, str], Component] = {}
    errors: list[dict[str, Any]] = []
    for dist in (distributions if distributions is not None else _metadata.distributions()):
        try:
            meta = getattr(dist, "metadata", None)
            raw_name = meta.get("Name") if meta is not None and hasattr(meta, "get") else None
            version = getattr(dist, "version", None)
        except Exception as exc:  # corrupt or undecodable metadata: skip it, say so
            errors.append({"surface": "installed", "location": _dist_location(dist),
                           "reason": f"metadata_unreadable: {type(exc).__name__}",
                           "coverage_unavailable": True})
            continue
        if not isinstance(raw_name, str) or not raw_name.strip() or not isinstance(version, str) or not version:
            errors.append({"surface": "installed", "location": _dist_location(dist),
                           "reason": "metadata_incomplete", "coverage_unavailable": True})
            continue
        name = canonicalize_name(raw_name)
        seen.setdefault((name, version), Component("installed", name, version, "importlib.metadata"))
    return [seen[key] for key in sorted(seen)], errors


def enumerate_extensions(paths: Sequence[Any]) -> tuple[list[Component], list[dict[str, Any]]]:
    """Exact Python pins declared by each descriptor; an unreadable one is an error row, not a crash.

    Only the normalised reason is reported — descriptor paths and content are not
    reflected into output, the same posture ``nerva extensions doctor`` takes.
    """
    from agents.core.extensions.manifest import ManifestError, load_manifest

    components: list[Component] = []
    errors: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        try:
            manifest = load_manifest(path)
        except ManifestError as exc:
            errors.append({"surface": "extension", "index": index, "reason": str(exc),
                           "coverage_unavailable": True})
            continue
        except Exception:
            errors.append({"surface": "extension", "index": index, "reason": "manifest_unreadable",
                           "coverage_unavailable": True})
            continue
        for name, version in manifest.python_requires:
            components.append(Component("extension", canonicalize_name(name), version, manifest.id))
    components.sort(key=lambda c: (c.name, c.version, c.origin))
    return components, errors


def enumerate_catalog() -> tuple[list[Component], list[dict[str, Any]]]:
    """Read the registered extension pin catalog without loading candidate code."""
    try:
        from agents.core.extensions.manifest_catalog import ExtensionManifestCatalog

        rows, errors = ExtensionManifestCatalog().snapshot()
        components = [
            Component("extension", canonicalize_name(name), version, row["id"])
            for row in rows for name, version in row["python_requires"]
        ]
        components.sort(key=lambda c: (c.name, c.version, c.origin))
        return components, errors
    except Exception:
        return [], [{"surface": "extension", "reason": "catalog_unavailable",
                     "coverage_unavailable": True}]


def mcp_surface() -> dict[str, Any]:
    return {"count": 0, "audited": False, "reason": MCP_REASON}


_NPX_REF = re.compile(r"^(@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+|[A-Za-z0-9._-]+)@([A-Za-z0-9._+-]+)$")
_UVX_REF = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._+!-]+)$")


def _mcp_package_refs(argv: list[str], launcher: str) -> list[str]:
    """Recognize package-valued launcher flags and the ordinary first positional ref.

    This is deliberately a narrow argv parser, not command execution or shell
    expansion. When a command declares explicit packages, its trailing program
    name is not another package; repeated declarations remain separate refs.
    """
    valued = {"-p", "--package"} if launcher == "npx" else {"--from", "--with"}
    refs: list[str] = []
    positional = ""
    has_from = False
    i = 1
    while i < len(argv):
        argument = argv[i]
        if argument == "--":
            if i + 1 < len(argv) and not positional:
                positional = argv[i + 1]
            break
        if argument in valued:
            has_from = has_from or argument == "--from"
            i += 1
            refs.append(argv[i] if i < len(argv) else "")
        elif any(argument.startswith(flag + "=") for flag in valued):
            has_from = has_from or argument.startswith("--from=")
            refs.append(argument.split("=", 1)[1])
        elif launcher == "npx" and argument.startswith("-p") and len(argument) > 2:
            refs.append(argument[2:])
        elif not argument.startswith("-") and not positional:
            positional = argument
            # Later options belong to the launched program, not npx/uvx.
            break
        i += 1
    if launcher == "uvx" and not has_from and positional:
        refs.insert(0, positional)
    elif launcher == "npx" and not refs and positional:
        refs.append(positional)
    return refs or [""]


def _saved_mcp_rows(db_path: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the owner's persisted MCP setting without initializing or changing settings."""
    from agents.core.paths import data_path

    path = db_path or data_path("settings.db")
    if not path.exists():
        return [], []
    if path.is_symlink() or not path.is_file():
        return [], [{"surface": "mcp", "reason": "configuration_unavailable", "coverage_unavailable": True}]
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE category='mcp' AND key='servers'"
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return [], []
        import json

        configs = json.loads(row[0])
        if not isinstance(configs, list) or len(configs) > 256:
            raise ValueError("invalid server list")
        return configs, []
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return [], [{"surface": "mcp", "reason": "configuration_unavailable", "coverage_unavailable": True}]


def enumerate_mcp(
    configs: Sequence[Any] | None = None, *, db_path: Path | None = None,
) -> tuple[list[Component], list[dict[str, Any]]]:
    """Discover exact npx/uvx package refs from saved stdio commands; execute none."""
    if configs is None:
        configs, errors = _saved_mcp_rows(db_path)
    else:
        errors = []
    components: list[Component] = []
    for index, row in enumerate(configs):
        if not isinstance(row, dict):
            errors.append({"surface": "mcp", "index": index, "reason": "invalid_server", "coverage_unavailable": True})
            continue
        name = _safe_token(row.get("name"), fallback=f"server-{index}")
        if row.get("transport", "stdio") != "stdio":
            errors.append({"surface": "mcp", "server": name, "reason": "non_stdio_not_audited",
                           "coverage_unavailable": True})
            continue
        command = row.get("command")
        try:
            argv = shlex.split(command) if isinstance(command, str) else []
        except ValueError:
            argv = []
        launcher = PurePath(argv[0].replace("\\", "/")).name.lower() if argv else ""
        if launcher.endswith((".cmd", ".exe")):
            launcher = launcher[:-4]
        if launcher not in {"npx", "uvx"}:
            errors.append({"surface": "mcp", "server": name, "reason": "unsupported_launcher_not_audited",
                           "coverage_unavailable": True})
            continue
        for ref in _mcp_package_refs(argv, launcher):
            match = (_NPX_REF if launcher == "npx" else _UVX_REF).fullmatch(ref)
            version = match.group(2) if match else ""
            exact = bool(_NPM_EXACT.fullmatch(version)) if launcher == "npx" else _version(version) is not None
            if match is None or not exact:
                errors.append({"surface": "mcp", "server": name, "reason": "unpinned_package_not_audited",
                               "coverage_unavailable": True})
                continue
            package = match.group(1) if launcher == "npx" else canonicalize_name(match.group(1))
            components.append(Component("mcp", package, match.group(2), name,
                                        "npm" if launcher == "npx" else "PyPI"))
    components.sort(key=lambda c: (c.ecosystem, c.name, c.version, c.origin))
    return components, errors


# ── advisories ─────────────────────────────────────────────────────────────────


def _package_matches(affected: Any, package: str, ecosystem: str = "PyPI") -> bool:
    if not isinstance(affected, dict):
        return False
    info = affected.get("package") or {}
    name, recorded_ecosystem = info.get("name"), info.get("ecosystem")
    if not isinstance(name, str) or recorded_ecosystem not in (None, ecosystem):
        return False
    return (canonicalize_name(name) == canonicalize_name(package)
            if ecosystem == "PyPI" else name.lower() == package.lower())


def _level(value: Any) -> str | None:
    return _LEVELS.get(value.strip().lower()) if isinstance(value, str) else None


def normalize_severity(vuln: dict[str, Any], package: str, ecosystem: str = "PyPI") -> tuple[str, str]:
    """``(level, source)`` — a stated level or ``unknown``; a CVSS vector alone is not a level."""
    level = _level((vuln.get("database_specific") or {}).get("severity"))
    if level:
        return level, "database_specific"
    for affected in vuln.get("affected") or []:
        if _package_matches(affected, package, ecosystem):
            level = _level((affected.get("database_specific") or {}).get("severity"))
            if level:
                return level, "affected"
    return "unknown", "none"


def _version(text: Any) -> Version | None:
    try:
        return Version(text) if isinstance(text, str) and text else None
    except InvalidVersion:
        return None


def fixed_in(vuln: dict[str, Any], package: str, version: str | None = None,
             ecosystem: str = "PyPI") -> str | None:
    """The fix that applies to *version* of *package*, or None when no fix is listed.

    OSV lists one ``[introduced, fixed)`` pair per maintained branch. The pair whose
    range contains the installed version names the upgrade that actually applies;
    the first listed fix is only a fallback (when no version is given, or none of
    the ranges can be compared) — otherwise a box on 3.0.0 would be told to "fix"
    by moving to 2.31.1.
    """
    pairs: list[tuple[str | None, str]] = []
    for affected in vuln.get("affected") or []:
        if not _package_matches(affected, package, ecosystem):
            continue
        for range_ in affected.get("ranges") or []:
            if not isinstance(range_, dict) or range_.get("type") not in ("ECOSYSTEM", "SEMVER"):
                continue
            introduced: str | None = None
            for event in range_.get("events") or []:
                if not isinstance(event, dict):
                    continue
                if isinstance(event.get("introduced"), str):
                    introduced = event["introduced"]
                fixed = event.get("fixed")
                if isinstance(fixed, str) and fixed:
                    pairs.append((introduced, fixed))
                    introduced = None
    if not pairs:
        return None
    installed = _version(version)
    if installed is not None:
        for introduced, fixed in pairs:
            low = Version("0") if introduced in (None, "0") else _version(introduced)
            high = _version(fixed)
            if low is not None and high is not None and low <= installed < high:
                return fixed
    return pairs[0][1]


def _fails(threshold: str, level: str) -> bool:
    return level == "unknown" or _RANK[level] <= _RANK[threshold]


@dataclass(frozen=True)
class Finding:
    surface: str
    name: str
    version: str
    origin: str
    id: str
    aliases: tuple[str, ...]
    severity: str
    severity_source: str
    fixed_in: str | None
    summary: str
    ecosystem: str = "PyPI"

    def to_dict(self) -> dict[str, Any]:
        return {"surface": self.surface, "name": self.name, "version": self.version, "origin": self.origin,
                "id": self.id, "aliases": list(self.aliases), "severity": self.severity,
                "severity_source": self.severity_source, "fixed_in": self.fixed_in,
                "summary": self.summary, "ecosystem": self.ecosystem}


def _sort_key(finding: Finding) -> tuple:
    return (_RANK[finding.severity], finding.name, finding.version, finding.id, finding.surface)


def _raw_finding(component: Component, vuln_id: str, vuln: dict[str, Any] | None) -> Finding:
    if vuln is None:
        return Finding(component.surface, component.name, component.version, component.origin,
                       vuln_id, (), "unknown", "detail_unavailable", None,
                       "advisory detail could not be fetched; treated as unrated", component.ecosystem)
    level, source = normalize_severity(vuln, component.name, component.ecosystem)
    aliases = tuple(a for a in (vuln.get("aliases") or []) if isinstance(a, str) and a != vuln_id)
    summary = vuln.get("summary") if isinstance(vuln.get("summary"), str) else ""
    return Finding(component.surface, component.name, component.version, component.origin,
                   vuln_id, aliases, level, source,
                   fixed_in(vuln, component.name, component.version, component.ecosystem),
                   summary, component.ecosystem)


#: Which id speaks for a merged group when severities tie. GHSA entries carry the stated
#: level; PYSEC mirrors usually carry only a CVSS vector, which this module does not score.
_ID_PREFERENCE = {"GHSA": 0, "CVE": 1, "PYSEC": 2}


def _merge_aliased(findings: list[Finding]) -> list[Finding]:
    """Collapse advisories that alias each other into one finding per real issue.

    OSV lists the same CVE under a GHSA id *and* a PYSEC mirror, and only the GHSA
    entry states a severity. Left unmerged, the mirror is an ``unknown`` that fails
    every threshold — so a box with one moderate advisory would fail ``--fail-on high``
    on its own duplicate. Members sharing any id or alias form one group; the group
    reports the best *stated* severity, keeps every id, and takes the first fix
    listed. A member whose detail could not be fetched merges through its sibling's
    alias list, and is only ``unknown`` when nothing in the group is rated.
    """
    if len(findings) < 2:
        return list(findings)
    parent = list(range(len(findings)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for index, finding in enumerate(findings):
        for name in (finding.id, *finding.aliases):
            key = name.lower()
            if key in owner:
                parent[find(index)] = find(owner[key])
            else:
                owner[key] = index
    groups: dict[int, list[Finding]] = {}
    for index, finding in enumerate(findings):
        groups.setdefault(find(index), []).append(finding)

    merged: list[Finding] = []
    for members in groups.values():
        members.sort(key=lambda f: (_RANK[f.severity], _ID_PREFERENCE.get(f.id.split("-", 1)[0], 9), f.id))
        head = members[0]
        spellings: dict[str, str] = {}
        for f in members:
            for n in (f.id, *f.aliases):
                spellings.setdefault(n.lower(), n)
        names = sorted(n for key, n in spellings.items() if key != head.id.lower())
        fixed = next((f.fixed_in for f in members if f.fixed_in), None)
        summary = next((f.summary for f in members if f.summary), "")
        merged.append(Finding(head.surface, head.name, head.version, head.origin, head.id, tuple(names),
                              head.severity, head.severity_source, fixed, summary, head.ecosystem))
    return merged


# ── the report ─────────────────────────────────────────────────────────────────


@dataclass
class Report:
    fail_on: str
    components: list[Component]
    findings: list[Finding] = field(default_factory=list)
    ignored: list[Finding] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    queried: int = 0
    unavailable: str | None = None
    status: str = "clean"        # clean | findings | unavailable | offline
    database: str = DEFAULT_OSV_URL
    skipped: dict[str, bool] = field(default_factory=dict)

    def failing(self) -> list[Finding]:
        return [f for f in self.findings if _fails(self.fail_on, f.severity)]

    def surfaces(self) -> dict[str, dict[str, Any]]:
        mcp_count = sum(c.surface == "mcp" for c in self.components)
        return {
            "installed": {"count": sum(c.surface == "installed" for c in self.components)},
            "extension": {"count": sum(c.surface == "extension" for c in self.components)},
            "mcp": {"count": mcp_count, "audited": bool(mcp_count),
                    "reason": "only exact pinned npx/uvx package refs are audited"}
                   if mcp_count else mcp_surface(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "fail_on": self.fail_on, "database": self.database,
            "skipped": dict(self.skipped),
            "queried": self.queried, "unavailable": self.unavailable,
            "surfaces": self.surfaces(),
            "components": [c.to_dict() for c in self.components],
            "errors": list(self.errors),
            "findings": [f.to_dict() for f in self.findings],
            "ignored": [f.to_dict() for f in self.ignored],
        }


class OSVClient(Protocol):
    def query_batch(self, queries: list[dict[str, Any]]) -> list[list[str]]: ...
    def vulnerability(self, vuln_id: str) -> dict[str, Any]: ...


def audit(
    components: Iterable[Component],
    client: OSVClient,
    *,
    fail_on: str = "low",
    ignore: Iterable[str] = (),
    batch_size: int = BATCH_LIMIT,
    errors: Iterable[dict[str, Any]] | None = None,
    database: str = DEFAULT_OSV_URL,
    skipped: dict[str, bool] | None = None,
) -> Report:
    """Ask the database about every distinct name+version pair and rank what comes back.

    *errors* are the enumeration rows that could not be read (an installed distribution
    with undecodable metadata, an unreadable descriptor); they ride along in the report
    so a "clean" verdict is never read as covering something that was skipped.
    """
    if fail_on not in _RANK or fail_on == "unknown":
        raise ValueError(f"fail_on must be one of {SEVERITIES[:-1]}, not {fail_on!r}")
    report = Report(fail_on=fail_on, components=list(components),
                    errors=list(errors or []), database=database, skipped=dict(skipped or {}))
    keys = sorted({(c.ecosystem, c.name, c.version) for c in report.components})
    queries = [{"package": {"name": name, "ecosystem": ecosystem}, "version": version}
               for ecosystem, name, version in keys]
    report.queried = len(queries)

    ids_per_key: list[list[str]] = []
    try:
        for start in range(0, len(queries), max(1, batch_size)):
            ids_per_key.extend(client.query_batch(queries[start:start + batch_size]))
        if len(ids_per_key) != len(keys):
            raise OSVUnavailable("malformed batch response: result count does not match the queries")
    except OSVUnavailable as exc:
        report.unavailable = str(exc) or "unavailable"
        report.status = "unavailable"
        return report

    hits = dict(zip(keys, ids_per_key, strict=True))
    details: dict[str, dict[str, Any] | None] = {}
    for vuln_id in sorted({v for ids in ids_per_key for v in ids}):
        try:
            details[vuln_id] = client.vulnerability(vuln_id)
        except OSVUnavailable:
            details[vuln_id] = None

    ignored_ids = {token.strip().lower() for token in ignore if isinstance(token, str) and token.strip()}
    for component in report.components:
        raw = [
            _raw_finding(component, vuln_id, details.get(vuln_id))
            for vuln_id in hits.get((component.ecosystem, component.name, component.version), [])
        ]
        for finding in _merge_aliased(raw):
            names = {finding.id.lower(), *(a.lower() for a in finding.aliases)}
            (report.ignored if names & ignored_ids else report.findings).append(finding)

    report.findings.sort(key=_sort_key)
    report.ignored.sort(key=_sort_key)
    report.status = ("unavailable" if any(error.get("coverage_unavailable") for error in report.errors)
                     else "findings" if report.failing() else "clean")
    if report.status == "unavailable":
        report.unavailable = "dependency inventory incomplete"
    return report


def offline_report(components: Iterable[Component],
                   errors: Iterable[dict[str, Any]] | None = None,
                   skipped: dict[str, bool] | None = None) -> Report:
    """Enumeration only. No database, no claim."""
    return Report(fail_on="low", components=list(components), errors=list(errors or []),
                  queried=0, status="offline", skipped=dict(skipped or {}))


# ── rendering ──────────────────────────────────────────────────────────────────


def _finding_line(finding: Finding, *, prefix: str = "") -> str:
    """One terminal line per finding. Every field that came from the database is cleaned:
    a summary carrying ESC or a newline would otherwise be able to repaint the screen or
    forge a second finding row."""
    aliases = f" ({', '.join(_clean(a) for a in finding.aliases)})" if finding.aliases else ""
    fix = f"fixed in {_clean(finding.fixed_in)}" if finding.fixed_in else "no fix listed"
    summary = f"  — {_clean(finding.summary, SUMMARY_WIDTH)}" if finding.summary else ""
    return (f"{prefix}{_clean(finding.severity).upper():<9}{_clean(finding.name)} {_clean(finding.version)}  "
            f"{_clean(finding.id)}{aliases}  {fix}{summary}")


def _error_line(error: dict[str, Any]) -> str:
    reason = _clean(error.get("reason", "unreadable"), 120)
    if error.get("surface") == "installed":
        return f"installed distribution {_safe_token(error.get('location'))}: {reason} — skipped, not audited"
    if error.get("surface") == "mcp":
        return f"MCP {_safe_token(error.get('server'), 'configuration')}: {reason}"
    return f"descriptor {_clean(error.get('index', '?'))}: {reason}"


def render(report: Report) -> str:
    surfaces = report.surfaces()
    total = len(report.components)
    database = _clean(report.database, 200)
    lines = [
        f"nerva security audit — {surfaces['installed']['count']} installed · "
        f"{surfaces['extension']['count']} declared extension pin(s) · {surfaces['mcp']['count']} MCP pin(s)",
    ]
    selected_skips = [name for name, enabled in report.skipped.items() if enabled]
    if selected_skips:
        lines.append("skipped: " + ", ".join(selected_skips))
    lines.extend(_error_line(error) for error in report.errors)
    if report.status == "offline":
        lines.append(f"no vulnerability database consulted (--offline): nothing is claimed about these {total} components.")
        return "\n".join(lines)
    if report.status == "unavailable" and report.unavailable != "dependency inventory incomplete":
        lines.append(f"could not consult {database}: {_clean(report.unavailable, 240)}. "
                     f"Nothing is claimed about these {total} components.")
        return "\n".join(lines)
    if report.status == "unavailable":
        lines.append("dependency inventory incomplete: coverage incomplete; known findings from selected pins follow")
    lines.append(f"consulted {database} ({report.queried} name+version pairs) · fail-on: {report.fail_on}")
    for finding in report.findings:
        lines.append(_finding_line(finding))
    for finding in report.ignored:
        lines.append(_finding_line(finding, prefix="ignored  "))
    failing = len(report.failing())
    below = len(report.findings) - failing
    lines.append(f"{failing} finding(s) at or above {report.fail_on}; {below} below; {len(report.ignored)} ignored"
                 + (" — clean at this threshold" if report.status == "clean" else ""))
    return "\n".join(lines)


# ── the real client ────────────────────────────────────────────────────────────


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url


def _https_only(url: str) -> str:
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("the vulnerability database must be an https URL (package versions leave the machine)")
    return url


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise OSVUnavailable("the audit cannot run inside a running event loop")


class OSVHttpClient:
    """OSV.dev over the governed plugin client: pinned resolution, owner TLS anchors, breaker."""

    def __init__(self, base_url: str = DEFAULT_OSV_URL, *, plugin_name: str = "dep_audit",
                 authorize_egress=None, resolver=None, transport_factory=None):
        self.base_url = _https_only(base_url).rstrip("/")
        self.plugin_name = plugin_name
        self.authorize_egress = authorize_egress
        self.resolver = resolver
        self.transport_factory = transport_factory

    #: Follow-up pages per batch before the answer is declared incomplete rather than trusted.
    MAX_PAGES = 20

    def query_batch(self, queries: list[dict[str, Any]]) -> list[list[str]]:
        """Ids per query, following ``next_page_token`` until every query is exhausted.

        OSV paginates when one query exceeds 1,000 advisories or a batch 3,000 in total.
        A page left unread would be reported as consulted — and possibly clean — so the
        pages are followed, and a batch still open after :attr:`MAX_PAGES` is
        ``unavailable``, not an answer.
        """
        pending = [dict(query) for query in queries]
        ids: list[list[str]] = [[] for _ in queries]
        open_ = list(range(len(queries)))
        for _page in range(self.MAX_PAGES):
            body = _run(self._request("POST", "/v1/querybatch",
                                      json={"queries": [pending[i] for i in open_]}))
            results = body.get("results") if isinstance(body, dict) else None
            if not isinstance(results, list) or len(results) != len(open_):
                raise OSVUnavailable("malformed batch response: result count does not match the queries")
            still_open: list[int] = []
            for index, result in zip(open_, results, strict=True):
                if not isinstance(result, dict):
                    continue
                ids[index].extend(v["id"] for v in (result.get("vulns") or [])
                                  if isinstance(v, dict) and isinstance(v.get("id"), str))
                token = result.get("next_page_token")
                if isinstance(token, str) and token:
                    pending[index] = {**pending[index], "page_token": token}
                    still_open.append(index)
            if not still_open:
                return ids
            open_ = still_open
        raise OSVUnavailable(f"batch results still paginated after {self.MAX_PAGES} pages; not consulted in full")

    def vulnerability(self, vuln_id: str) -> dict[str, Any]:
        body = _run(self._request("GET", f"/v1/vulns/{quote(vuln_id, safe='')}"))
        if not isinstance(body, dict) or body.get("id") != vuln_id:
            raise OSVUnavailable(f"malformed advisory body for {vuln_id}")
        return body

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        from agents.core.http_client import PluginHTTPClient, RequiredEgressHTTPClient

        authorize = self.authorize_egress
        if authorize is None:
            client = PluginHTTPClient(plugin_name=self.plugin_name,
                                      resolver=self.resolver, transport_factory=self.transport_factory)
        else:
            client = RequiredEgressHTTPClient(
                plugin_name=self.plugin_name, authorize_egress=authorize,
                resolver=self.resolver, transport_factory=self.transport_factory,
            )
        try:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
            if response.status_code != 200:
                raise OSVUnavailable(f"HTTP {response.status_code} from {host_of(self.base_url)}")
            return response.json()
        except OSVUnavailable:
            raise
        except Exception as exc:  # egress refusals, transport and decode errors alike: not consulted
            raise OSVUnavailable(f"{type(exc).__name__}: {exc}"[:240]) from None
        finally:
            await client.close()


def default_client(base_url: str = DEFAULT_OSV_URL, *, authorize_egress=None) -> OSVClient:
    """The client the CLI uses; tests replace this attribute."""
    return OSVHttpClient(base_url, authorize_egress=authorize_egress)
