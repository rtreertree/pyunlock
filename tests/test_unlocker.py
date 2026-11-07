from pathlib import Path

import pytest
from pypdf import PdfReader

from pyunlock.unlocker import unlock

from fixtures.factory import content_snapshot, encrypt_pdf, make_pdf


@pytest.mark.parametrize("mode", ["replace", "new"])
@pytest.mark.parametrize(
    "algorithm", ["RC4-40", "RC4-128", "AES-128", "AES-256-R5", "AES-256"]
)
def test_unlock_supported_encryption_algorithms(tmp_path, mode, algorithm):
    plain = make_pdf(tmp_path / "plain.pdf")
    source = encrypt_pdf(plain, tmp_path / "protected.PDF", algorithm=algorithm)
    original = source.read_bytes()
    expected = content_snapshot(plain)

    result = unlock(source, "test-password", mode=mode)

    destination = source if mode == "replace" else tmp_path / "protected_unlock.PDF"
    assert result.status == "ok", result.message
    assert result.source == source
    assert result.destination == destination
    assert not PdfReader(destination).is_encrypted
    assert content_snapshot(destination) == expected
    if mode == "new":
        assert source.read_bytes() == original


@pytest.mark.parametrize("password", ["open-password", "owner-password"])
def test_unlock_accepts_user_and_owner_password(tmp_path, password):
    plain = make_pdf(tmp_path / "plain.pdf")
    source = encrypt_pdf(
        plain,
        tmp_path / "protected.pdf",
        password="open-password",
        owner_password="owner-password",
    )

    result = unlock(source, password)

    assert result.status == "ok", result.message
    assert not PdfReader(source).is_encrypted


def test_explicit_empty_unlock_password_is_allowed(tmp_path):
    plain = make_pdf(tmp_path / "plain.pdf")
    source = encrypt_pdf(
        plain,
        tmp_path / "empty-password.pdf",
        password="",
        owner_password="owner-only",
    )

    result = unlock(source, "")

    assert result.status == "ok", result.message
    assert not PdfReader(source).is_encrypted


def test_unicode_paths_password_and_prior_suffix_are_preserved(tmp_path):
    password = "รหัสผ่าน-密碼-🔐"
    plain = make_pdf(tmp_path / "plain.pdf")
    source = encrypt_pdf(
        plain, tmp_path / "เอกสาร.final_lock.PDF", password=password
    )
    original = source.read_bytes()

    result = unlock(source, password, mode="new")

    destination = tmp_path / "เอกสาร.final_lock_unlock.PDF"
    assert result.status == "ok", result.message
    assert result.destination == destination
    assert not PdfReader(destination).is_encrypted
    assert source.read_bytes() == original


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_wrong_unlock_password_preserves_source_and_hides_password(
    encrypted_pdf, mode
):
    before = encrypted_pdf.read_bytes()
    password = "never-display-this-wrong-password"

    result = unlock(encrypted_pdf, password, mode=mode)

    assert result.status == "error"
    assert "password" in result.message.lower()
    assert password not in result.message
    assert encrypted_pdf.read_bytes() == before
    assert not encrypted_pdf.with_name("protected_unlock.pdf").exists()
    assert not list(encrypted_pdf.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_already_unlocked_is_skip_without_rewrite(plain_pdf, mode):
    before = plain_pdf.read_bytes()
    previous_stat = plain_pdf.stat()

    result = unlock(plain_pdf, "unused-password", mode=mode)

    assert result.status == "skip"
    assert "already unlocked" in result.message.lower()
    assert plain_pdf.read_bytes() == before
    assert plain_pdf.stat().st_mtime_ns == previous_stat.st_mtime_ns
    assert not plain_pdf.with_name("report_unlock.pdf").exists()


def test_existing_new_destination_is_not_overwritten(encrypted_pdf):
    before = encrypted_pdf.read_bytes()
    destination = encrypted_pdf.with_name("protected_unlock.pdf")
    destination.write_bytes(b"Unrelated existing destination")

    result = unlock(encrypted_pdf, "test-password", mode="new")

    assert result.status == "error"
    assert encrypted_pdf.read_bytes() == before
    assert destination.read_bytes() == b"Unrelated existing destination"
    assert not list(encrypted_pdf.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_corrupt_pdf_is_error_without_modification(tmp_path, data):
    source = tmp_path / "invalid.pdf"
    source.write_bytes(data)

    result = unlock(source, "secret-not-in-errors")

    assert result.status == "error"
    assert "secret-not-in-errors" not in result.message
    assert source.read_bytes() == data
    assert not list(tmp_path.glob(".pyunlock-*"))


def test_representative_content_survives_unlock(rich_pdf):
    expected = content_snapshot(rich_pdf)
    source = encrypt_pdf(rich_pdf, rich_pdf.with_name("protected-rich.pdf"))

    result = unlock(source, "test-password")

    assert result.status == "ok", result.message
    assert content_snapshot(source) == expected
    assert expected["images"]
    assert expected["links"] == [(0, 1)]
    assert expected["outlines"] == ["Chapter One"]
    assert expected["forms"] == {"customer": "Ada Example"}
    assert expected["attachments"] == {"notes.txt": [b"Synthetic attachment\n"]}
