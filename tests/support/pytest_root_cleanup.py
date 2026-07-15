"""Delete one validated pytest data root after its parent process exits."""

from __future__ import annotations

import argparse
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

_ROOT_NAME = re.compile(r"jarvis-pytest-[A-Za-z0-9_][A-Za-z0-9._-]*\Z")
_DEFAULT_ATTEMPTS = 120
_DEFAULT_DELAY_SECONDS = 0.1


def validated_pytest_root(raw_target: str | Path) -> Path | None:
    """Return an exact safe target, or refuse anything outside direct temp children."""
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        target = Path(raw_target).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if target.parent != temp_root or _ROOT_NAME.fullmatch(target.name) is None:
        return None
    return target


def remove_pytest_root(target: Path, *, attempts: int, delay_seconds: float) -> bool:
    """Retry deletion of one pre-validated root while Windows releases handles."""
    for attempt in range(attempts):
        try:
            target.chmod(stat.S_IRWXU)
            shutil.rmtree(target)
        except FileNotFoundError:
            return True
        except OSError:
            if not target.exists():
                return True
            if attempt + 1 == attempts:
                return False
            time.sleep(delay_seconds)
        else:
            return True
    return False


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--attempts", type=_positive_int, default=_DEFAULT_ATTEMPTS)
    parser.add_argument("--delay", type=_non_negative_float, default=_DEFAULT_DELAY_SECONDS)
    args = parser.parse_args(argv)

    target = validated_pytest_root(args.target)
    if target is None:
        print("refusing unsafe pytest root", file=sys.stderr)
        return 2
    if remove_pytest_root(target, attempts=args.attempts, delay_seconds=args.delay):
        return 0
    print("pytest root cleanup retries exhausted", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
