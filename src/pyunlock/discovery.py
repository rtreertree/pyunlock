"""Complete, deterministic input discovery without traversing symlinks."""

import os
import stat
from pathlib import Path
from collections.abc import Sequence

from .models import FileResult, ProcessingError


def check_no_symlink(path: Path) -> None:
    """Reject symlink components as well as a symlink at the final path."""
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ProcessingError("symlinks are not supported")


def discover(paths: Sequence[str | Path], recursive: bool = False) -> list[FileResult]:
    results: list[FileResult] = []
    seen: set[Path] = set()
    positions: dict[Path, int] = {}

    def add(path: Path, status: str = "ready", message: str = "", *, explicit: bool = False) -> None:
        if path not in seen:
            seen.add(path)
            positions[path] = len(results)
            results.append(FileResult(path, status=status, message=message))
        elif explicit and status == "error" and results[positions[path]].status == "skip":
            # An explicitly requested symlink is an error even if an earlier
            # folder selection discovered it as a skip. Keep one result.
            results[positions[path]] = FileResult(path, status=status, message=message)

    def inspect_file(path: Path, info: os.stat_result, explicit: bool) -> None:
        if not stat.S_ISREG(info.st_mode):
            if explicit:
                add(path, "error", "unsupported file type")
        elif path.suffix.lower() != ".pdf":
            if explicit:
                add(path, "error", "not a PDF file (.pdf extension required)")
        elif info.st_nlink != 1:
            add(path, "error", "multiply hard-linked files are not supported")
        else:
            add(path)

    def scan(directory: Path) -> tuple[list[tuple[Path, os.stat_result]], list[FileResult]]:
        files: list[tuple[Path, os.stat_result]] = []
        events: list[FileResult] = []
        try:
            # scandir errors must be reported, unlike glob's silent omissions.
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda item: item.name)
            for entry in children:
                path = Path(entry.path)
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        events.append(FileResult(path, status="skip", message="symlink ignored"))
                    elif stat.S_ISDIR(info.st_mode):
                        if recursive:
                            nested_files, nested_events = scan(path)
                            files.extend(nested_files)
                            events.extend(nested_events)
                    elif stat.S_ISREG(info.st_mode) and path.suffix.lower() == ".pdf":
                        files.append((path, info))
                except OSError:
                    events.append(FileResult(path, status="error", message="cannot inspect directory entry"))
        except OSError:
            events.append(FileResult(directory, status="error", message="cannot read directory"))
        return files, events

    for selected in paths:
        path = Path(os.path.abspath(os.fspath(selected)))
        try:
            # Check before abspath collapses '..': link/../file.pdf must never
            # hide a symlink component or select a different sibling file.
            raw = Path(selected)
            if not raw.is_absolute():
                raw = Path.cwd() / raw
            check_no_symlink(raw)
            check_no_symlink(path)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                files, events = scan(path)
                # Sort full discovered paths, including across subdirectories.
                for file, file_info in sorted(files, key=lambda item: str(item[0])):
                    inspect_file(file, file_info, False)
                for event in sorted(events, key=lambda item: str(item.source)):
                    add(event.source, event.status, event.message)
                if not files and not any(event.status == "error" for event in events):
                    add(path, "skip", "no PDFs found")
            else:
                inspect_file(path, info, True)
        except ProcessingError as exc:
            add(raw, "error", str(exc), explicit=True)
        except FileNotFoundError:
            add(path, "error", "path does not exist")
        except (OSError, ValueError):
            add(path, "error", "cannot inspect path")
    return results

