"""``pm`` (Hermes's lazy package installer) for vendored code.

Nerva never installs a package at runtime because a provider asked for one. The two extras
the adopted providers ask for are the compat SDK stand-ins, which are always present; any
other extra is refused, and ``plugins/web/_common.lazy_ensure`` turns that into the
ImportError the vendored code already handles ("SDK not installed").
"""

#: Extras the compat layer provides itself (``hermes_compat.sdk``).
PROVIDED = frozenset({"exa", "parallel-web"})


class InstallError(Exception):
    """Raised for an extra Nerva does not provide."""


def ensure_import(extra: str) -> None:
    if extra not in PROVIDED:
        raise InstallError(f"{extra} is not available in Nerva (runtime installs are off)")
