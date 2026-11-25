"""H566 — a third-party author's extension, submitted by the owner, installed only on a card.

Until now the only way an extension package reached the signed store was the
acquisition loop's strict-local generator, so nobody but Nerva could write one. This
module is the author's path, and it is deliberately **the same pipeline, not a second
one**: there is no second store, signing key, sandbox or approval mechanism.

An author ships a directory (or an installed Python distribution that declares it under
the ``nerva.extensions`` entry point, :mod:`.distribution`) with three files::

    extension.json        the descriptor (manifest.parse_manifest)
    main.py               register() plus call/command/on_event for what it declares
    test_extension.py     the author's unittest module (must exercise and assert)

The owner submits it (``nerva extensions install DIR`` -> ``POST
/api/plugins/extensions/install``, admin). Then, in order, each step refusing on its own:

1. **static checks** — the generator's own AST rules (stdlib allowlist, no file,
   process, network, dynamic import or introspection), the secret/PII scanners, a real
   ``register`` and one handler per declared capability, a test that asserts;
2. **quarantine** — the bytes become an encrypted quarantine record whose package hash
   binds the source, the tests, the descriptor and the install version
   (``generator.authored_goal``);
3. **sandbox verification** — the acquisition profile's sealed container runs the
   author's tests, then a system-owned contract that ``register()`` returns exactly the
   declared surface, then the same contract with ``register`` mutated, which must fail;
4. **proposal** — ``PromotionBroker.propose`` with the verified receipt, crossing the
   ``skill.install`` kernel gate;
5. **the owner's card** — an ``extensions.install`` card at the irreversible tier
   (:mod:`agents.core.autonomy.irreversible`) showing every capability's risk sentence,
   the declared surface, the source and test sha256 and what it replaces.

Nothing is installed until a *person* accepts that exact card (a machine decider and an
``edit`` are refused, and a payload that moved is ``payload_changed``). Acceptance
records the permanent owner decision on the proposal and runs the existing install,
which re-checks the receipt, signs the package and records it. **Installing still grants
nothing**: the extension's tools and commands appear only after the owner's separate
consent and the isolated activation (:mod:`.consent`, :mod:`.runtime`), and an
owner-submitted package is never registered as a generic acquired tool.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import stat
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .manifest import (
    MAX_MANIFEST_BYTES,
    ExtensionManifest,
    ManifestError,
    _unique_object,
    parse_manifest,
)
from .store_lock import StoreLockError, locked_store

logger = logging.getLogger("jarvis.extensions.submission")

APPROVAL_KIND = "extensions.install"
DESCRIPTOR_FILE = "extension.json"
SOURCE_FILE = "main.py"
TEST_FILE = "test_extension.py"
MAX_SOURCE_BYTES = 64 * 1024
MAX_REQUESTS = 256
HANDLERS = {"tools": "call", "commands": "command", "events.observe": "on_event"}
#: Names submitted code may not use: leaving the interpreter early would end a sandbox
#: run with status 0 before its checks ran (review m1).
_EXIT_NAMES = frozenset({"SystemExit", "exit", "quit"})
#: A pending card younger than this is never expired while its row is reconciled, unless
#: the request store is full (an accepted card may be about to apply).
PENDING_GRACE_S = 15 * 60
#: An install that stayed "installing" this long crashed mid-way and is recovered.
INSTALLING_STALE_S = 60 * 60
_PROVENANCE_KINDS = frozenset({"directory", "distribution", "pack"})


class SubmissionError(ValueError):
    """A bounded reason code (and an optional static detail) — never author text."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class AuthoredExtension:
    manifest: ExtensionManifest
    code: str
    test_code: str
    provenance: dict

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.code.encode("utf-8")).hexdigest()

    @property
    def test_sha256(self) -> str:
        return hashlib.sha256(self.test_code.encode("utf-8")).hexdigest()


def canonical_descriptor(manifest: ExtensionManifest) -> dict:
    """The descriptor as validated, re-serialized: unknown fields never ride along."""
    body = {
        "manifest_version": 1, "api_version": 1, "id": manifest.id, "version": manifest.version,
        "capabilities": list(manifest.capabilities), "tools": list(manifest.tools),
        "commands": list(manifest.commands), "events": list(manifest.events),
        "requires": {"extensions": dict(manifest.extension_requires),
                     "python": dict(manifest.python_requires)},
    }
    if manifest.command_requires_args:
        body["command_requires_args"] = list(manifest.command_requires_args)
    return body


