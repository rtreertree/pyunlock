"""Command-line parsing, private password prompts, and batch reporting."""

import argparse
import getpass
import sys
import warnings
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .discovery import discover
from .fileio import process_pdf
from .models import FileResult, InterruptedWithCleanup, PasswordInputError, ProcessingError


def _display(path: Path) -> str:
    # Escape control/format characters (including terminal escape sequences).
    import unicodedata

    return "".join(
        char if not unicodedata.category(char).startswith("C") and char not in "\u2028\u2029" else
        (f"\\x{ord(char):02x}" if ord(char) <= 255 else f"\\u{ord(char):04x}")
        for char in str(path)
    )


class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's messages can echo unrecognized argv, including passwords
        # after a typo. Usage shows valid options without printing user values.
        self.print_usage(sys.stderr)
        self.exit(2, "pyunlock: error: invalid arguments; check -f PATH and option values (see --help)\n")


def _parser() -> argparse.ArgumentParser:
    parser = _PrivateArgumentParser(
        prog="pyunlock",
        description="Lock and unlock PDFs locally with a password.",
        epilog=("Examples:\n"
                "  pyunlock -f invoice.pdf -p 'password'\n"
                "  pyunlock -f invoice.pdf ./reports -m new -r\n"
                "  pyunlock -a lock -f invoice.pdf -m new\n\n"
                "Omit -p for a private prompt. Command-line passwords may appear in\n"
                "shell history and process arguments. Prefix hyphenated paths with ./;\n"
                "use --password='-secret' for a password beginning with a hyphen."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-f", "--files", nargs="+", action="extend", required=True,
                        metavar="PATH", help="PDF files or folders; may be repeated")
    parser.add_argument("-a", "--action", choices=("unlock", "lock"), default="unlock",
                        help="operation (default: unlock)")
    parser.add_argument("-p", "--password", help="password shared by the batch (default: prompt)")
    parser.add_argument("-m", "--mode", choices=("replace", "new"), default="replace",
                        help="output mode (default: replace)")
    parser.add_argument("-r", "--recursive", action="store_true", help="include PDFs in subfolders")
    parser.add_argument("--version", action="version", version=f"pyunlock {__version__}")
    return parser


def _password_provider(action: str, supplied: str | None):
    password = supplied

    def obtain() -> str:
        nonlocal password
        if password is not None:
            return password
        if not sys.stdin.isatty():
            raise ProcessingError("password required; use -p or an interactive terminal")
        try:
            # Never allow getpass's echoing fallback if no controlling terminal is
            # available even though stdin appeared interactive.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                answer = getpass.getpass("New password: " if action == "lock" else "Password: ")
                if action == "lock":
                    if not answer:
                        raise PasswordInputError("locking requires a nonempty password")
                    confirmation = getpass.getpass("Confirm new password: ")
                    if answer != confirmation:
                        raise PasswordInputError("password confirmation does not match")
        except (EOFError, OSError, getpass.GetPassWarning):
            raise ProcessingError("password could not be read privately; use -p or an interactive terminal") from None
        password = answer
        return password

    return obtain


def _render(result: FileResult, action: str) -> None:
    source = _display(result.source)
    if result.status == "ok":
        suffix = " (locked)" if action == "lock" else ""
        print(f"OK    {source} -> {_display(result.destination)}{suffix}")
    elif result.status == "skip":
        print(f"SKIP  {source}: {result.message}")
    else:
        print(f"ERROR {source}: {result.message}", file=sys.stderr)


def _summary(counts: Counter[str], action: str) -> None:
    operation = "locked" if action == "lock" else "unlocked"
    print(f"\nDone: {counts['ok']} {operation}, {counts['skip']} skipped, {counts['error']} failed.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if options.action == "lock" and options.password == "":
        print("ERROR locking requires a nonempty password", file=sys.stderr)
        return 2
    counts: Counter[str] = Counter()
    try:
        inputs = discover(options.files, options.recursive)
        eligible = sum(result.status == "ready" for result in inputs)
        password_provider = _password_provider(options.action, options.password)
        for item in inputs:
            result = process_pdf(item.source, options.action, options.mode, password_provider) if item.status == "ready" else item
            _render(result, options.action)
            counts[result.status] += 1
        if not eligible:
            print("ERROR no eligible PDFs found", file=sys.stderr)
    except PasswordInputError as exc:
        print(f"ERROR {exc}; no PDFs written", file=sys.stderr)
        return 2
    except KeyboardInterrupt as exc:
        print("\nERROR interrupted; previously completed files remain completed", file=sys.stderr)
        if isinstance(exc, InterruptedWithCleanup):
            print(f"ERROR temporary cleanup failed; private temporary file remains beside source: {exc.temporary_name}", file=sys.stderr)
        _summary(counts, options.action)
        return 130
    _summary(counts, options.action)
    return 1 if counts["error"] or not eligible else 0
