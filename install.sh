#!/bin/bash
# Installs into the current user's home; never run with sudo.
set -euo pipefail

PYUNLOCK_PYTHON="${PYUNLOCK_PYTHON:-python3}"
command -v "$PYUNLOCK_PYTHON" >/dev/null 2>&1 || {
    printf '%s\n' 'pyunlock installer: Install Python 3.11+ or set PYUNLOCK_PYTHON to its executable.' >&2
    exit 1
}

exec "$PYUNLOCK_PYTHON" - <<'PY'
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "pyunlock-install-v1"
REPOSITORY = os.environ.get("PYUNLOCK_REPO", "rtreertree/pyunlock")
REFERENCE = os.environ.get("PYUNLOCK_REF", "main")


class InstallError(Exception):
    pass


class Terminated(BaseException):
    pass


def fail(message):
    raise InstallError(message)


def exists(path):
    return os.path.lexists(path)


def owned_directory(path, create=False):
    if not exists(path):
        if not create:
            return
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        fail(f"Refusing a symlink, non-directory, or directory owned by another user: {path}")


def check_layout(home, create=False):
    owned_directory(home)
    if not home.is_dir():
        fail("HOME must be an existing directory.")
    for path in (home / ".local", home / ".local/share", home / ".local/bin"):
        owned_directory(path, create)


def check_root(root):
    if not exists(root):
        return
    owned_directory(root)
    marker = root / ".pyunlock-managed"
    if not exists(marker):
        fail(f"Existing application directory is not a managed pyunlock installation: {root}")
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        fail(f"Refusing an unsafe installation marker: {marker}")
    try:
        content = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        fail(f"Cannot read installation marker: {marker}")
    if content not in (MARKER, MARKER + "\n"):
        fail(f"Unrecognized installation marker: {marker}")
    owned_directory(root / "envs")


def managed_command(command, root):
    if not exists(command):
        return None
    info = command.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        fail(f"Refusing to overwrite an unrelated command: {command}")
    raw_target = os.readlink(command)
    target = Path(raw_target)
    name = target.parent.parent.name
    expected = root / "envs" / name / "bin" / "pyunlock"
    if not target.is_absolute() or not name or name in (".", "..") or raw_target != str(expected):
        fail(f"Command does not point to a managed environment: {command}")
    # A path-shaped link must not disguise an external environment through symlinks.
    for directory in (root / "envs" / name, root / "envs" / name / "bin"):
        owned_directory(directory)
    return (info.st_dev, info.st_ino, info.st_mtime_ns, raw_target)


def checked_run(arguments, explanation):
    environment = os.environ.copy()
    environment.update(PIP_NO_INPUT="1", GIT_TERMINAL_PROMPT="0")
    if subprocess.run(arguments, check=False, env=environment).returncode:
        fail(explanation)


def install():
    if sys.version_info < (3, 11):
        fail("Python 3.11 or newer is required.")
    if sys.platform not in ("darwin", "linux"):
        fail("This installer supports macOS and Linux.")
    if not os.environ.get("HOME") or not Path(os.environ["HOME"]).is_absolute():
        fail("HOME must name an absolute directory.")
    home = Path(os.environ["HOME"])
    root, bin_dir = home / ".local/share/pyunlock", home / ".local/bin"
    command = bin_dir / "pyunlock"
    local_source = os.environ.get("PYUNLOCK_SOURCE")
    if local_source:
        source = Path(local_source)
        if not source.is_absolute() or not source.exists() or not (
            source.is_file() and source.suffix == ".whl"
            or source.is_dir() and (source / "pyproject.toml").is_file()
        ):
            fail("PYUNLOCK_SOURCE must be an absolute path to a local wheel or pyunlock checkout.")
        package = str(source)
    else:
        if REPOSITORY.startswith("YOUR_GITHUB_USERNAME/"):
            fail("Set PYUNLOCK_REPO to the real GitHub owner/repository; YOUR_GITHUB_USERNAME is a placeholder.")
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", REPOSITORY):
            fail("PYUNLOCK_REPO must be a GitHub owner/repository.")
        if not REFERENCE or any(character.isspace() for character in REFERENCE) or "#" in REFERENCE or "@" in REFERENCE:
            fail("PYUNLOCK_REF must be a nonempty Git branch, tag, or commit without whitespace, #, or @.")
        if not shutil.which("git"):
            fail("Install Git, then rerun this installer.")
        package = f"git+https://github.com/{REPOSITORY}.git@{REFERENCE}"

    check_layout(home)
    check_root(root)
    previous = managed_command(command, root)
    check_layout(home, create=True)
    if not exists(root):
        root.mkdir(mode=0o700)
        try:
            with (root / ".pyunlock-managed").open("x", encoding="utf-8") as marker:
                marker.write(MARKER + "\n")
        except BaseException:
            try:
                root.rmdir()
            except OSError:
                pass
            raise
    owned_directory(root / "envs", create=True)
    environment = Path(tempfile.mkdtemp(prefix="install.", dir=root / "envs"))
    stage = None
    try:
        checked_run([sys.executable, "-m", "venv", str(environment)],
                    "Python venv/pip support is unavailable. Install it, then retry.")
        python = str(environment / "bin/python")
        checked_run([python, "-m", "pip", "--version"],
                    "The new environment has no working pip; install Python venv/pip support.")
        checked_run([python, "-m", "pip", "install", package],
                    "Package installation failed; the previous command was preserved. Check the repository/ref, network, or local source.")
        checked_run([python, "-m", "pip", "check"], "Package dependency verification failed; the previous command was preserved.")
        checked_run([str(environment / "bin/pyunlock"), "--version"],
                    "The installed command failed verification; the previous command was preserved.")
        checked_run([python, "-m", "pyunlock", "--version"],
                    "The installed Python module failed verification; the previous command was preserved.")

        # Revalidate after preparing the environment, before changing the public command.
        check_layout(home)
        check_root(root)
        if managed_command(command, root) != previous:
            fail("The command changed during installation; refusing to replace it. Concurrent installation is unsupported.")
        stage = Path(tempfile.mkdtemp(prefix=".pyunlock.", dir=bin_dir))
        temporary = stage / "pyunlock"
        temporary.symlink_to(environment / "bin/pyunlock")
        if previous is None:
            # Unlike replace(), link() cannot overwrite a concurrently created command.
            os.link(temporary, command, follow_symlinks=False)
            temporary.unlink()
        else:
            os.replace(temporary, command)
        print(f"Installed: {command}")
        if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
            print('Add this line to ~/.zshrc or ~/.bashrc, then open a new terminal:')
            print('export PATH="$HOME/.local/bin:$PATH"')
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        # A signal immediately after publication must retain the now-active environment.
        try:
            active = command.is_symlink() and os.readlink(command) == str(environment / "bin/pyunlock")
        except OSError:
            active = False
        if not active:
            shutil.rmtree(environment, ignore_errors=True)


def terminate(signum, frame):
    raise Terminated()


signal.signal(signal.SIGTERM, terminate)
os.umask(0o077)
try:
    install()
except KeyboardInterrupt:
    print("pyunlock installer: Interrupted; the active installation was retained.", file=sys.stderr)
    sys.exit(130)
except Terminated:
    print("pyunlock installer: Terminated; the active installation was retained.", file=sys.stderr)
    sys.exit(143)
except (InstallError, OSError, ValueError) as error:
    print(f"pyunlock installer: {error}", file=sys.stderr)
    sys.exit(1)
PY
