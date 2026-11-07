"""Add a guarded PATH entry to user-owned Bash/Zsh startup files."""

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


BEGIN = b"# >>> pyunlock PATH >>>"
END = b"# <<< pyunlock PATH <<<"
BLOCK = b'''# >>> pyunlock PATH >>>
case ":${PATH-}:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin${PATH:+:$PATH}" ;;
esac
# <<< pyunlock PATH <<<
'''


class ShellSetupError(Exception):
    """A safe, actionable failure without underlying exception text."""


@dataclass
class _StartupFile:
    path: Path
    original: bytes
    info: os.stat_result | None
    descriptor: int | None = None
    addition: bytes = b""
    written: bytes = b""
    created: bool = False


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _unchanged(info: os.stat_result, previous: os.stat_result) -> bool:
    return (_identity(info), info.st_size, info.st_mtime_ns) == (
        _identity(previous), previous.st_size, previous.st_mtime_ns
    )


def _safe_directory(path: Path) -> None:
    if not path.is_absolute():
        raise ShellSetupError("Shell configuration directory must be absolute.")
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ShellSetupError(f"Refusing a symlink in shell configuration path: {component}")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ShellSetupError(f"Shell configuration directory must be user-owned: {path}")


def _targets(home: Path, shell: str | None, zdotdir: str | None) -> list[Path]:
    name = Path(shell or "/bin/bash").name
    if name == "bash":
        login = next((home / name for name in (".bash_profile", ".bash_login", ".profile")
                      if os.path.lexists(home / name)), home / ".profile")
        return [home / ".bashrc", login]
    if name == "zsh":
        directory = Path(zdotdir) if zdotdir else home
        _safe_directory(directory)
        return [directory / ".zshrc", directory / ".zprofile"]
    raise ShellSetupError("Automatic PATH setup supports Bash and Zsh; select one with SHELL.")


def _open_existing(path: Path) -> _StartupFile:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1):
        raise ShellSetupError(f"Refusing an unsafe shell startup file: {path}")
    if not info.st_mode & 0o222:
        raise ShellSetupError(f"Shell startup file is not writable: {path}")
    flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if not _unchanged(current, info) or current.st_nlink != 1:
            raise ShellSetupError(f"Shell startup file changed during setup: {path}")
        original = os.pread(fd, info.st_size + 1, 0)
        if len(original) != info.st_size:
            raise ShellSetupError(f"Shell startup file changed during setup: {path}")
        return _StartupFile(path, original, info, fd)
    except BaseException:
        os.close(fd)
        raise


def _rollback(files: list[_StartupFile]) -> bool:
    complete = True
    for file in reversed(files):
        if file.descriptor is None or not (file.written or file.created):
            continue
        try:
            info = os.fstat(file.descriptor)
            expected = file.original + file.written
            # Preserve changes from another editor rather than truncating them.
            if (_identity(file.path.lstat()) != _identity(info)
                    or os.pread(file.descriptor, len(expected) + 1, 0) != expected):
                complete = False
                continue
            if file.created:
                file.path.unlink()
            else:
                os.ftruncate(file.descriptor, len(file.original))
                os.fsync(file.descriptor)
        except OSError:
            complete = False
    return complete


def configure_path(
    home: Path, shell: str | None = None, zdotdir: str | None = None,
) -> list[Path]:
    """Append one managed block, validating all files before any edit.

    Existing bytes, inode and permission bits are preserved. Failed appends are
    rolled back only while the files still contain exactly our own changes.
    """
    home = Path(home)
    files: list[_StartupFile] = []
    try:
        _safe_directory(home)
        targets = _targets(home, shell, zdotdir)
        for path in targets:
            file = _open_existing(path) if os.path.lexists(path) else _StartupFile(path, b"", None)
            files.append(file)
            if BEGIN in file.original or END in file.original:
                if (file.original.count(BEGIN) != 1 or file.original.count(END) != 1
                        or BLOCK not in file.original):
                    raise ShellSetupError(f"Managed PATH block is incomplete or edited; inspect {path}")
            else:
                file.addition = (b"\n" if file.original and not file.original.endswith(b"\n") else b"") + BLOCK

        # Opening all existing files above catches permissions and unsafe targets
        # before creating or appending anything.
        for file in files:
            if not file.addition:
                continue
            if file.descriptor is None:
                file.descriptor = os.open(file.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_APPEND,
                                          0o600)
                file.created = True
            else:
                current = file.path.lstat()
                if current.st_nlink != 1 or not _unchanged(current, file.info):
                    raise ShellSetupError(f"Shell startup file changed during setup: {file.path}")
            remaining = file.addition
            while remaining:
                count = os.write(file.descriptor, remaining)
                if count <= 0:
                    raise OSError("No progress writing shell configuration")
                file.written += remaining[:count]
                remaining = remaining[count:]
            os.fsync(file.descriptor)
        return [file.path for file in files if file.addition]
    except BaseException as exc:
        restored = _rollback(files)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if not restored:
            raise ShellSetupError("PATH setup failed and shell files changed during cleanup; inspect managed PATH blocks.") from None
        if isinstance(exc, ShellSetupError):
            raise
        raise ShellSetupError("Could not configure PATH; check shell startup file permissions. Previous contents were retained.") from None
    finally:
        for file in files:
            if file.descriptor is not None:
                os.close(file.descriptor)


def main() -> int:
    try:
        home = os.environ.get("HOME")
        if not home:
            raise ShellSetupError("HOME must name an existing absolute directory.")
        changed = configure_path(Path(home), os.environ.get("SHELL"), os.environ.get("ZDOTDIR"))
        for path in changed:
            print(f"Configured PATH: {path}")
        if not changed:
            print("PATH configuration is already installed.")
        return 0
    except ShellSetupError as exc:
        print(f"pyunlock PATH setup: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("pyunlock PATH setup: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
