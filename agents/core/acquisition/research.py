"""Governed research: consent, bounded fetch, taint, grounding, encrypted retention."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import json
import os
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from agents.core.grounded_plan import ground_plan
from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError
from agents.core.security.quarantine import detect_injection
from agents.core.security.scanner import PIIScanner, SecretScanner

from .models import CapabilityRequest
from .store import CapabilityStoreError


class ResearchError(RuntimeError):
    pass


class _PinnedResearchResponse:
    """Own an open PluginHTTPClient stream until the bounded reader closes it."""

    def __init__(self, *, response: object, context: object, circuit_breaker: object) -> None:
        self._response = response
        self._context = context
        self._circuit_breaker = circuit_breaker
        self._closed = False
        status = int(getattr(response, "status_code", 0))
        headers = getattr(response, "headers", {})
        self.redirect_url = headers.get("location") if 300 <= status < 400 else None

    async def aiter_bytes(self):
        async for chunk in self._response.aiter_bytes():
            yield chunk

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._context.__aexit__(None, None, None)


class WebSearchResearchBackend:
    """Production bridge to WebSearchPlugin and its governed PluginHTTPClient.

    Search is deliberately SearXNG-only. Page fetches first pass through the
    plugin egress/kernel guard and then dial the already validated IP, preserving
    the original Host header and TLS SNI. This closes the DNS-rebinding window
    between validation and connect while keeping response streaming bounded by
    :class:`GovernedResearch`.
    """

    def __init__(
        self,
        *,
        plugin: object | None = None,
        searxng_url: str = "",
    ) -> None:
        if plugin is None:
            if not searxng_url:
                raise ResearchError("configured SearXNG backend required")
            from agents.core.plugins.websearch import WebSearchPlugin

            plugin = WebSearchPlugin(tavily_api_key="", searxng_url=searxng_url)
        if not str(getattr(plugin, "searxng_url", "")).strip():
            raise ResearchError("configured SearXNG backend required")
        if str(getattr(plugin, "tavily_api_key", "")).strip():
            raise ResearchError("cloud search backend is forbidden for local research")
        client = getattr(plugin, "_client", None)
        if client is None:
            raise ResearchError("PluginHTTPClient unavailable")
        self.plugin = plugin
        self.http_client = client

    async def search(self, query: str, max_results: int) -> list[dict]:
        results = await self.plugin.search(query, max_results=max_results)
        if not isinstance(results, list):
            raise ResearchError("SearXNG returned invalid results")
        return results

    async def fetch(self, url: str, pinned_ip: str) -> _PinnedResearchResponse:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host or parsed.scheme not in {"http", "https"}:
            raise ResearchError("SSRF guard refused unsupported URL")
        try:
            ipaddress.ip_address(pinned_ip)
        except ValueError as exc:
            raise ResearchError("SSRF guard received invalid pinned address") from exc

        client = self.http_client
        try:
            context = client.stream(
                "GET",
                url,
                headers={"User-Agent": "Jarvis-GovernedResearch/1"},
                follow_redirects=False,
            )
            response = await context.__aenter__()
            if int(getattr(response, "status_code", 0)) >= 400:
                try:
                    response.raise_for_status()
                finally:
                    await context.__aexit__(None, None, None)
            return _PinnedResearchResponse(
                response=response,
                context=context,
                circuit_breaker=client.circuit_breaker,
            )
        except Exception:
            raise


@dataclass(frozen=True, slots=True)
class ResearchSource:
    source_id: str
    url: str
    title: str
    extract: str
    content_hash: str
    tainted: bool = True
    taint_source: str = "websearch"
    quarantined: bool = False
    injection_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchRecord:
    research_id: str
    request_id: str
    backend: str
    sources: tuple[ResearchSource, ...]
    plan: dict
    tainted: bool
    created_at: float
    expires_at: float


class ResearchStore:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        retention_days: int = 7,
        max_records: int = 1_000,
        max_bytes: int = 32 * 1024 * 1024,
        max_source_extract_bytes: int = 16 * 1024,
        max_plan_bytes: int = 128 * 1024,
        event_sink=None,
    ) -> None:
        self.root = Path(root) if root is not None else data_path("acquisition")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "research.enc"
        self._cipher = SecretStore(self.root / "research-cipher.json")
        self._clock = clock
        self._retention = max(1, int(retention_days)) * 86_400
        self._max_records = max(1, int(max_records))
        self._max_bytes = max(1024, int(max_bytes))
        self._max_source_extract_bytes = max(16, int(max_source_extract_bytes))
        self._max_plan_bytes = max(64, int(max_plan_bytes))
        self._lock = threading.RLock()
        self._records: list[ResearchRecord] | None = None
        self._event_sink = event_sink

    def put(self, record: ResearchRecord) -> ResearchRecord:
        with self._lock:
            self._validate_record(record)
            now = float(self._clock())
            records = [
                row
                for row in self._load()
                if row.request_id != record.request_id and row.expires_at > now
            ]
            if len(records) >= self._max_records:
                raise CapabilityStoreError("research store capacity reached")
            self._commit([*records, record])
            if self._event_sink is not None:
                self._event_sink(
                    "research.completed",
                    actor="governed-research",
                    request_id=record.request_id,
                    status="grounded",
                    details={
                        "research_id": record.research_id,
                        "backend": record.backend,
                        "source_hashes": [source.content_hash for source in record.sources],
                        "sources": len(record.sources),
                    },
                )
        return record

    def put_raw(self, *, request_id: str, backend: str, sources: list[dict], plan: dict) -> ResearchRecord:
        now = float(self._clock())
        normalized = []
        for source in sources:
            extract = str(source.get("extract", ""))[:16_384]
            normalized.append(
                ResearchSource(
                    source_id=str(source.get("source_id", uuid.uuid4().hex[:16])),
                    url=str(source.get("url", ""))[:2048],
                    title=str(source.get("title", ""))[:512],
                    extract=extract,
                    content_hash=hashlib.sha256(extract.encode()).hexdigest(),
                )
            )
        return self.put(
            ResearchRecord(
                research_id=uuid.uuid4().hex,
                request_id=str(request_id)[:64],
                backend=str(backend)[:64],
                sources=tuple(normalized),
                plan=dict(plan),
                tainted=True,
                created_at=now,
                expires_at=now + self._retention,
            )
        )

    def get(self, request_id: str) -> ResearchRecord | None:
        with self._lock:
            return next((row for row in self._load() if row.request_id == request_id), None)

    def purge(self, *, request_id: str | None = None, now: float | None = None) -> int:
        reference = float(self._clock() if now is None else now)
        with self._lock:
            records = self._load()
            kept = [
                row
                for row in records
                if not ((request_id is not None and row.request_id == request_id) or row.expires_at <= reference)
            ]
            removed = len(records) - len(kept)
            if removed:
                self._commit(kept)
            return removed

    def summary(self) -> dict[str, object]:
        with self._lock:
            records = self._load()
            return {
                "total": len(records),
                "requests": [
                    {
                        "request_id": row.request_id,
                        "backend": row.backend,
                        "sources": len(row.sources),
                        "expires_at": row.expires_at,
                    }
                    for row in records
                ],
            }

    def _load(self) -> list[ResearchRecord]:
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        if self.path.is_symlink():
            raise CapabilityStoreError("research store cannot be a symlink")
        try:
            payload = json.loads(self._cipher.decrypt_bytes(self.path.read_bytes()).decode("utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("records"), list):
                raise ValueError("invalid research schema")
            records = []
            for row in payload["records"]:
                sources = tuple(
                    ResearchSource(
                        source_id=str(source["source_id"]),
                        url=str(source["url"]),
                        title=str(source["title"]),
                        extract=str(source["extract"]),
                        content_hash=str(source["content_hash"]),
                        tainted=bool(source.get("tainted", True)),
                        taint_source=str(source.get("taint_source", "websearch")),
                        quarantined=bool(source.get("quarantined", False)),
                        injection_flags=tuple(str(flag) for flag in source.get("injection_flags", [])),
                    )
                    for source in row["sources"]
                )
                records.append(
                    ResearchRecord(
                        research_id=str(row["research_id"]),
                        request_id=str(row["request_id"]),
                        backend=str(row["backend"]),
                        sources=sources,
                        plan=dict(row["plan"]),
                        tainted=bool(row.get("tainted", True)),
                        created_at=float(row["created_at"]),
                        expires_at=float(row["expires_at"]),
                    )
                )
            if len(records) > self._max_records:
                raise ValueError("research count exceeds capacity")
            for record in records:
                self._validate_record(record)
        except (OSError, UnicodeError, json.JSONDecodeError, SecretStoreError, ValueError, KeyError) as exc:
            raise CapabilityStoreError("cannot decrypt or validate research store") from exc
        self._records = records
        return records

    def _validate_record(self, record: ResearchRecord) -> None:
        if any(
            len(source.extract.encode("utf-8")) > self._max_source_extract_bytes
            for source in record.sources
        ):
            raise CapabilityStoreError("research source extract capacity reached")
        plan_size = len(
            json.dumps(record.plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if plan_size > self._max_plan_bytes:
            raise CapabilityStoreError("research plan capacity reached")

    def _commit(self, records: list[ResearchRecord]) -> None:
        raw = json.dumps(
            {"schema": 1, "records": [asdict(record) for record in records]},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(raw) > self._max_bytes:
            raise CapabilityStoreError("research byte capacity reached")
        token = self._cipher.encrypt_bytes(raw)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".research-", delete=False) as handle:
                temporary = handle.name
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CapabilityStoreError("cannot atomically commit research") from exc
        finally:
            if temporary:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)
        self._records = records


class GovernedResearch:
    def __init__(
        self,
        *,
        enabled: bool = False,
        network_consent: bool = False,
        cloud_consent: bool = False,
        backend_name: str = "",
        search: Callable[[str, int], Awaitable[list[dict]]] | None = None,
        fetch: Callable[[str, str], Awaitable[object]] | None = None,
        draft: Callable[[str, list[dict]], object] | None = None,
        draft_route: str = "strict-local",
        resolve: Callable[[str], Iterable[str]] | None = None,
        allowed_domains: set[str] | None = None,
        store: ResearchStore | None = None,
        clock: Callable[[], float] = time.time,
        max_sources: int = 5,
        max_source_bytes: int = 64 * 1024,
        max_total_bytes: int = 256 * 1024,
        max_plan_bytes: int = 128 * 1024,
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        self.enabled = enabled
        self.network_consent = network_consent
        self.cloud_consent = cloud_consent
        self.backend_name = backend_name.strip().lower()
        self.search = search
        self.fetch = fetch
        self.draft = draft
        self.draft_route = draft_route
        self.resolve = resolve or self._system_resolve
        self.allowed_domains = {
            domain.strip().lower().lstrip(".") for domain in (allowed_domains or set()) if domain.strip()
        }
        self.store = store
        self.clock = clock
        self.max_sources = max(1, min(16, int(max_sources)))
        self.max_source_bytes = max(16, min(1024 * 1024, int(max_source_bytes)))
        self.max_total_bytes = max(self.max_source_bytes, int(max_total_bytes))
        self.max_plan_bytes = max(64, min(1024 * 1024, int(max_plan_bytes)))
        self.operation_timeout_seconds = max(0.001, min(300.0, float(operation_timeout_seconds)))
        self._secrets = SecretScanner()
        self._pii = PIIScanner()

    @classmethod
    def from_websearch(
        cls,
        *,
        searxng_url: str,
        enabled: bool,
        network_consent: bool,
        draft: Callable[[str, list[dict]], object],
        **kwargs,
    ) -> GovernedResearch:
        """Construct the production SearXNG/PluginHTTPClient research path."""
        backend = WebSearchResearchBackend(searxng_url=searxng_url)
        return cls(
            enabled=enabled,
            network_consent=network_consent,
            cloud_consent=False,
            backend_name="searxng",
            search=backend.search,
            fetch=backend.fetch,
            draft=draft,
            **kwargs,
        )

    async def run(self, request: CapabilityRequest) -> ResearchRecord:
        self._preflight()
        results = await self._await_bounded(
            self.search(request.goal, self.max_sources),
            operation="research search",
        )
        if not isinstance(results, list):
            raise ResearchError("search backend returned invalid results")
        sources: list[ResearchSource] = []
        total_bytes = 0
        for result in results[: self.max_sources]:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", ""))[:2048]
            title = self._pii.redact(self._secrets.redact(str(result.get("title", ""))))[:512]
            raw = await self._await_bounded(
                self._fetch_bounded(url),
                operation="research fetch",
            )
            total_bytes += len(raw)
            if total_bytes > self.max_total_bytes:
                raise ResearchError("aggregate research byte cap exceeded")
            content_hash = hashlib.sha256(raw).hexdigest()
            text = raw.decode("utf-8", errors="replace")
            flags = tuple(detect_injection(text))
            source_id = f"src-{content_hash[:16]}"
            if flags:
                sources.append(
                    ResearchSource(
                        source_id=source_id,
                        url=self._display_url(url),
                        title=title,
                        extract="",
                        content_hash=content_hash,
                        quarantined=True,
                        injection_flags=flags,
                    )
                )
                continue
            extract = self._pii.redact(self._secrets.redact(text))[:16_384]
            sources.append(
                ResearchSource(
                    source_id=source_id,
                    url=self._display_url(url),
                    title=title,
                    extract=extract,
                    content_hash=content_hash,
                )
            )

        usable = [source for source in sources if not source.quarantined and source.extract]
        if not usable:
            raise ResearchError("research produced no usable references")
        references = [
            {
                "id": source.source_id,
                "title": source.title,
                "url": source.url,
                "content_hash": source.content_hash,
                "tainted": True,
                "taint_source": source.taint_source,
            }
            for source in usable
        ]
        steps = self.draft(request.goal, references)
        if inspect.isawaitable(steps):
            steps = await self._await_bounded(steps, operation="research draft")
        if not isinstance(steps, list) or not steps:
            raise ResearchError("strict grounded plan is required")
        plan = ground_plan(request.goal, references, steps)
        if not plan["steps"] or not plan["fully_grounded"]:
            raise ResearchError("strict grounded plan is required")
        hashes = {source.source_id: source.content_hash for source in usable}
        for step in plan["steps"]:
            step["citations"] = [
                {"source_id": source_id, "content_hash": hashes[source_id]}
                for source_id in step["cites"]
            ]
        plan_size = len(
            json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if plan_size > self.max_plan_bytes:
            raise ResearchError("research plan byte cap exceeded")
        now = float(self.clock())
        record = ResearchRecord(
            research_id=uuid.uuid4().hex,
            request_id=request.request_id,
            backend=self.backend_name,
            sources=tuple(sources),
            plan=plan,
            tainted=True,
            created_at=now,
            expires_at=now + 7 * 86_400,
        )
        if self.store is not None:
            self.store.put(record)
        return record

    async def _await_bounded(self, awaitable: Awaitable[object], *, operation: str):
        try:
            return await asyncio.wait_for(awaitable, timeout=self.operation_timeout_seconds)
        except TimeoutError as exc:
            raise ResearchError(f"{operation} timed out") from exc

    def _display_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            raise ResearchError("source URL credentials are forbidden")
        display = parsed._replace(query="", fragment="").geturl()
        return self._pii.redact(self._secrets.redact(display))[:2048]

    def _preflight(self) -> None:
        if not self.enabled:
            raise ResearchError("research disabled")
        if not self.network_consent:
            raise ResearchError("explicit network consent required")
        if not self.backend_name:
            raise ResearchError("configured research backend required")
        if self.backend_name == "duckduckgo":
            raise ResearchError("duckduckgo implicit fallback is forbidden")
        if self.backend_name != "searxng" and not self.cloud_consent:
            raise ResearchError("cloud research consent required")
        if self.search is None or self.fetch is None:
            raise ResearchError("research backend unavailable")
        if self.draft is None or self.draft_route != "strict-local":
            raise ResearchError("strict-local research drafter required")

    async def _fetch_bounded(self, initial_url: str) -> bytes:
        current = initial_url
        for _hop in range(6):
            addresses = self._validate_url(current)
            response = await self.fetch(current, addresses[0])
            if response is None:
                raise ResearchError("research fetch unavailable")
            try:
                redirect = getattr(response, "redirect_url", None)
                if redirect:
                    current = urljoin(current, str(redirect))
                    continue
                chunks: list[bytes] = []
                received = 0
                async for chunk in response.aiter_bytes():
                    if not isinstance(chunk, bytes):
                        raise ResearchError("research fetch returned invalid bytes")
                    received += len(chunk)
                    if received > self.max_source_bytes:
                        raise ResearchError("research source byte cap exceeded")
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                close = getattr(response, "aclose", None)
                if callable(close):
                    await close()
        raise ResearchError("research redirect cap exceeded")

    def _validate_url(self, url: str) -> tuple[str, ...]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            raise ResearchError("SSRF guard refused unsupported URL")
        if not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
            raise ResearchError("SSRF guard refused non-allowlisted host")
        try:
            addresses = tuple(str(value) for value in self.resolve(host))
        except Exception as exc:
            raise ResearchError("SSRF guard could not resolve host") from exc
        if not addresses:
            raise ResearchError("SSRF guard could not resolve host")
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise ResearchError("SSRF guard received invalid address") from exc
            if not address.is_global:
                raise ResearchError("SSRF guard refused private or reserved address")
        return addresses

    @staticmethod
    def _system_resolve(host: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    entry[4][0]
                    for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                }
            )
        )
