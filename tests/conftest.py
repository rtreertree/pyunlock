from pathlib import Path

import pytest

from fixtures.factory import encrypt_pdf, make_pdf


@pytest.fixture
def plain_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "report.pdf")


@pytest.fixture
def rich_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "rich.pdf", rich=True)


@pytest.fixture
def encrypted_pdf(plain_pdf: Path) -> Path:
    return encrypt_pdf(plain_pdf, plain_pdf.with_name("protected.pdf"))
