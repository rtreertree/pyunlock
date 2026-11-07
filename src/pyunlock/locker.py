"""Explicit AES-256 encryption and opening-password validation."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import FileResult, ProcessingError


def build_writer(reader: PdfReader, password: str) -> PdfWriter:
    if not password:
        raise ProcessingError("locking requires a nonempty password")
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    return writer


def validate_output(path: Path, password: str, page_count: int) -> None:
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if not reader.is_encrypted or reader.decrypt(""):
            raise ProcessingError("encryption validation failed: opening password is not protected")
        if not reader.decrypt(password) or len(reader.pages) != page_count:
            raise ProcessingError("encryption validation failed")
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None:
                contents.get_data()


def lock(source: Path, password: str, mode: str = "replace") -> FileResult:
    from .fileio import process_pdf

    return process_pdf(source, "lock", mode, lambda: password)

