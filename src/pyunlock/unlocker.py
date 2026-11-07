"""Document cloning and validation for known-password decryption."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import FileResult, ProcessingError


def build_writer(reader: PdfReader, password: str) -> PdfWriter:
    if not reader.decrypt(password):
        raise ProcessingError("incorrect password")
    return PdfWriter(clone_from=reader)


def validate_output(path: Path, password: str, page_count: int) -> None:
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted or len(reader.pages) != page_count:
            raise ProcessingError("decryption validation failed")
        # Resolve each page and content stream while the handle is still open.
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None:
                contents.get_data()


def unlock(source: Path, password: str, mode: str = "replace") -> FileResult:
    from .fileio import process_pdf

    return process_pdf(source, "unlock", mode, lambda: password)