def _clean_provenance(value) -> dict:
    """Owner-asserted provenance: informative, bounded, shown on the card, never trusted."""
    if value is None:
        return {"kind": "directory"}
    if not isinstance(value, dict) or set(value) - {"kind", "distribution", "version"}:
        raise SubmissionError("invalid_provenance")
    kind = value.get("kind")
    if kind not in _PROVENANCE_KINDS:
        raise SubmissionError("invalid_provenance")
    result = {"kind": kind}
    for key, cap in (("distribution", 128), ("version", 64)):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, str) or not item or len(item) > cap or not item.isprintable():
            raise SubmissionError("invalid_provenance")
        result[key] = item
    return result


def from_parts(descriptor, code, test_code, provenance=None) -> AuthoredExtension:
    """Build a submission from a descriptor object and the two files' text."""
    try:
        manifest = parse_manifest(descriptor)
    except ManifestError as exc:
        raise SubmissionError(str(exc)) from None
    for value in (code, test_code):
        if not isinstance(value, str) or not value.strip():
            raise SubmissionError("source_required")
        if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise SubmissionError("source_too_large")
    return AuthoredExtension(manifest, code, test_code, _clean_provenance(provenance))


def _read_bounded(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise SubmissionError("file_unreadable", path.name) from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SubmissionError("file_not_regular", path.name)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
    finally:
        os.close(descriptor)
    if len(raw) > limit:
        raise SubmissionError("file_too_large", path.name)
    return raw


def _text(raw: bytes, name: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SubmissionError("file_not_utf8", name) from None


def _descriptor_object(raw: bytes):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except ManifestError as exc:
        raise SubmissionError(str(exc)) from None
    except (ValueError, RecursionError):
        raise SubmissionError("manifest_unreadable") from None


def read_directory(path: str | Path) -> AuthoredExtension:
    """Read an author's directory: three regular files, no symlinks, bounded."""
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise SubmissionError("directory_not_regular")
    descriptor = _descriptor_object(_read_bounded(root / DESCRIPTOR_FILE, MAX_MANIFEST_BYTES))
    code = _text(_read_bounded(root / SOURCE_FILE, MAX_SOURCE_BYTES), SOURCE_FILE)
    test_code = _text(_read_bounded(root / TEST_FILE, MAX_SOURCE_BYTES), TEST_FILE)
    return from_parts(descriptor, code, test_code, {"kind": "directory"})


def read_installed(extension_id: str, *, distributions=None) -> AuthoredExtension:
    """Read an extension an installed distribution declares — metadata and files only.

    ``main.py`` and ``test_extension.py`` must sit beside the descriptor and be listed
    in the distribution's RECORD. Nothing is imported.
    """
    from .distribution import find_installed

    row = find_installed(extension_id, distributions=distributions)
    if row is None:
        raise SubmissionError("extension_not_installed")
    dist, member = row["dist"], row["member"]
    parent = Path(member).parent
    files = {Path(str(item)).as_posix() for item in (dist.files or ())}
    texts = {}
    for name in (SOURCE_FILE, TEST_FILE):
        relative = (parent / name).as_posix()
        if relative not in files:
            raise SubmissionError("file_not_recorded", name)
        texts[name] = _text(_read_bounded(Path(dist.locate_file(relative)), MAX_SOURCE_BYTES), name)
    return from_parts(canonical_descriptor(row["manifest"]), texts[SOURCE_FILE], texts[TEST_FILE],
                      {"kind": "distribution", "distribution": row["distribution"][:128] or "unknown",
                       "version": row["distribution_version"][:64] or "unknown"})


# ── static checks: the generator's own rules ───────────────────────────────────

def check_source(authored: AuthoredExtension) -> None:
    import ast

    from agents.core.acquisition.generator import GenerationError, StrictLocalGenerator
    from agents.core.security.scanner import PIIScanner, SecretScanner

    combined = f"{authored.code}\n{authored.test_code}"
    if SecretScanner().scan(combined).findings or PIIScanner().scan(combined).findings:
        raise SubmissionError("source_contains_secret")
    try:
        code_tree = StrictLocalGenerator._parse_and_validate(authored.code, label="implementation",
                                                             allow_main=False)
        test_tree = StrictLocalGenerator._parse_and_validate(authored.test_code, label="test",
                                                             allow_main=True)
        StrictLocalGenerator._validate_entrypoint(code_tree, "register")
        for capability in authored.manifest.capabilities:
            StrictLocalGenerator._validate_entrypoint(code_tree, HANDLERS[capability])
    except GenerationError as exc:
        # The generator's messages are static strings, never candidate text.
        raise SubmissionError("source_rejected", str(exc)) from None
    except (RecursionError, ValueError, MemoryError):
        # Pathological nesting or a NUL byte: refused, never a 500.
        raise SubmissionError("source_rejected", "source cannot be parsed") from None
    for tree in (code_tree, test_tree):
        for node in ast.walk(tree):
            if ((isinstance(node, ast.Name) and node.id in _EXIT_NAMES)
                    or (isinstance(node, ast.Attribute) and node.attr in _EXIT_NAMES | {"_exit"})):
                raise SubmissionError("source_rejected", "the source may not exit the interpreter")
    candidates = ("register", *(HANDLERS[name] for name in authored.manifest.capabilities))
    for name in candidates:
        try:
            StrictLocalGenerator._validate_test(test_tree, name)
            break
        except GenerationError:
            continue
    else:
        raise SubmissionError("test_rejected", "the test must call a handler and assert")
    if not any(isinstance(node, ast.FunctionDef) and node.name.startswith("test")
               for node in ast.walk(test_tree)):
        raise SubmissionError("test_rejected", "no test function")


def reserved_names(tool_rpc) -> frozenset[str]:
    """Names an extension id may never take: every tool the hub registered that is not an
    acquired package's generic tool, the tool-search bridge names and the core commands.
    Read from the live registries, not a hand list."""
    from agents.core.acquisition.promotion import ACQUIRED_CAPABILITY_PREFIX
    from agents.core.tool_search import BRIDGE_TOOL_NAMES

    from .manifest import core_commands

    names = set(BRIDGE_TOOL_NAMES) | set(core_commands())
    reader = getattr(tool_rpc, "registered_capabilities", None)
    if callable(reader):
        names |= {name for name, capability in reader().items()
                  if not (isinstance(capability, str) and capability.startswith(ACQUIRED_CAPABILITY_PREFIX))}
    return frozenset(name.lower() for name in names)


def _require_free_name(manifest: ExtensionManifest, tool_rpc) -> None:
    try:
        reserved = reserved_names(tool_rpc)
    except Exception:  # noqa: BLE001 - cannot tell what the hub owns: refuse
        raise SubmissionError("extension_id_unverifiable") from None
    if manifest.id.lower() in reserved:
        raise SubmissionError("extension_id_reserved", "the id is a core tool or command name")


def _removals(broker, name: str) -> tuple[str, list[str]]:
    """What installing *name* takes away: the package it replaces and the generic acquired
    tool it unregisters. Returns (the replaced package's hash or "", card lines)."""
    from agents.core.acquisition.promotion import is_acquired_tool

    lines, replaced_hash = [], ""
    current = broker.packages.get(name)
    if current is not None:
        replaced_hash = current.package_hash
        lines.append(f"package {current.name} {current.version} ({current.manifest.get('model_route', 'unknown')}, "
                     f"package {current.package_hash[:12]})")
    if is_acquired_tool(broker.tool_rpc, name):
        lines.append(f"the generic acquired tool {name} (unregistered at install)")
    return replaced_hash, lines


def _mediation_refusal(orch) -> str | None:
    """With task mediation enforced, an unclassified card kind is refused at intake: say
    so before anything is quarantined, so a refusal leaves no orphan behind."""
    queue = getattr(getattr(orch, "autonomy", None), "queue", None)
    mode = str(getattr(queue, "mediation_mode", "off") or "off").lower()
    if mode == "off":
        return None
    if mode == "hold":
        return "approval_queue_on_hold"
    classify = getattr(queue, "classify_mediation", None)
    try:
        verdict = classify(APPROVAL_KIND) if callable(classify) else None
    except Exception:  # noqa: BLE001
        verdict = None
    return "approval_kind_unclassified" if verdict is None else None


def registration(manifest: ExtensionManifest) -> dict:
    return {"tools": sorted(manifest.qualified_tools), "commands": sorted(manifest.commands),
            "events": sorted(manifest.events)}


def build_package(authored: AuthoredExtension, *, clock=time.time):
    """The quarantine package and its system-owned contract (no I/O)."""
    from agents.core.acquisition.generator import (
        OWNER_SUBMITTED_ROUTE,
        CapabilityContract,
        ContractCase,
        GeneratedPackage,
        _canonical_hash,
        authored_goal,
    )

    from .consent import declared_digest

    manifest = authored.manifest
    goal = authored_goal(manifest.id, manifest.version)
    contract = CapabilityContract(goal=goal, entrypoint="register",
                                  cases=(ContractCase(input=None, expected=registration(manifest)),))
    members = {
        "artifact_id": uuid.uuid4().hex,
        "request_id": uuid.uuid4().hex,
        "name": manifest.id,
        "entrypoint": "register",
        "goal_hash": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        "plan_hash": _canonical_hash({"descriptor": canonical_descriptor(manifest),
                                      "declared_digest": declared_digest(manifest),
                                      "provenance": authored.provenance}),
        "contract_hash": contract.contract_hash,
        "model_route": OWNER_SUBMITTED_ROUTE,
        "generated_at": float(clock()),
        "source_hash": authored.source_sha256,
        "test_hash": authored.test_sha256,
    }
    package = GeneratedPackage(code=authored.code, test_code=authored.test_code,
                               package_hash=_canonical_hash(members), **members)
    return package, contract


def _verifier_class():
    from agents.core.acquisition.sandbox_profile import SandboxVerifier

    class ExtensionVerifier(SandboxVerifier):
        """The acquisition verifier with one system-owned contract: ``register()`` takes
        nothing and must return exactly the declared surface.

        Exit status 0 alone does not pass the contract run: it must also print a marker
        carrying a nonce chosen for this run, which the submitted code never sees, so code
        that leaves the interpreter early cannot pass a contract that never ran."""

        def __init__(self, *args, **kwargs):
            import secrets

            super().__init__(*args, **kwargs)
            self.marker = f"SYSTEM_CONTRACT_OK {secrets.token_hex(16)}"

        async def _run(self, source, contract, name, command, *, mutate=False):
            from dataclasses import replace as _replace

            result = await super()._run(source, contract, name, command, mutate=mutate)
            is_contract = bool(command) and str(command[-1]).endswith("/contract_test.py")
            if (is_contract and not mutate and result.exit_code == 0
                    and self.marker not in str(result.stdout or "").splitlines()):
                return _replace(result, exit_code=1)
            return result

        def contract_test_source(self, contract) -> str:
            payload = json.dumps(asdict(contract), ensure_ascii=False, separators=(",", ":"))
            return (
                "import importlib.util\n"
                "import json\n"
                "import sys\n\n"
                f"CONTRACT = json.loads({payload!r})\n"
                "spec = importlib.util.spec_from_file_location('nerva_extension', '/workspace/source/main.py')\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "register = getattr(module, 'register')\n"
                "if '--jarvis-mutate-contract' in sys.argv[1:]:\n"
                f"    register = lambda: {{'__jarvis_forced_mutation__': '{contract.contract_hash}'}}\n"
                "expected = CONTRACT['cases'][0]['expected']\n"
                "actual = register()\n"
                "if not isinstance(actual, dict) or set(actual) != set(expected):\n"
                "    raise AssertionError('registration keys differ from the declaration')\n"
                "for key, names in expected.items():\n"
                "    value = actual[key]\n"
                "    if (not isinstance(value, (list, tuple)) or len(set(value)) != len(value)\n"
                "            or sorted(value) != names):\n"
                "        raise AssertionError('registration differs from the declaration')\n"
                f"print({self.marker!r})\n"
            )

    return ExtensionVerifier


# ── the card ─────────────────────────────────────────────────────────────────

def _requests_path() -> Path:
    from ..paths import data_path

    return data_path("extensions", "install_requests.json")


def _read_requests(path: Path) -> dict:
    try:
        if path.is_symlink():
            return {}
        raw = path.read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            return {}
        value = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return {}
    rows = value.get("requests") if isinstance(value, dict) and value.get("version") == 1 else None
    return {key: row for key, row in rows.items() if isinstance(row, dict)} if isinstance(rows, dict) else {}


def _write_requests(path: Path, rows: dict) -> None:
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "requests": rows}, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _card(authored: AuthoredExtension, proposal, package, receipt_hash: str, replaced_hash: str,
          removals: list[str]) -> tuple[dict, dict]:
    from .capabilities import consent_screen
    from .consent import declared_digest

    manifest = authored.manifest
    payload = {
        "proposal_id": proposal.proposal_id,
        "artifact_id": package.artifact_id,
        "extension": manifest.id,
        "version": manifest.version,
        "package_hash": package.package_hash,
        "receipt_hash": receipt_hash,
        "source_sha256": authored.source_sha256,
        "test_sha256": authored.test_sha256,
        "declared_digest": declared_digest(manifest),
        "provenance": dict(authored.provenance),
        # The install refuses if the installed package is no longer the one this card
        # was computed against (review m2: no silent downgrade by an older card).
        "replaces_package_hash": replaced_hash,
    }
    screen = consent_screen(manifest, {"consent": "not_granted", "declared_digest": payload["declared_digest"]})
    preview = {
        "action": f"Install the third-party extension {manifest.id} {manifest.version}",
        "capabilities": [f"{row['title']} [{row['id']}]: {row['risk']}" for row in screen["capabilities"]],
        "tools": ", ".join(screen["tools"]) or "none",
        "commands": ", ".join(screen["commands"]) or "none",
        "events": ", ".join(screen["events"]) or "none",
        "source": (f"main.py sha256 {authored.source_sha256} ({len(authored.code.encode('utf-8'))} bytes); "
                   f"test_extension.py sha256 {authored.test_sha256}"),
        "provenance": "owner-asserted, not verified: " + ", ".join(
            f"{k}={v}" for k, v in sorted(authored.provenance.items())),
        "replaces": "; ".join(removals) or "nothing",
        "effect": ("signs and stores this exact code after it passed its tests and the declared-surface "
                   "contract in the sealed sandbox. Nothing becomes callable until you also consent "
                   "and activate it."),
    }
    return payload, preview


async def submit(acquisition, authored: AuthoredExtension, *, orch, runner=None, clock=time.time) -> dict:
    """Static checks -> quarantine -> sandbox verification -> proposal -> the owner's card."""
    from agents.core.acquisition.promotion import PromotionError
    from agents.core.acquisition.quarantine import QuarantineError
    from agents.core.autonomy import irreversible

    check_source(authored)
    if acquisition is None:
        raise SubmissionError("acquisition_unavailable")
    if not acquisition.is_enabled():
        raise SubmissionError("acquisition_disabled")
    broker = acquisition.ensure_promotion()
    if broker is None:
        raise SubmissionError("acquisition_unavailable")
    _require_free_name(authored.manifest, broker.tool_rpc)
    refusal = _mediation_refusal(orch)
    if refusal:
        raise SubmissionError(refusal)
    package, contract = build_package(authored, clock=clock)
    try:
        broker.quarantine.put(package)
    except QuarantineError:
        raise SubmissionError("quarantine_refused") from None
    verifier = _verifier_class()(profile=broker.profile, runner=runner,
                                 runtime_root=acquisition.verification_root())
    outcome = await verifier.verify_quarantined(store=broker.quarantine, artifact_id=package.artifact_id,
                                                contract=contract)
    if not outcome.verified or outcome.receipt is None:
        raise SubmissionError("verification_failed", outcome.reason)
    try:
        proposal = broker.propose(package.artifact_id, contract=contract, version=authored.manifest.version)
    except PromotionError as exc:
        raise SubmissionError("proposal_refused", str(exc)) from None
    replaced_hash, removals = _removals(broker, authored.manifest.id)
    replaces = "; ".join(removals) or None
    payload, preview = _card(authored, proposal, package, outcome.receipt.receipt_hash, replaced_hash, removals)
    path = _requests_path()
    try:
        with locked_store(path):
            rows = _read_requests(path)
            now = float(clock())
            _reconcile(rows, orch, broker, now=now, force=len(rows) >= MAX_REQUESTS)
            # A newer card for the same extension supersedes every older waiting one.
            for key, row in rows.items():
                if row.get("status") == "pending" and (row.get("payload") or {}).get("extension") == authored.manifest.id:
                    _retire(rows, key, broker, "superseded", now)
            if len(rows) >= MAX_REQUESTS:
                # Keep the newest; a settled row is history, a pending one may still be decided.
                settled = sorted((key for key, row in rows.items() if row.get("status") != "pending"),
                                 key=lambda key: rows[key].get("requested_at", 0))
                for key in settled[: len(rows) - MAX_REQUESTS + 1]:
                    del rows[key]
                if len(rows) >= MAX_REQUESTS:
                    raise SubmissionError("install_request_capacity")
            queued = irreversible.enqueue(orch, APPROVAL_KIND,
                                          title=f"Install extension {authored.manifest.id} {authored.manifest.version}",
                                          payload=payload, preview=preview)
            if "pending" not in queued:
                raise SubmissionError(str(queued.get("refused") or "approval_queue_unavailable"))
            rows[proposal.proposal_id] = {"task_id": queued["pending"], "payload": payload, "status": "pending",
                                          "requested_at": float(clock())}
            _write_requests(path, rows)
    except StoreLockError:
        raise SubmissionError("install_requests_unavailable") from None
    return {"pending": queued["pending"], "proposal_id": proposal.proposal_id,
            "extension": authored.manifest.id, "version": authored.manifest.version,
            "package_hash": package.package_hash, "replaces": replaces}


def _waiting_task_ids(orch) -> set | None:
    """Ids of the install cards still waiting for a decision, or None when the queue
    cannot say (then nothing is expired on its account)."""
    from agents.core.autonomy import irreversible

    queue = getattr(getattr(orch, "autonomy", None), "queue", None)
    lister = getattr(queue, "pending_decisions", None)
    if not callable(lister):
        return None
    try:
        found = lister(kind=APPROVAL_KIND, limit=irreversible.PENDING_MAX)
    except Exception:  # noqa: BLE001 - cannot tell
        return None
    return {getattr(task, "id", None) for task in found if getattr(task, "kind", APPROVAL_KIND) == APPROVAL_KIND}


def _retire(rows: dict, key: str, broker, status: str, now: float) -> None:
    rows[key]["status"] = status
    rows[key]["settled_at"] = now
    if broker is not None:
        with contextlib.suppress(Exception):
            broker.proposals.discard(key)


def _reconcile(rows: dict, orch, broker, *, now: float, force: bool) -> None:
    """Settle rows whose card is gone (review m4): a waiting row whose card is no longer
    waiting expires (after a grace, or at once when the store is full) and its proposal is
    dropped; an install that crashed mid-way is recovered from the package store."""
    waiting = _waiting_task_ids(orch)
    for key, row in list(rows.items()):
        status = row.get("status")
        if status == "pending" and waiting is not None and row.get("task_id") not in waiting:
            if force or now - float(row.get("requested_at") or 0) > PENDING_GRACE_S:
                _retire(rows, key, broker, "expired", now)
        elif status == "installing" and now - float(row.get("installing_at") or 0) > INSTALLING_STALE_S:
            payload = row.get("payload") or {}
            current = broker.packages.get(payload.get("extension", "")) if broker is not None else None
            done = current is not None and current.package_hash == payload.get("package_hash")
            row["status"] = "installed" if done else "failed"
            row["settled_at"] = now


def _audit(orch: Any, actor: str, action: str, why: str, metadata: dict) -> None:
    audit = getattr(orch, "intent_log", None)
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor=actor, action=action, why=why, cause="extensions.install", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("extension install intent projection failed", exc_info=True)


def _settle(path: Path, proposal_id: str, status: str) -> None:
    try:
        with locked_store(path):
            rows = _read_requests(path)
            if proposal_id in rows:
                rows[proposal_id]["status"] = status
                rows[proposal_id]["settled_at"] = time.time()
                _write_requests(path, rows)
    except (StoreLockError, OSError):
        logger.warning("extension install request could not be settled")


async def apply_approved(task: Any, orch: Any) -> dict:
    """A person accepted the card (``irreversible.execute`` checked who decided): record the
    permanent owner decision on exactly that proposal and run the existing install."""
    from types import SimpleNamespace

    from agents.core.acquisition.promotion import PromotionError

    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decision not in ("accept", "approve"):
        return {"status": "refused", "reason": "edit_not_supported"}
    payload = dict(getattr(task, "payload", {}) or {})
    proposal_id = payload.get("proposal_id")
    path = _requests_path()
    try:
        with locked_store(path):
            rows = _read_requests(path)
            row = rows.get(proposal_id) if isinstance(proposal_id, str) else None
            if row is None or row.get("task_id") != getattr(task, "id", None):
                return {"status": "refused", "reason": "not_requested"}
            if row.get("status") in {"superseded", "expired"}:
                return {"status": "refused", "reason": f"card_{row['status']}"}
            if row.get("status") != "pending":
                return {"status": "refused", "reason": "already_applied"}
            expected = row.get("payload") or {}
            if not expected or any(payload.get(key) != value for key, value in expected.items()):
                return {"status": "refused", "reason": "payload_changed"}
            row["status"] = "installing"
            row["installing_at"] = time.time()
            _write_requests(path, rows)
    except StoreLockError:
        return {"status": "refused", "reason": "install_requests_unavailable"}
    acquisition = getattr(orch, "acquisition", None) if orch is not None else None
    broker = acquisition.ensure_promotion() if acquisition is not None else None
    if broker is None:
        _settle(path, proposal_id, "pending")
        return {"status": "refused", "reason": "acquisition_unavailable"}
    proposal = broker.proposals.get(proposal_id)
    if (proposal is None or proposal.package_hash != expected["package_hash"]
            or proposal.receipt_hash != expected["receipt_hash"] or proposal.version != expected["version"]
            or proposal.name != expected["extension"] or proposal.status != "pending"):
        _settle(path, proposal_id, "refused")
        return {"status": "refused", "reason": "proposal_changed"}
    try:
        _require_free_name(SimpleNamespace(id=expected["extension"]), broker.tool_rpc)
    except SubmissionError as exc:
        _settle(path, proposal_id, "refused")
        return {"status": "refused", "reason": exc.reason}
    current = broker.packages.get(expected["extension"])
    if (current.package_hash if current is not None else "") != expected.get("replaces_package_hash", ""):
        # Another install landed since this card was computed: its "replaces" line is
        # stale, and accepting it could silently downgrade. Ask again.
        _settle(path, proposal_id, "refused")
        return {"status": "refused", "reason": "installed_package_moved"}
    actor = str(getattr(task, "decided_by", "") or "owner")
    try:
        broker.decide(proposal_id, approved=True, actor="owner", permanent=True)
    except (PromotionError, KeyError, ValueError):
        _settle(path, proposal_id, "refused")
        return {"status": "refused", "reason": "proposal_refused"}
    result = await broker.execute_task(SimpleNamespace(payload={"proposal_id": proposal_id}))
    if result.get("status") != "installed":
        _settle(path, proposal_id, "failed")
        return {"status": "failed", "reason": str(result.get("reason") or "install_failed")}
    _settle(path, proposal_id, "installed")
    _audit(orch, actor, "extension.install",
           f"extension {expected['extension']} {expected['version']} installed (task {getattr(task, 'id', None)})",
           {"extension": expected["extension"], "version": expected["version"],
            "package_hash": expected["package_hash"], "source_sha256": expected["source_sha256"]})
    return {"status": "installed", "extension": expected["extension"], "version": expected["version"],
            "package_hash": expected["package_hash"]}


__all__ = ["APPROVAL_KIND", "AuthoredExtension", "SubmissionError", "apply_approved", "build_package",
           "canonical_descriptor", "check_source", "from_parts", "read_directory", "read_installed",
           "registration", "reserved_names", "submit"]
