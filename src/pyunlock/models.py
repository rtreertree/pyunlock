"""Password-free results and expected errors shared by application layers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class FileResult:
    source: Path
    destination: Path | None = None
    status: Literal["ready", "ok", "skip", "error"] = "ready"
    message: str = ""


class ProcessingError(Exception):
    """An expected error with a fixed, safe-to-display message."""


class PasswordInputError(Exception):
    """Invalid lock password or confirmation; abort the invocation with code 2."""


class InterruptedWithCleanup(KeyboardInterrupt):
    """An interruption whose private temporary file could not be removed."""

    def __init__(self, temporary_name: str):
        self.temporary_name = temporary_name

