"""dep_audit.py — H022: audit installed dependencies for known vulnerabilities.

The SBOM (``scripts/gen_sbom.py``) has been generated for months and checked against
nothing — ``rg -il 'osv|vulnerab'`` over ``agents/`` and ``scripts/`` was empty. CI runs
``pip-audit`` over the *lockfile*, which is the right gate for a release and the wrong
question for an owner: they want to know whether the interpreter that is actually
running Nerva, on this box, carries something with a public advisory. This module
answers that, from three surfaces it names explicitly:

* ``installed`` — every distribution ``importlib.metadata`` can see in this interpreter;
* ``extension`` — the exact Python pins an extension descriptor declares
  (``requires.python`` in ``agents/core/extensions/manifest.py``), for descriptors the
  caller names — the acquired-package catalog needs the running hub and is not read here;
* ``mcp`` — on Nerva an HTTP transport with no installed server packages. Reported as an
  empty surface *with that reason*, never omitted, so a reader is not left wondering.

Two decisions are load-bearing and each has a test:

* **An advisory whose severity OSV does not state is ``unknown`` and fails every
  ``fail_on`` threshold.** A CVSS vector is not turned into a level here — computing a
  score this module cannot vouch for would let an unrated advisory pass a bar it never
  cleared. The same holds for an advisory whose detail could not be fetched.
* **A database that could not be reached is ``unavailable``, never ``clean``.** The
  report says nothing is claimed, and the CLI maps it to its own exit code so a script
  cannot mistake "we could not look" for either answer.

Egress goes through :class:`agents.core.http_client.PluginHTTPClient` — pinned
resolution, the owner's TLS anchors, a circuit breaker — and only package name+version
pairs are sent. The client is injected, so every test here runs offline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import metadata as _metadata
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from packaging.utils import canonicalize_name

DEFAULT_OSV_URL = "https://api.osv.dev"
#: OSV rejects batches above this; https://google.github.io/osv.dev/post-v1-querybatch/
BATCH_LIMIT = 1000
SEVERITIES: tuple[str, ...] = ("critical", "high", "moderate", "low", "unknown")
_RANK = {level: index for index, level in enumerate(SEVERITIES)}
_LEVELS = {"critical": "critical", "high": "high", "moderate": "moderate",
           "medium": "moderate", "low": "low"}
MCP_REASON = ("Nerva reaches MCP servers over an HTTP transport and installs no npx/uvx "
              "server packages, so there is nothing to audit on this surface.")


class OSVUnavailable(RuntimeError):
    """The database could not be consulted. Nothing about the components is claimed."""


# ── components ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Component:
    surface: str          # installed | extension
    name: str             # canonical PyPI name
    version: str
    origin: str           # importlib.metadata, or the extension id that declared the pin

    def to_dict(self) -> dict[str, str]:
        return {"surface": self.surface, "name": self.name, "version": self.version, "origin": self.origin}


def enumerate_installed(distributions: Iterable[Any] | None = None) -> list[Component]:
    """Every distribution this interpreter can see, canonicalised and de-duplicated."""
    seen: dict[tuple[str, str], Component] = {}
    for dist in (distributions if distributions is not None else _metadata.distributions()):
        meta = getattr(dist, "metadata", None)
        raw_name = meta.get("Name") if meta is not None and hasattr(meta, "get") else None
        version = getattr(dist, "version", None)
        if not isinstance(raw_name, str) or not raw_name.strip() or not isinstance(version, str) or not version:
            continue
        name = canonicalize_name(raw_name)
        seen.setdefault((name, version), Component("installed", name, version, "importlib.metadata"))
    return [seen[key] for key in sorted(seen)]


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
            errors.append({"index": index, "reason": str(exc)})
            continue
        except Exception:
            errors.append({"index": index, "reason": "manifest_unreadable"})
            continue
        for name, version in manifest.python_requires:
            components.append(Component("extension", canonicalize_name(name), version, manifest.id))
    components.sort(key=lambda c: (c.name, c.version, c.origin))
    return components, errors


def mcp_surface() -> dict[str, Any]:
    return {"count": 0, "reason": MCP_REASON}


# ── advisories ─────────────────────────────────────────────────────────────────


def _package_matches(affected: Any, package: str) -> bool:
    if not isinstance(affected, dict):
        return False
    info = affected.get("package") or {}
    name, ecosystem = info.get("name"), info.get("ecosystem")
    if not isinstance(name, str) or ecosystem not in (None, "PyPI"):
        return False
    return canonicalize_name(name) == canonicalize_name(package)


def _level(value: Any) -> str | None:
    return _LEVELS.get(value.strip().lower()) if isinstance(value, str) else None


def normalize_severity(vuln: dict[str, Any], package: str) -> tuple[str, str]:
    """``(level, source)`` — a stated level or ``unknown``; a CVSS vector alone is not a level."""
    level = _level((vuln.get("database_specific") or {}).get("severity"))
    if level:
        return level, "database_specific"
    for affected in vuln.get("affected") or []:
        if _package_matches(affected, package):
            level = _level((affected.get("database_specific") or {}).get("severity"))
            if level:
                return level, "affected"
    return "unknown", "none"


def fixed_in(vuln: dict[str, Any], package: str) -> str | None:
    """The first ``fixed`` version OSV lists for *package*, or None when no fix is listed."""
    for affected in vuln.get("affected") or []:
        if not _package_matches(affected, package):
            continue
        for range_ in affected.get("ranges") or []:
            if not isinstance(range_, dict) or range_.get("type") not in ("ECOSYSTEM", "SEMVER"):
                continue
            for event in range_.get("events") or []:
                fixed = event.get("fixed") if isinstance(event, dict) else None
                if isinstance(fixed, str) and fixed:
                    return fixed
    return None


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

    def to_dict(self) -> dict[str, Any]:
        return {"surface": self.surface, "name": self.name, "version": self.version, "origin": self.origin,
                "id": self.id, "aliases": list(self.aliases), "severity": self.severity,
                "severity_source": self.severity_source, "fixed_in": self.fixed_in, "summary": self.summary}


def _sort_key(finding: Finding) -> tuple:
    return (_RANK[finding.severity], finding.name, finding.version, finding.id, finding.surface)


def _raw_finding(component: Component, vuln_id: str, vuln: dict[str, Any] | None) -> Finding:
    if vuln is None:
        return Finding(component.surface, component.name, component.version, component.origin,
                       vuln_id, (), "unknown", "detail_unavailable", None,
                       "advisory detail could not be fetched; treated as unrated")
    level, source = normalize_severity(vuln, component.name)
    aliases = tuple(a for a in (vuln.get("aliases") or []) if isinstance(a, str) and a != vuln_id)
    summary = vuln.get("summary") if isinstance(vuln.get("summary"), str) else ""
    return Finding(component.surface, component.name, component.version, component.origin,
                   vuln_id, aliases, level, source, fixed_in(vuln, component.name), summary)


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
        names = sorted({n for f in members for n in (f.id, *f.aliases)} - {head.id})
        fixed = next((f.fixed_in for f in members if f.fixed_in), None)
        summary = next((f.summary for f in members if f.summary), "")
        merged.append(Finding(head.surface, head.name, head.version, head.origin, head.id, tuple(names),
                              head.severity, head.severity_source, fixed, summary))
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

    def failing(self) -> list[Finding]:
        return [f for f in self.findings if _fails(self.fail_on, f.severity)]

    def surfaces(self) -> dict[str, dict[str, Any]]:
        return {
            "installed": {"count": sum(c.surface == "installed" for c in self.components)},
            "extension": {"count": sum(c.surface == "extension" for c in self.components)},
            "mcp": mcp_surface(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "fail_on": self.fail_on, "database": self.database,
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
    extension_errors: Iterable[dict[str, Any]] | None = None,
    database: str = DEFAULT_OSV_URL,
) -> Report:
    """Ask the database about every distinct name+version pair and rank what comes back."""
    if fail_on not in _RANK or fail_on == "unknown":
        raise ValueError(f"fail_on must be one of {SEVERITIES[:-1]}, not {fail_on!r}")
    report = Report(fail_on=fail_on, components=list(components),
                    errors=list(extension_errors or []), database=database)
    keys = sorted({(c.name, c.version) for c in report.components})
    queries = [{"package": {"name": name, "ecosystem": "PyPI"}, "version": version} for name, version in keys]
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
            for vuln_id in hits.get((component.name, component.version), [])
        ]
        for finding in _merge_aliased(raw):
            names = {finding.id.lower(), *(a.lower() for a in finding.aliases)}
            (report.ignored if names & ignored_ids else report.findings).append(finding)

    report.findings.sort(key=_sort_key)
    report.ignored.sort(key=_sort_key)
    report.status = "findings" if report.failing() else "clean"
    return report


def offline_report(components: Iterable[Component],
                   extension_errors: Iterable[dict[str, Any]] | None = None) -> Report:
    """Enumeration only. No database, no claim."""
    return Report(fail_on="low", components=list(components), errors=list(extension_errors or []),
                  queried=0, status="offline")


# ── rendering ──────────────────────────────────────────────────────────────────


def _finding_line(finding: Finding, *, prefix: str = "") -> str:
    aliases = f" ({', '.join(finding.aliases)})" if finding.aliases else ""
    fix = f"fixed in {finding.fixed_in}" if finding.fixed_in else "no fix listed"
    summary = f"  — {finding.summary}" if finding.summary else ""
    return f"{prefix}{finding.severity.upper():<9}{finding.name} {finding.version}  {finding.id}{aliases}  {fix}{summary}"


def render(report: Report) -> str:
    surfaces = report.surfaces()
    total = len(report.components)
    lines = [
        f"nerva security audit — {surfaces['installed']['count']} installed · "
        f"{surfaces['extension']['count']} extension pin(s) · MCP: 0 (HTTP transport, no installed server packages)",
    ]
    for error in report.errors:
        lines.append(f"descriptor {error.get('index', '?')}: {error.get('reason', 'unreadable')}")
    if report.status == "offline":
        lines.append(f"no vulnerability database consulted (--offline): nothing is claimed about these {total} components.")
        return "\n".join(lines)
    if report.status == "unavailable":
        lines.append(f"could not consult {report.database}: {report.unavailable}. "
                     f"Nothing is claimed about these {total} components.")
        return "\n".join(lines)
    lines.append(f"consulted {report.database} ({report.queried} name+version pairs) · fail-on: {report.fail_on}")
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

    def __init__(self, base_url: str = DEFAULT_OSV_URL, *, plugin_name: str = "dep_audit"):
        self.base_url = _https_only(base_url).rstrip("/")
        self.plugin_name = plugin_name

    def query_batch(self, queries: list[dict[str, Any]]) -> list[list[str]]:
        body = _run(self._request("POST", "/v1/querybatch", json={"queries": list(queries)}))
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list) or len(results) != len(queries):
            raise OSVUnavailable("malformed batch response: result count does not match the queries")
        return [
            [v["id"] for v in ((r.get("vulns") or []) if isinstance(r, dict) else [])
             if isinstance(v, dict) and isinstance(v.get("id"), str)]
            for r in results
        ]

    def vulnerability(self, vuln_id: str) -> dict[str, Any]:
        body = _run(self._request("GET", f"/v1/vulns/{quote(vuln_id, safe='')}"))
        if not isinstance(body, dict) or body.get("id") != vuln_id:
            raise OSVUnavailable(f"malformed advisory body for {vuln_id}")
        return body

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        from agents.core.http_client import PluginHTTPClient

        client = PluginHTTPClient(plugin_name=self.plugin_name)
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


def default_client(base_url: str = DEFAULT_OSV_URL) -> OSVClient:
    """The client the CLI uses; tests replace this attribute."""
    return OSVHttpClient(base_url)
