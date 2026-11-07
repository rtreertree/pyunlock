"""Shared read/validate/publish transaction for both PDF actions."""

import errno
import logging
import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from . import locker, unlocker
from .discovery import check_no_symlink
from .models import FileResult, InterruptedWithCleanup, PasswordInputError, ProcessingError


@contextmanager
def _quiet_pdf_logs() -> Iterator[None]:
    # Parser warnings may quote arbitrary document content. Emit only our fixed
    # messages, so even a malformed PDF cannot echo a supplied password.
    logger = logging.getLogger("pypdf")
    handlers, propagate = logger.handlers[:], logger.propagate
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    try:
        yield
    finally:
        logger.handlers, logger.propagate = handlers, propagate


def _snapshot(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _write_temporary(writer: PdfWriter, source: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=".pyunlock-", suffix=".pdf", dir=source.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Keep ownership with the caller if removal fails. In particular,
            # cleanup must never replace a KeyboardInterrupt with an OSError.
            exc._pyunlock_temporary = temporary
        raise


def _validate_output(path: Path, action: str, password: str, page_count: int) -> None:
    operation = locker if action == "lock" else unlocker
    operation.validate_output(path, password, page_count)


def _publish(temporary: Path, destination: Path, mode: str, source_stat: os.stat_result) -> None:
    if mode == "replace":
        check_no_symlink(destination)
        current = destination.lstat()
        if current.st_nlink != 1 or _snapshot(current) != _snapshot(source_stat):
            raise ProcessingError("source changed during processing; output not published")
        os.chmod(temporary, stat.S_IMODE(source_stat.st_mode) & 0o777)
        # Persist the final permission change before replacing the source.
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    else:
        # Hard-link publication is atomic and cannot clobber a racing creator.
        # A filesystem without hard-link support fails safely here.
        os.link(temporary, destination)


def _sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        if exc.errno in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            return  # Directory synchronization is unavailable on this filesystem.
        raise
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise
    finally:
        os.close(fd)


def process_pdf(
    source: Path,
    action: str,
    mode: str,
    password_provider: Callable[[], str],
) -> FileResult:
    """Process one input; never expose parser/crypto exception text.

    PasswordInputError and KeyboardInterrupt deliberately reach the CLI. Every
    other failure is a per-file result. Source and validator handles are closed
    before publication. Temporary files are cleaned even on interruption.
    """
    raw_source = Path(source)
    if not raw_source.is_absolute():
        raw_source = Path.cwd() / raw_source
    source = Path(os.path.abspath(source))
    temporary: Path | None = None
    destination = source if mode == "replace" else source.with_name(
        f"{source.stem}_{action}{source.suffix}"
    )
    published = False
    stage = "read"
    pending: KeyboardInterrupt | PasswordInputError | None = None
    cleanup_failed = False
    try:
        if action not in ("lock", "unlock") or mode not in ("replace", "new"):
            raise ProcessingError("invalid action or mode")
        check_no_symlink(raw_source)
        check_no_symlink(source)
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream, _quiet_pdf_logs():
            source_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ProcessingError("unsupported file type")
            if source_stat.st_nlink != 1:
                raise ProcessingError("multiply hard-linked files are not supported")
            reader = PdfReader(stream)
            if action == "unlock" and not reader.is_encrypted:
                result = FileResult(source, status="skip", message="already unlocked")
            else:
                if action == "lock" and reader.is_encrypted:
                    raise ProcessingError("already encrypted; unlock it first")
                # This saves work; atomic publication remains authoritative.
                if mode == "new" and os.path.lexists(destination):
                    raise ProcessingError("destination already exists")
                password = password_provider()
                operation = locker if action == "lock" else unlocker
                writer = operation.build_writer(reader, password)
                try:
                    page_count = len(reader.pages)
                    stage = "write"
                    temporary = _write_temporary(writer, source)
                    stage = "validate"
                    _validate_output(temporary, action, password, page_count)
                finally:
                    writer.close()
                result = None
        if result is None:
            stage = "publish"
            _publish(temporary, destination, mode, source_stat)
            published = True
            # A kill can leave the private temporary name, but the source is safe.
            temporary.unlink(missing_ok=True)
            temporary = None
            stage = "sync"
            _sync_directory(source.parent)
            result = FileResult(source, destination, "ok")
    except (KeyboardInterrupt, PasswordInputError) as exc:
        temporary = temporary or getattr(exc, "_pyunlock_temporary", None)
        pending = exc
    except Exception as exc:
        temporary = temporary or getattr(exc, "_pyunlock_temporary", None)
        if published:
            message = "output was published but durability could not be confirmed"
        elif isinstance(exc, ProcessingError):
            message = str(exc)
        elif isinstance(exc, FileExistsError):
            message = "destination already exists"
        elif isinstance(exc, PermissionError):
            message = "permission denied"
        elif isinstance(exc, FileNotFoundError):
            message = "source or output directory no longer exists"
        elif isinstance(exc, PdfReadError):
            message = "invalid or unreadable PDF"
        else:
            message = {
                "read": "cannot read or process PDF",
                "write": "could not write temporary PDF",
                "validate": "output validation failed",
                "publish": "could not publish output",
                "sync": "could not synchronize output directory",
            }[stage]
        if not published:
            message += "; original unchanged"
        result = FileResult(source, destination if published else None, "error", message)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
    if pending is not None:
        if cleanup_failed and isinstance(pending, KeyboardInterrupt):
            raise InterruptedWithCleanup(temporary.name) from None
        raise pending
    if cleanup_failed:
        message = (result.message + "; " if result.message else "") + (
            f"temporary cleanup failed; private temporary file remains beside source: {temporary.name}"
        )
        result = FileResult(source, destination if published else None, "error", message)
    return result

