import pytest
from pypdf import PdfReader

from pyunlock.locker import lock
from pyunlock.unlocker import unlock

from fixtures.factory import content_snapshot, encrypt_pdf, make_pdf


@pytest.mark.parametrize("mode", ["replace", "new"])
@pytest.mark.parametrize("password", ["new-password", "รหัสผ่าน-密碼-🔐", "  keep spaces  "])
def test_lock_requires_password_to_read_and_uses_aes256(tmp_path, mode, password):
    source = make_pdf(tmp_path / "report.final.PDF")
    original = source.read_bytes()
    expected = content_snapshot(source)

    result = lock(source, password, mode=mode)

    destination = source if mode == "replace" else tmp_path / "report.final_lock.PDF"
    assert result.status == "ok", result.message
    assert result.destination == destination
    with destination.open("rb") as stream:
        reader = PdfReader(stream)
        assert reader.is_encrypted
        encryption = reader.trailer["/Encrypt"]
        assert encryption["/V"] == 5
        assert encryption["/R"] == 6
        assert encryption["/Length"] == 256
        assert encryption["/CF"]["/StdCF"]["/CFM"] == "/AESV3"
        assert not reader.decrypt("")
        assert not reader.decrypt("different-password")
        with pytest.raises(Exception):
            len(reader.pages)
        assert reader.decrypt(password)
        assert len(reader.pages) == 2
    assert content_snapshot(destination, password) == expected
    if mode == "new":
        assert source.read_bytes() == original


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_empty_lock_password_rejected_before_writing(plain_pdf, mode):
    before = plain_pdf.read_bytes()

    result = lock(plain_pdf, "", mode=mode)

    assert result.status == "error"
    assert plain_pdf.read_bytes() == before
    assert not plain_pdf.with_name("report_lock.pdf").exists()
    assert not list(plain_pdf.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
@pytest.mark.parametrize("existing_password", ["existing-password", ""])
def test_already_encrypted_rejected_even_with_empty_open_password(
    tmp_path, mode, existing_password
):
    plain = make_pdf(tmp_path / "plain.pdf")
    source = encrypt_pdf(
        plain,
        tmp_path / "protected.pdf",
        password=existing_password,
        owner_password="separate-owner",
    )
    before = source.read_bytes()

    result = lock(source, "requested-new-password", mode=mode)

    assert result.status == "error"
    assert "already encrypted" in result.message.lower()
    assert "unlock it first" in result.message.lower()
    assert source.read_bytes() == before
    assert not source.with_name("protected_lock.pdf").exists()


def test_lock_suffix_appends_without_stripping_previous_suffix(tmp_path):
    source = make_pdf(tmp_path / "report_unlock.PDF")

    result = lock(source, "new-password", mode="new")

    assert result.status == "ok", result.message
    assert result.destination == tmp_path / "report_unlock_lock.PDF"


def test_existing_new_lock_destination_is_not_overwritten(plain_pdf):
    before = plain_pdf.read_bytes()
    destination = plain_pdf.with_name("report_lock.pdf")
    destination.write_bytes(b"Keep this unrelated file")

    result = lock(plain_pdf, "password", mode="new")

    assert result.status == "error"
    assert plain_pdf.read_bytes() == before
    assert destination.read_bytes() == b"Keep this unrelated file"
    assert not list(plain_pdf.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("lock_mode", ["replace", "new"])
@pytest.mark.parametrize("unlock_mode", ["replace", "new"])
def test_lock_unlock_round_trip_preserves_representative_content(
    rich_pdf, lock_mode, unlock_mode
):
    original_bytes = rich_pdf.read_bytes()
    expected = content_snapshot(rich_pdf)
    password = "roundtrip-รหัสผ่าน"

    locked = lock(rich_pdf, password, mode=lock_mode)
    assert locked.status == "ok", locked.message
    assert content_snapshot(locked.destination, password) == expected
    unlocked = unlock(locked.destination, password, mode=unlock_mode)

    assert unlocked.status == "ok", unlocked.message
    assert not PdfReader(unlocked.destination).is_encrypted
    assert content_snapshot(unlocked.destination) == expected
    if lock_mode == "new":
        assert rich_pdf.read_bytes() == original_bytes


def test_one_new_password_can_lock_multiple_inputs(tmp_path):
    sources = [make_pdf(tmp_path / name) for name in ("first.pdf", "second.PDF")]

    results = [lock(source, "shared-password", mode="new") for source in sources]

    assert [result.status for result in results] == ["ok", "ok"]
    for result in results:
        reader = PdfReader(result.destination)
        assert reader.is_encrypted
        assert reader.decrypt("shared-password")
        assert len(reader.pages) == 2


def test_corrupt_lock_input_preserves_original(tmp_path):
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken PDF")

    result = lock(source, "secret-must-not-appear")

    assert result.status == "error"
    assert "secret-must-not-appear" not in result.message
    assert source.read_bytes() == b"broken PDF"
    assert not list(tmp_path.glob(".pyunlock-*"))
