#!/bin/bash
set -euo pipefail

PYUNLOCK_PYTHON="${PYUNLOCK_PYTHON:-python3}"
command -v "$PYUNLOCK_PYTHON" >/dev/null 2>&1 || {
    printf '%s\n' 'pyunlock uninstaller: Python 3 is required; set PYUNLOCK_PYTHON to its executable.' >&2
    exit 1
}

exec "$PYUNLOCK_PYTHON" - <<'PY'
import os
import shutil
import stat
import sys
from pathlib import Path


class RemovalError(Exception):
    pass


def fail(message):
    raise RemovalError(message)


def exists(path):
    return os.path.lexists(path)


def directory(path):
    if exists(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            fail(f"Refusing a symlink, non-directory, or directory owned by another user: {path}")


def uninstall():
    if not os.environ.get("HOME") or not Path(os.environ["HOME"]).is_absolute():
        fail("HOME must name an absolute directory.")
    home = Path(os.environ["HOME"])
    root = home / ".local/share/pyunlock"
    command = home / ".local/bin/pyunlock"
    # Validate every ancestor and both removal targets before deleting either one.
    for path in (home, home / ".local", home / ".local/share", home / ".local/bin", root, root / "envs"):
        directory(path)
    root_exists, command_exists = exists(root), exists(command)
    if root_exists:
        marker = root / ".pyunlock-managed"
        if not exists(marker):
            fail(f"Installation marker is missing: {marker}")
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            fail(f"Refusing an unsafe installation marker: {marker}")
        try:
            content = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            fail(f"Cannot read installation marker: {marker}")
        if content not in ("pyunlock-install-v1", "pyunlock-install-v1\n"):
            fail(f"Unrecognized installation marker: {marker}")
    if command_exists:
        info = command.lstat()
        if not stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
            fail(f"Refusing to remove an unrelated command: {command}")
        raw_target = os.readlink(command)
        target = Path(raw_target)
        name = target.parent.parent.name
        expected = root / "envs" / name / "bin/pyunlock"
        if not target.is_absolute() or not name or name in (".", "..") or raw_target != str(expected):
            fail(f"Command does not point to a managed environment: {command}")
        for path in (root / "envs" / name, root / "envs" / name / "bin"):
            directory(path)
    if command_exists:
        command.unlink()
        print(f"Removed command: {command}")
    if root_exists:
        shutil.rmtree(root)
        print(f"Removed application: {root}")
    print("pyunlock uninstalled." if root_exists or command_exists else "pyunlock is already uninstalled.")


try:
    uninstall()
except KeyboardInterrupt:
    print("pyunlock uninstaller: Interrupted; rerun to finish removal.", file=sys.stderr)
    sys.exit(130)
except (RemovalError, OSError, ValueError) as error:
    print(f"pyunlock uninstaller: {error}", file=sys.stderr)
    sys.exit(1)
PY
