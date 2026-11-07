import errno
import os
import stat
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from pyunlock import fileio

from fixtures.factory import encrypt_pdf, make_pdf


@pytest.fixture(params=["unlock", "lock"])
def operation(request, tmp_path):
    action = request.param
    plain = make_pdf(tmp_path / "plain.pdf")
    source = (
        encrypt_pdf(plain, tmp_path / "protected.pdf")
        if action == "unlock"
        else plain
    )
    return action, source, "test-password"


def run(operation, mode="replace"):
    action, source, password = operation
    return fileio.process_pdf(source, action, mode, lambda: password)


def assert_failure_untouched(result, source, before):
    assert result.status == "error", result.message
    assert source.read_bytes() == before
    assert not list(source.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_incomplete_writer_failure_preserves_source_and_cleans_temporary(
    operation, mode, monkeypatch
):
    _, source, password = operation
    before = source.read_bytes()

    def partial_write(writer, stream):
        stream.write(b"partial output")
        raise OSError(f"injected write failure containing {password}")

    monkeypatch.setattr(fileio.PdfWriter, "write", partial_write)

    result = run(operation, mode)

    assert_failure_untouched(result, source, before)
    assert password not in result.message


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_validation_failure_preserves_source_and_cleans_temporary(
    operation, mode, monkeypatch
):
    _, source, password = operation
    before = source.read_bytes()

    def reject_output(*args, **kwargs):
        raise ValueError(f"injected validation failure containing {password}")

    monkeypatch.setattr(fileio, "_validate_output", reject_output)

    result = run(operation, mode)

    assert_failure_untouched(result, source, before)
    assert password not in result.message


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_publication_failure_preserves_source_and_cleans_temporary(
    operation, mode, monkeypatch
):
    _, source, password = operation
    before = source.read_bytes()

    def reject_publication(*args, **kwargs):
        raise OSError(f"injected publication failure containing {password}")

    monkeypatch.setattr(fileio, "_publish", reject_publication)

    result = run(operation, mode)

    assert_failure_untouched(result, source, before)
    assert password not in result.message


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_temporary_fsync_failure_preserves_source(operation, mode, monkeypatch):
    _, source, _ = operation
    before = source.read_bytes()

    def fail_sync(fd):
        raise OSError("injected synchronization failure")

    monkeypatch.setattr(fileio.os, "fsync", fail_sync)

    result = run(operation, mode)

    assert_failure_untouched(result, source, before)


def test_temporary_is_in_source_folder_and_owner_only_until_validated(
    operation, monkeypatch
):
    _, source, _ = operation
    validate = fileio._validate_output
    seen = []

    def inspect_temporary(path, *args, **kwargs):
        assert path != source
        assert path.parent == source.parent
        assert path.name.startswith(".pyunlock-")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        seen.append(path)
        return validate(path, *args, **kwargs)

    monkeypatch.setattr(fileio, "_validate_output", inspect_temporary)

    result = run(operation)

    assert result.status == "ok", result.message
    assert seen
    assert not seen[0].exists()


def test_replace_preserves_ordinary_permission_bits(operation):
    _, source, _ = operation
    source.chmod(0o640)

    result = run(operation)

    assert result.status == "ok", result.message
    assert stat.S_IMODE(source.stat().st_mode) == 0o640


def test_new_output_retains_owner_only_permissions(operation):
    _, source, _ = operation
    source.chmod(0o644)

    result = run(operation, "new")

    assert result.status == "ok", result.message
    assert stat.S_IMODE(result.destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(source.stat().st_mode) == 0o644


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_keyboard_interrupt_during_write_cleans_temporary(
    operation, mode, monkeypatch
):
    _, source, _ = operation
    before = source.read_bytes()

    def interrupt_write(writer, stream):
        stream.write(b"interrupted output")
        raise KeyboardInterrupt

    monkeypatch.setattr(fileio.PdfWriter, "write", interrupt_write)

    with pytest.raises(KeyboardInterrupt):
        run(operation, mode)

    assert source.read_bytes() == before
    assert not list(source.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_keyboard_interrupt_during_validation_cleans_temporary(
    operation, mode, monkeypatch
):
    _, source, _ = operation
    before = source.read_bytes()

    def interrupt_validation(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(fileio, "_validate_output", interrupt_validation)

    with pytest.raises(KeyboardInterrupt):
        run(operation, mode)

    assert source.read_bytes() == before
    assert not list(source.parent.glob(".pyunlock-*"))


def test_new_destination_created_concurrently_is_never_overwritten(
    operation, monkeypatch
):
    _, source, _ = operation
    before = source.read_bytes()
    link = fileio.os.link
    sentinel = b"A concurrent process created this destination"

    def concurrent_link(temporary, destination, *args, **kwargs):
        destination.write_bytes(sentinel)
        return link(temporary, destination, *args, **kwargs)

    monkeypatch.setattr(fileio.os, "link", concurrent_link)

    result = run(operation, "new")

    assert_failure_untouched(result, source, before)
    assert source.with_name(f"{source.stem}_{operation[0]}{source.suffix}").read_bytes() == sentinel


def test_new_mode_requires_atomic_nonoverwriting_publication(operation, monkeypatch):
    _, source, _ = operation
    before = source.read_bytes()

    def unsupported_link(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "hard links unsupported")

    monkeypatch.setattr(fileio.os, "link", unsupported_link)

    result = run(operation, "new")

    assert_failure_untouched(result, source, before)
    assert not source.with_name(f"{source.stem}_{operation[0]}{source.suffix}").exists()


def test_replace_detects_concurrent_source_content_change(operation, monkeypatch):
    _, source, _ = operation
    validate = fileio._validate_output
    external_bytes = b"An external editor changed this source after it was read"

    def change_after_validation(*args, **kwargs):
        result = validate(*args, **kwargs)
        source.write_bytes(external_bytes)
        return result

    monkeypatch.setattr(fileio, "_validate_output", change_after_validation)

    result = run(operation)

    assert result.status == "error"
    assert "chang" in result.message.lower()
    assert source.read_bytes() == external_bytes
    assert not list(source.parent.glob(".pyunlock-*"))


def test_replace_detects_concurrent_source_identity_change(operation, monkeypatch):
    _, source, _ = operation
    validate = fileio._validate_output
    moved = source.with_name("external-original.pdf")
    original_bytes = source.read_bytes()
    replacement_bytes = b"Different inode with independently owned bytes"

    def substitute_after_validation(*args, **kwargs):
        result = validate(*args, **kwargs)
        source.rename(moved)
        source.write_bytes(replacement_bytes)
        return result

    monkeypatch.setattr(fileio, "_validate_output", substitute_after_validation)

    result = run(operation)

    assert result.status == "error"
    assert source.read_bytes() == replacement_bytes
    assert moved.read_bytes() == original_bytes
    assert not list(source.parent.glob(".pyunlock-*"))


def test_replace_detects_symlink_substitution(operation, monkeypatch):
    _, source, _ = operation
    validate = fileio._validate_output
    moved = source.with_name("external-original.pdf")
    outside = make_pdf(source.parent / "outside.pdf")
    original_bytes = source.read_bytes()
    outside_bytes = outside.read_bytes()

    def substitute_after_validation(*args, **kwargs):
        result = validate(*args, **kwargs)
        source.rename(moved)
        source.symlink_to(outside)
        return result

    monkeypatch.setattr(fileio, "_validate_output", substitute_after_validation)

    result = run(operation)

    assert result.status == "error"
    assert source.is_symlink()
    assert outside.read_bytes() == outside_bytes
    assert moved.read_bytes() == original_bytes
    assert not list(source.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_postpublication_sync_failure_reports_published_output(
    operation, mode, monkeypatch
):
    action, source, password = operation
    original = source.read_bytes()

    def fail_directory_sync(path):
        raise OSError("injected directory synchronization failure")

    monkeypatch.setattr(fileio, "_sync_directory", fail_directory_sync)

    result = run(operation, mode)

    assert result.status == "error"
    assert "published" in result.message.lower()
    assert "durability" in result.message.lower()
    destination = source if mode == "replace" else source.with_name(
        f"{source.stem}_{action}{source.suffix}"
    )
    assert destination.exists()
    reader = PdfReader(destination)
    if action == "lock":
        assert reader.is_encrypted
        assert reader.decrypt(password)
    else:
        assert not reader.is_encrypted
    assert len(reader.pages) == 2
    if mode == "new":
        assert source.read_bytes() == original
    assert not list(source.parent.glob(".pyunlock-*"))


@pytest.mark.parametrize("mode", ["replace", "new"])
@pytest.mark.parametrize("invalid_output", ["corrupt", "page_count", "protection"])
def test_real_output_validation_rejects_invalid_documents_before_publication(
    operation, mode, invalid_output, monkeypatch
):
    action, source, password = operation
    before = source.read_bytes()
    write = fileio._write_temporary

    def write_invalid(writer, source_path):
        temporary = write(writer, source_path)
        if invalid_output == "corrupt":
            temporary.write_bytes(b"not a valid output PDF")
            return temporary
        substitute = PdfWriter()
        substitute.add_blank_page(width=300, height=300)
        if invalid_output != "page_count":
            substitute.add_blank_page(width=300, height=300)
        if action == "unlock" and invalid_output == "protection":
            substitute.encrypt(password, password, algorithm="AES-256")
        elif action == "lock" and invalid_output == "page_count":
            substitute.encrypt(password, password, algorithm="AES-256")
        # The protection-invalid lock case intentionally remains unencrypted.
        with temporary.open("wb") as stream:
            substitute.write(stream)
        return temporary

    monkeypatch.setattr(fileio, "_write_temporary", write_invalid)

    result = run(operation, mode)

    assert_failure_untouched(result, source, before)


@pytest.mark.parametrize("wrong_password", ["", "different-new-password"])
def test_lock_validation_rejects_empty_or_wrong_open_password(
    plain_pdf, wrong_password, monkeypatch
):
    before = plain_pdf.read_bytes()
    write = fileio._write_temporary

    def write_with_wrong_password(writer, source):
        temporary = write(writer, source)
        replacement = PdfWriter()
        replacement.add_blank_page(width=300, height=300)
        replacement.add_blank_page(width=300, height=300)
        replacement.encrypt(
            wrong_password, "owner-password", algorithm="AES-256"
        )
        with temporary.open("wb") as stream:
            replacement.write(stream)
        return temporary

    monkeypatch.setattr(fileio, "_write_temporary", write_with_wrong_password)

    result = fileio.process_pdf(
        plain_pdf, "lock", "replace", lambda: "intended-password"
    )

    assert_failure_untouched(result, plain_pdf, before)


@pytest.mark.parametrize("action", ["unlock", "lock"])
def test_pdf_layer_rejects_symlink_even_if_discovery_is_bypassed(
    action, tmp_path
):
    plain = make_pdf(tmp_path / "plain.pdf")
    source = (
        encrypt_pdf(plain, tmp_path / "protected.pdf")
        if action == "unlock"
        else plain
    )
    original = source.read_bytes()
    alias = tmp_path / "alias.pdf"
    alias.symlink_to(source)

    result = fileio.process_pdf(alias, action, "replace", lambda: "test-password")

    assert result.status == "error"
    assert alias.is_symlink()
    assert source.read_bytes() == original


def test_password_provider_is_lazy_for_ineligible_inputs(plain_pdf, encrypted_pdf):
    def should_not_prompt():
        raise AssertionError("No password should be needed for an ineligible input")

    unlocked = fileio.process_pdf(plain_pdf, "unlock", "new", should_not_prompt)
    locked = fileio.process_pdf(encrypted_pdf, "lock", "new", should_not_prompt)

    assert unlocked.status == "skip"
    assert locked.status == "error"
    assert "already encrypted" in locked.message.lower()


def test_all_source_and_validation_handles_close_before_publication(
    operation, monkeypatch
):
    streams = []
    path_open = Path.open
    fd_open = fileio.os.fdopen
    publish = fileio._publish

    def tracked_path_open(path, *args, **kwargs):
        stream = path_open(path, *args, **kwargs)
        streams.append(stream)
        return stream

    def tracked_fd_open(*args, **kwargs):
        stream = fd_open(*args, **kwargs)
        streams.append(stream)
        return stream

    def assert_closed_before_publish(*args, **kwargs):
        assert streams
        assert all(stream.closed for stream in streams)
        return publish(*args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_path_open)
    monkeypatch.setattr(fileio.os, "fdopen", tracked_fd_open)
    monkeypatch.setattr(fileio, "_publish", assert_closed_before_publish)

    result = run(operation)

    assert result.status == "ok", result.message


def test_hardlinked_input_is_rejected_if_discovery_is_bypassed(operation):
    _, source, _ = operation
    before = source.read_bytes()
    alias = source.with_name("hardlinked-alias.pdf")
    os.link(source, alias)

    result = run(operation)

    assert_failure_untouched(result, source, before)
    assert alias.read_bytes() == before


def test_unreadable_source_preserves_bytes(operation):
    _, source, _ = operation
    before = source.read_bytes()
    previous_mode = stat.S_IMODE(source.stat().st_mode)
    source.chmod(0)
    try:
        if os.access(source, os.R_OK):
            pytest.skip("Current user bypasses filesystem permission bits")
        result = run(operation)
        assert result.status == "error"
        assert "permission" in result.message.lower()
    finally:
        source.chmod(previous_mode)
    assert source.read_bytes() == before


@pytest.mark.parametrize("mode", ["replace", "new"])
def test_unwritable_source_directory_preserves_original(operation, mode):
    _, source, _ = operation
    before = source.read_bytes()
    directory = source.parent
    previous_mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0o500)
    try:
        if os.access(directory, os.W_OK):
            pytest.skip("Current user bypasses filesystem permission bits")
        result = run(operation, mode)
        assert result.status == "error"
        assert "permission" in result.message.lower()
    finally:
        directory.chmod(previous_mode)
    assert source.read_bytes() == before
    assert not list(directory.glob(".pyunlock-*"))


def test_cleanup_failure_is_a_password_free_result_before_publication(
    operation, monkeypatch
):
    _, source, password = operation
    before = source.read_bytes()
    unlink = Path.unlink

    def reject_validation(*args, **kwargs):
        raise ValueError(f"injected validation failure {password}")

    def fail_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith(".pyunlock-"):
            raise PermissionError(f"injected cleanup failure {password}")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fileio, "_validate_output", reject_validation)
        patch.setattr(Path, "unlink", fail_temporary_unlink)
        result = run(operation)

    assert result.status == "error"
    assert password not in result.message
    assert "temporar" in result.message.lower() or "cleanup" in result.message.lower()
    assert source.read_bytes() == before
    leftovers = list(source.parent.glob(".pyunlock-*"))
    assert leftovers
    for temporary in leftovers:
        assert stat.S_IMODE(temporary.stat().st_mode) == 0o600
        temporary.unlink()


def test_cleanup_failure_after_new_publication_reports_published_output(
    operation, monkeypatch
):
    action, source, password = operation
    before = source.read_bytes()
    unlink = Path.unlink

    def fail_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith(".pyunlock-"):
            raise PermissionError(f"injected cleanup failure {password}")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_temporary_unlink)
        result = run(operation, "new")

    assert result.status == "error"
    assert "published" in result.message.lower()
    assert password not in result.message
    assert source.read_bytes() == before
    destination = source.with_name(f"{source.stem}_{action}{source.suffix}")
    reader = PdfReader(destination)
    if action == "lock":
        assert reader.decrypt(password)
    assert len(reader.pages) == 2
    for temporary in source.parent.glob(".pyunlock-*"):
        temporary.unlink()


def test_actual_replace_failure_preserves_source(operation, monkeypatch):
    _, source, _ = operation
    before = source.read_bytes()

    def failed_replace(*args, **kwargs):
        raise OSError("injected atomic replacement failure")

    monkeypatch.setattr(fileio.os, "replace", failed_replace)

    result = run(operation)

    assert_failure_untouched(result, source, before)


def test_cleanup_failure_during_interrupted_write_preserves_interrupt(
    operation, monkeypatch
):
    _, source, password = operation
    before = source.read_bytes()
    unlink = Path.unlink

    def interrupt_write(writer, stream):
        stream.write(b"interrupted temporary output")
        raise KeyboardInterrupt

    def fail_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith(".pyunlock-"):
            raise PermissionError(f"injected cleanup failure {password}")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fileio.PdfWriter, "write", interrupt_write)
        patch.setattr(Path, "unlink", fail_temporary_unlink)
        with pytest.raises(KeyboardInterrupt):
            run(operation)

    assert source.read_bytes() == before
    for temporary in source.parent.glob(".pyunlock-*"):
        temporary.unlink()
