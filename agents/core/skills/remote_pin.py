"""Validated immutable source and per-call authority for remote skill imports."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

_REPO_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ENTRY_NAMES = {"SKILL.md", "manifest.json", "manifest.yaml", "manifest.yml"}
_REFUSALS = {
    "missing_pin", "invalid_pin", "authorization_unavailable", "install_denied",
    "egress_denied", "fetch_failed", "digest_mismatch", "source_identity_mismatch",
    "invalid_skill", "already_exists", "staging_failed",
}


class RemoteImportRefused(ValueError):
    """Bounded public refusal, with no upstream body, URL, or owner path."""

    def __init__(self, code: str):
        if code not in _REFUSALS:
            raise ValueError("invalid remote import refusal code")
        self.code = code
        super().__init__(code)


def _safe_path(path: object) -> bool:
    if type(path) is not str or not 1 <= len(path) <= 512 or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return (pure.as_posix() == path and len(pure.parts) >= 2
            and all(_PATH_PART.fullmatch(part) for part in pure.parts))


@dataclass(frozen=True, slots=True)
class RemoteSkillPin:
    repo: str
    commit: str
    entry_path: str
    content_sha256: str
    references: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (type(self.repo) is not str or len(self.repo) > 201
                or len(self.repo.split("/")) != 2
                or not all(_REPO_PART.fullmatch(part) for part in self.repo.split("/"))
                or type(self.commit) is not str or not _SHA40.fullmatch(self.commit)
                or not _safe_path(self.entry_path)
                or self.entry_path.rsplit("/", 1)[-1] not in _ENTRY_NAMES
                or type(self.content_sha256) is not str
                or not _SHA256.fullmatch(self.content_sha256)
                or type(self.references) is not tuple or len(self.references) > 64):
            raise RemoteImportRefused("invalid_pin")
        prefix = self.entry_path.rsplit("/", 1)[0] + "/references/"
        seen: set[str] = set()
        for reference in self.references:
            if (type(reference) is not tuple or len(reference) != 2
                    or not _safe_path(reference[0])
                    or not reference[0].startswith(prefix)
                    or type(reference[1]) is not str
                    or not _SHA256.fullmatch(reference[1])
                    or reference[0] in seen):
                raise RemoteImportRefused("invalid_pin")
            seen.add(reference[0])

    @classmethod
    def from_dict(cls, value: object) -> RemoteSkillPin:
        if type(value) is not dict or not {
            "repo", "commit", "entry_path", "content_sha256",
        } <= value.keys() or value.keys() - {
            "repo", "commit", "entry_path", "content_sha256", "references",
        }:
            raise RemoteImportRefused("invalid_pin")
        raw_refs = value.get("references", [])
        if type(raw_refs) is not list or len(raw_refs) > 64:
            raise RemoteImportRefused("invalid_pin")
        refs = []
        for row in raw_refs:
            if type(row) is not dict or set(row) != {"path", "content_sha256"}:
                raise RemoteImportRefused("invalid_pin")
            refs.append((row["path"], row["content_sha256"]))
        return cls(value["repo"], value["commit"], value["entry_path"],
                   value["content_sha256"], tuple(refs))


@dataclass(frozen=True, slots=True)
class RemoteImportAuthorization:
    install_gate: Callable[[dict], str]
    egress_gate: Callable[[str, str, str, str], str | None]

    def __post_init__(self) -> None:
        if not callable(self.install_gate) or not callable(self.egress_gate):
            raise RemoteImportRefused("authorization_unavailable")
