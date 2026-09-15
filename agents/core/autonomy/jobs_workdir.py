"""Read-only validation of script cwd against existing terminal roots."""

from pathlib import Path

from ..environments.local_transport import default_roots


def validate_workdir(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
        raise ValueError("workdir must be a bounded absolute directory")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("workdir must be an absolute directory")
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("workdir symlinks are not supported")
        resolved = path.resolve(strict=True)
        roots = [Path(root).expanduser().resolve() for root in default_roots()]
        if not resolved.is_dir() or not any(
            resolved == root or root in resolved.parents for root in roots
        ):
            raise ValueError("workdir must be an existing directory inside terminal roots")
        return str(resolved)
    except (OSError, RuntimeError):
        raise ValueError("workdir is unavailable") from None
