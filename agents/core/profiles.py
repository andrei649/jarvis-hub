"""Named hub profile management: registry, aliases, archive export/import, and wrapper scripts (H036).

Works directly on the H689/H689b profile layout resolved by :mod:`agents.core.paths`:
- ``default`` lives at :func:`agents.core.paths.install_root`
- Named profiles live at ``<install_root>-profiles/<name>`` with isolated ``.env`` files
- Metadata (descriptions and aliases) lives at ``<install_root>-profiles/_registry.json``
  (prefixed with ``_`` so it never matches ``_PROFILE_RE`` or shell directory completion).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .paths import (
    _PROFILE_RE,
    app_root,
    install_root,
    profile_name,
    profiles_root,
)

REGISTRY_FILENAME = "_registry.json"
MANIFEST_FILENAME = "profile_manifest.json"
ARCHIVE_FORMAT = "nerva-profile-v1"
MAX_DESCRIPTION_CHARS = 280
MAX_IMPORT_BYTES = 256 * 1024 * 1024
MAX_IMPORT_MEMBERS = 5000
_SECRET_FILENAMES = frozenset({".env", "secrets.enc", "audit.key", "backup.key"})
_TRANSIENT_FILENAMES = frozenset({"hub.lock", "history.lock"})


def validate_profile_token(value: str, *, label: str = "profile name") -> str:
    cleaned = str(value or "").strip()
    if not _PROFILE_RE.match(cleaned):
        raise ValueError(
            f"{cleaned!r} is not a valid {label}: use 1-32 lowercase letters, digits, "
            "'-' or '_', starting with a letter or digit"
        )
    return cleaned


def _clean_description(text: str | None) -> str:
    if not text:
        return ""
    collapsed = " ".join(
        "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text)).split()
    )
    return collapsed[:MAX_DESCRIPTION_CHARS]


def _registry_path(base: Path) -> Path:
    return profiles_root(base) / REGISTRY_FILENAME


def read_profile_registry(base: Path) -> dict[str, dict[str, str]]:
    """Read ``{"descriptions": {...}, "aliases": {...}}`` from ``_registry.json``."""
    path = _registry_path(base)
    empty: dict[str, dict[str, str]] = {"descriptions": {}, "aliases": {}}
    if not path.is_file() or path.is_symlink():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    descriptions: dict[str, str] = {}
    raw_desc = raw.get("descriptions")
    if isinstance(raw_desc, Mapping):
        for k, v in raw_desc.items():
            if isinstance(k, str) and _PROFILE_RE.match(k) and isinstance(v, str):
                cleaned = _clean_description(v)
                if cleaned:
                    descriptions[k] = cleaned
    aliases: dict[str, str] = {}
    raw_aliases = raw.get("aliases")
    if isinstance(raw_aliases, Mapping):
        for k, v in raw_aliases.items():
            if (
                isinstance(k, str)
                and isinstance(v, str)
                and k != "default"
                and k != v
                and _PROFILE_RE.match(k)
                and _PROFILE_RE.match(v)
            ):
                aliases[k] = v
    return {"descriptions": descriptions, "aliases": aliases}


def _write_profile_registry(base: Path, registry: Mapping[str, Mapping[str, str]]) -> None:
    path = _registry_path(base)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and path.is_symlink():
        raise ValueError("refusing to write profile registry through a symlink")
    payload = json.dumps(
        {
            "version": 1,
            "descriptions": dict(sorted((registry.get("descriptions") or {}).items())),
            "aliases": dict(sorted((registry.get("aliases") or {}).items())),
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".profile-reg-", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def resolve_profile_alias(raw_name: str, *, base: Path) -> str:
    """Resolve one alias token against ``_registry.json``; real directories win over aliases."""
    if not raw_name or raw_name == "default" or not _PROFILE_RE.match(raw_name):
        return raw_name
    direct_dir = profiles_root(base) / raw_name
    if direct_dir.is_dir() and not direct_dir.is_symlink():
        return raw_name
    aliases = read_profile_registry(base)["aliases"]
    target = aliases.get(raw_name)
    if target and _PROFILE_RE.match(target):
        return target
    return raw_name


def _base_root(environ: Mapping[str, str] | None = None) -> Path:
    clean_env = dict(os.environ if environ is None else environ)
    clean_env.pop("JARVIS_PROFILE", None)
    clean_env.pop("NERVA_PROFILE", None)
    return install_root(clean_env)


def _profile_dir(base: Path, name: str) -> Path:
    return base if name == "default" else profiles_root(base) / name


def list_profiles(*, environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    base = _base_root(environ)
    p_root = profiles_root(base)
    reg = read_profile_registry(base)
    descriptions = reg["descriptions"]
    aliases = reg["aliases"]
    active = profile_name(environ) or "default"

    names = ["default"]
    if p_root.is_dir() and not p_root.is_symlink():
        for child in sorted(p_root.iterdir(), key=lambda p: p.name):
            if child.name != "default" and _PROFILE_RE.match(child.name) and child.is_dir() and not child.is_symlink():
                names.append(child.name)

    rows: list[dict[str, Any]] = []
    for name in names:
        root = _profile_dir(base, name)
        alias_list = sorted(alias for alias, target in aliases.items() if target == name)
        rows.append({
            "name": name,
            "root": str(root),
            "exists": root.is_dir(),
            "active": name == active,
            "description": descriptions.get(name, ""),
            "aliases": alias_list,
            "has_env": (root / ".env").is_file(),
        })
    return rows


def create_profile(
    name: str,
    *,
    description: str = "",
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_profile_token(name)
    if validated == "default":
        raise ValueError("'default' is the main installation profile and always exists")
    base = _base_root(environ)
    reg = read_profile_registry(base)
    if validated in reg["aliases"]:
        raise ValueError(f"{validated!r} is already defined as an alias for {reg['aliases'][validated]!r}")
    target = profiles_root(base) / validated
    if target.exists() or target.is_symlink():
        raise ValueError(f"profile {validated!r} already exists at {target}")
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(target, 0o700)
    env_file = target / ".env"
    env_file.write_text(f"# Isolated environment for Nerva profile '{validated}'\n", encoding="utf-8")
    os.chmod(env_file, 0o600)

    cleaned_desc = _clean_description(description)
    if cleaned_desc:
        reg["descriptions"][validated] = cleaned_desc
        _write_profile_registry(base, reg)

    return {
        "ok": True,
        "name": validated,
        "root": str(target),
        "description": cleaned_desc,
        "env_file": str(env_file),
    }


def describe_profile(
    name: str,
    description: str | None = None,
    *,
    clear: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_profile_token(name)
    base = _base_root(environ)
    resolved = resolve_profile_alias(validated, base=base)
    target = _profile_dir(base, resolved)
    if resolved != "default" and (not target.is_dir() or target.is_symlink()):
        raise ValueError(f"profile {resolved!r} does not exist")
    reg = read_profile_registry(base)
    if clear:
        reg["descriptions"].pop(resolved, None)
        _write_profile_registry(base, reg)
    elif description is not None:
        cleaned = _clean_description(description)
        if cleaned:
            reg["descriptions"][resolved] = cleaned
        else:
            reg["descriptions"].pop(resolved, None)
        _write_profile_registry(base, reg)
    aliases = sorted(a for a, t in reg["aliases"].items() if t == resolved)
    return {
        "ok": True,
        "name": resolved,
        "root": str(target),
        "exists": target.is_dir(),
        "description": reg["descriptions"].get(resolved, ""),
        "aliases": aliases,
    }


def rename_profile(
    old_name: str,
    new_name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    old_valid = validate_profile_token(old_name, label="source profile name")
    new_valid = validate_profile_token(new_name, label="target profile name")
    if old_valid == "default" or new_valid == "default":
        raise ValueError("the 'default' profile cannot be renamed or overwritten")
    if old_valid == new_valid:
        raise ValueError("source and target profile names are identical")
    base = _base_root(environ)
    reg = read_profile_registry(base)
    if new_valid in reg["aliases"]:
        raise ValueError(f"{new_valid!r} is already in use as a profile alias")
    old_dir = profiles_root(base) / old_valid
    new_dir = profiles_root(base) / new_valid
    if not old_dir.is_dir() or old_dir.is_symlink():
        raise ValueError(f"profile {old_valid!r} does not exist")
    if new_dir.exists() or new_dir.is_symlink():
        raise ValueError(f"profile {new_valid!r} already exists")
    old_dir.rename(new_dir)
    if old_valid in reg["descriptions"]:
        reg["descriptions"][new_valid] = reg["descriptions"].pop(old_valid)
    for alias, target in list(reg["aliases"].items()):
        if target == old_valid:
            reg["aliases"][alias] = new_valid
    _write_profile_registry(base, reg)
    return {
        "ok": True,
        "old_name": old_valid,
        "new_name": new_valid,
        "root": str(new_dir),
    }


def delete_profile(
    name: str,
    *,
    confirm: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_profile_token(name)
    if validated == "default":
        raise ValueError("the 'default' profile cannot be deleted")
    base = _base_root(environ)
    target = profiles_root(base) / validated
    if not target.exists() and not target.is_symlink():
        raise ValueError(f"profile {validated!r} does not exist")
    if target.is_symlink() or not target.is_dir():
        raise ValueError(f"refusing to delete non-directory or symlink profile path: {target}")
    if not confirm:
        raise ValueError(f"refusing to delete profile {validated!r} without --confirm")
    active = profile_name(environ)
    if active == validated:
        raise ValueError(f"cannot delete currently active profile {validated!r}")
    shutil.rmtree(target)
    reg = read_profile_registry(base)
    reg["descriptions"].pop(validated, None)
    removed_aliases = [alias for alias, dest in list(reg["aliases"].items()) if dest == validated]
    for alias in removed_aliases:
        reg["aliases"].pop(alias, None)
    _write_profile_registry(base, reg)
    return {
        "ok": True,
        "deleted": validated,
        "removed_aliases": sorted(removed_aliases),
    }


def set_profile_alias(
    alias: str,
    target: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    alias_valid = validate_profile_token(alias, label="alias")
    target_valid = validate_profile_token(target, label="target profile")
    if alias_valid == "default":
        raise ValueError("'default' cannot be redefined as an alias")
    base = _base_root(environ)
    if (profiles_root(base) / alias_valid).exists():
        raise ValueError(f"{alias_valid!r} already exists as a profile directory")
    reg = read_profile_registry(base)
    resolved_target = reg["aliases"].get(target_valid, target_valid)
    if resolved_target == alias_valid:
        raise ValueError("alias cannot point to itself")
    target_dir = _profile_dir(base, resolved_target)
    if resolved_target != "default" and (not target_dir.is_dir() or target_dir.is_symlink()):
        raise ValueError(f"target profile {resolved_target!r} does not exist")
    reg["aliases"][alias_valid] = resolved_target
    _write_profile_registry(base, reg)
    return {"ok": True, "alias": alias_valid, "target": resolved_target}


def remove_profile_alias(
    alias: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    alias_valid = validate_profile_token(alias, label="alias")
    base = _base_root(environ)
    reg = read_profile_registry(base)
    existed = reg["aliases"].pop(alias_valid, None)
    if existed is None:
        raise ValueError(f"alias {alias_valid!r} does not exist")
    _write_profile_registry(base, reg)
    return {"ok": True, "unaliased": alias_valid, "previous_target": existed}


def _should_skip_export_file(rel: PurePosixPath, *, include_secrets: bool) -> bool:
    name = rel.name
    if name in _TRANSIENT_FILENAMES or name.endswith((".lock", "-wal", "-shm")):
        return True
    if not include_secrets and (name in _SECRET_FILENAMES or name.endswith(".key")):
        return True
    return False


def export_profile(
    name: str,
    out_path: Path,
    *,
    include_secrets: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    validated = validate_profile_token(name)
    base = _base_root(environ)
    resolved = resolve_profile_alias(validated, base=base)
    src_dir = _profile_dir(base, resolved)
    if not src_dir.is_dir() or src_dir.is_symlink():
        raise ValueError(f"profile {resolved!r} does not exist")

    reg = read_profile_registry(base)
    description = reg["descriptions"].get(resolved, "")

    dest = Path(out_path).expanduser()
    if dest.exists() and dest.is_symlink():
        raise ValueError("refusing to write profile archive through a symlink")
    dest.parent.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, dict[str, Any]] = {}
    staged: list[tuple[str, bytes]] = []

    for item in sorted(src_dir.rglob("*")):
        if item.is_symlink() or not item.is_file():
            continue
        rel = PurePosixPath(item.relative_to(src_dir).as_posix())
        if rel.as_posix() == MANIFEST_FILENAME or _should_skip_export_file(rel, include_secrets=include_secrets):
            continue
        data = item.read_bytes()
        manifest_files[rel.as_posix()] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        staged.append((rel.as_posix(), data))

    manifest_bytes = (
        json.dumps(
            {
                "format": ARCHIVE_FORMAT,
                "name": resolved,
                "description": description,
                "include_secrets": bool(include_secrets),
                "exported_at": time.time(),
                "files": manifest_files,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(prefix=".profile-exp-", suffix=".tar.gz", dir=str(dest.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as raw_out, tarfile.open(fileobj=raw_out, mode="w:gz") as tar:
            m_info = tarfile.TarInfo(name=MANIFEST_FILENAME)
            m_info.size = len(manifest_bytes)
            m_info.mode = 0o600
            m_info.mtime = int(time.time())
            tar.addfile(m_info, io.BytesIO(manifest_bytes))
            for rel_str, content in staged:
                info = tarfile.TarInfo(name=f"data/{rel_str}")
                info.size = len(content)
                info.mode = 0o600
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(content))
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return {
        "ok": True,
        "name": resolved,
        "archive": str(dest),
        "file_count": len(staged),
        "include_secrets": bool(include_secrets),
    }


def _validate_archive_relpath(member_name: str) -> PurePosixPath:
    if not member_name or "\\" in member_name or member_name.startswith("/"):
        raise ValueError(f"unsafe archive path: {member_name!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in member_name):
        raise ValueError(f"control character in archive path: {member_name!r}")
    pure = PurePosixPath(member_name)
    if any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError(f"traversal segment in archive path: {member_name!r}")
    return pure


def import_profile(
    archive_path: Path,
    *,
    as_name: str | None = None,
    force: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    src = Path(archive_path).expanduser()
    if not src.is_file() or src.is_symlink():
        raise ValueError(f"archive does not exist or is a symlink: {src}")

    extracted_files: dict[str, bytes] = {}
    manifest: dict[str, Any] | None = None
    total_bytes = 0

    with tarfile.open(src, mode="r:gz") as tar:
        members = tar.getmembers()
        if len(members) > MAX_IMPORT_MEMBERS:
            raise ValueError("profile archive exceeds maximum member count")
        for member in members:
            pure = _validate_archive_relpath(member.name)
            if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                raise ValueError(f"archive member {member.name!r} uses a forbidden special file type")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"unsupported archive entry type: {member.name!r}")
            if member.size < 0 or total_bytes + member.size > MAX_IMPORT_BYTES:
                raise ValueError("profile archive exceeds maximum uncompressed size")
            total_bytes += member.size
            reader = tar.extractfile(member)
            if reader is None:
                continue
            payload = reader.read(MAX_IMPORT_BYTES + 1)
            if len(payload) != member.size:
                raise ValueError(f"archive member size mismatch: {member.name!r}")
            if pure.as_posix() == MANIFEST_FILENAME:
                try:
                    parsed = json.loads(payload.decode("utf-8"))
                except ValueError as exc:
                    raise ValueError("invalid JSON in profile_manifest.json") from exc
                if not isinstance(parsed, dict) or parsed.get("format") != ARCHIVE_FORMAT:
                    raise ValueError("unsupported profile archive manifest format")
                manifest = parsed
            elif pure.parts[0] == "data" and len(pure.parts) >= 2:
                rel_key = PurePosixPath(*pure.parts[1:]).as_posix()
                extracted_files[rel_key] = payload
            else:
                raise ValueError(f"unexpected archive layout path: {member.name!r}")

    if manifest is None:
        raise ValueError("archive is missing profile_manifest.json")

    declared_files = manifest.get("files")
    if not isinstance(declared_files, Mapping):
        raise ValueError("profile manifest files table is malformed")
    if set(declared_files.keys()) != set(extracted_files.keys()):
        raise ValueError("archive contents do not match profile_manifest.json file list")
    for rel_key, data in extracted_files.items():
        meta = declared_files.get(rel_key)
        if not isinstance(meta, Mapping):
            raise ValueError(f"missing manifest metadata for {rel_key!r}")
        if hashlib.sha256(data).hexdigest() != meta.get("sha256") or len(data) != meta.get("size"):
            raise ValueError(f"digest or size mismatch for archive file {rel_key!r}")

    chosen_raw = as_name if as_name else str(manifest.get("name") or "")
    target_name = validate_profile_token(chosen_raw, label="imported profile name")
    if target_name == "default":
        raise ValueError("cannot import over 'default'; pass --as <profile-name>")

    base = _base_root(environ)
    reg = read_profile_registry(base)
    if target_name in reg["aliases"]:
        raise ValueError(f"{target_name!r} is already registered as an alias")
    dest_dir = profiles_root(base) / target_name
    if dest_dir.exists() or dest_dir.is_symlink():
        if not force:
            raise ValueError(f"profile {target_name!r} already exists (pass --force to replace)")
        if dest_dir.is_symlink():
            raise ValueError("refusing to replace symlink target")
        shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(dest_dir, 0o700)
    for rel_key, data in extracted_files.items():
        out_file = dest_dir.joinpath(*PurePosixPath(rel_key).parts)
        out_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        out_file.write_bytes(data)
        os.chmod(out_file, 0o600)

    env_path = dest_dir / ".env"
    if not env_path.exists():
        env_path.write_text(f"# Isolated environment for Nerva profile '{target_name}'\n", encoding="utf-8")
        os.chmod(env_path, 0o600)

    desc = _clean_description(str(manifest.get("description") or ""))
    if desc:
        reg["descriptions"][target_name] = desc
        _write_profile_registry(base, reg)

    return {
        "ok": True,
        "name": target_name,
        "root": str(dest_dir),
        "file_count": len(extracted_files),
        "description": desc,
    }


def render_profile_wrapper(
    name: str,
    *,
    windows: bool = False,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return ``(resolved_profile_name, script_text)`` for a per-profile CLI wrapper."""
    validated = validate_profile_token(name)
    base = _base_root(environ)
    resolved = resolve_profile_alias(validated, base=base)
    target_dir = _profile_dir(base, resolved)
    if resolved != "default" and (not target_dir.is_dir() or target_dir.is_symlink()):
        raise ValueError(f"profile {resolved!r} does not exist")

    py_exe = sys.executable
    repo = str(app_root())
    if windows:
        script = (
            "@echo off\r\n"
            f"REM Generated by nerva profile wrapper for profile {resolved}\r\n"
            f'set "JARVIS_PROFILE={resolved}"\r\n'
            f'set "PYTHONPATH={repo};%PYTHONPATH%"\r\n'
            f'"{py_exe}" -m agents.cli.nerva %*\r\n'
        )
        return resolved, script

    import shlex

    q_prof = shlex.quote(resolved)
    q_py = shlex.quote(py_exe)
    q_repo = shlex.quote(repo)
    script = (
        "#!/bin/sh\n"
        f"# Generated by `nerva profile wrapper` for profile '{resolved}'\n"
        f"export JARVIS_PROFILE={q_prof}\n"
        f'export PYTHONPATH={q_repo}"${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        f"exec {q_py} -m agents.cli.nerva \"$@\"\n"
    )
    return resolved, script


def write_profile_wrapper(
    name: str,
    *,
    dest_dir: Path | None = None,
    out_path: Path | None = None,
    windows: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    resolved, content = render_profile_wrapper(name, windows=windows, environ=environ)
    suffix = ".cmd" if windows else ""
    if out_path is not None:
        target = Path(out_path).expanduser()
    else:
        folder = Path(dest_dir).expanduser() if dest_dir is not None else (_base_root(environ) / "bin")
        target = folder / f"nerva-{resolved}{suffix}"
    if target.exists() and target.is_symlink():
        raise ValueError("refusing to write wrapper script through a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    os.chmod(target, 0o755)  # nosec B103 - owner CLI wrapper script is intentionally executable
    return {
        "ok": True,
        "name": resolved,
        "wrapper": str(target),
        "windows": bool(windows),
    }
