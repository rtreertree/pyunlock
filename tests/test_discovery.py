import os
from pathlib import Path

import pytest

from pyunlock.discovery import discover

from fixtures.factory import make_pdf


def ready_paths(results):
    return [result.source for result in results if result.status == "ready"]


def test_explicit_order_folder_sorting_uppercase_and_deduplication(tmp_path):
    folder = tmp_path / "reports"
    folder.mkdir()
    zed = make_pdf(folder / "z.PDF")
    alpha = make_pdf(folder / "a.pdf")
    first = make_pdf(tmp_path / "first.pdf")
    (folder / "notes.txt").write_text("not a PDF")

    results = discover([first, folder, alpha, folder / "." / "z.PDF", first])

    assert ready_paths(results) == [first, alpha, zed]
    assert len(results) == 3


def test_directories_are_shallow_unless_recursive(tmp_path):
    top = make_pdf(tmp_path / "top.pdf")
    nested = make_pdf(tmp_path / "nested" / "child.pdf")
    deeper = make_pdf(tmp_path / "nested" / "deep" / "another.PDF")

    assert ready_paths(discover([tmp_path])) == [top]
    assert ready_paths(discover([tmp_path], recursive=True)) == sorted(
        [top, nested, deeper]
    )


def test_overlapping_directories_do_not_repeat_inputs(tmp_path):
    first = make_pdf(tmp_path / "first.pdf")
    nested = make_pdf(tmp_path / "nested" / "child.pdf")

    results = discover([tmp_path, nested.parent, first], recursive=True)

    assert ready_paths(results) == sorted([first, nested])
    assert len(results) == 2


def test_relative_and_absolute_spellings_are_deduplicated(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "unicodé เอกสาร.PDF")
    monkeypatch.chdir(tmp_path)

    results = discover([path.name, path, Path(".") / path.name])

    assert ready_paths(results) == [path]


def test_discovery_snapshot_does_not_gain_new_outputs(tmp_path):
    source = make_pdf(tmp_path / "one.pdf")
    results = discover([tmp_path], recursive=True)
    make_pdf(tmp_path / "one_unlock.pdf")

    assert ready_paths(results) == [source]


def test_missing_and_explicit_non_pdf_are_errors_while_folder_non_pdf_is_ignored(
    tmp_path,
):
    text = tmp_path / "notes.txt"
    text.write_text("notes")
    missing = tmp_path / "missing.pdf"
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "ignored.txt").write_text("ignored")

    results = discover([text, missing, folder])

    assert [result.status for result in results] == ["error", "error", "skip"]
    assert all(result.message for result in results)


def test_empty_folder_is_skip(tmp_path):
    results = discover([tmp_path])

    assert len(results) == 1
    assert results[0].status == "skip"
    assert "empty" in results[0].message.lower() or "no pdf" in results[0].message.lower()


@pytest.mark.parametrize("directory", [False, True])
def test_explicit_symlinks_are_errors_and_discovered_symlinks_are_skips(
    tmp_path, directory
):
    target = tmp_path / "target"
    if directory:
        target.mkdir()
        make_pdf(target / "secret.pdf")
    else:
        target = make_pdf(tmp_path / "target.pdf")
    selected = tmp_path / "selected"
    selected.mkdir()
    link = selected / ("linked" if directory else "linked.pdf")
    link.symlink_to(target, target_is_directory=directory)

    explicit = discover([link], recursive=True)
    found = discover([selected], recursive=True)

    assert len(explicit) == 1
    assert explicit[0].status == "error"
    assert any(result.source == link and result.status == "skip" for result in found)
    assert not ready_paths(found)


def test_dangling_symlink_is_error(tmp_path):
    path = tmp_path / "dangling.pdf"
    path.symlink_to(tmp_path / "missing.pdf")

    results = discover([path])

    assert len(results) == 1
    assert results[0].status == "error"


def test_symlink_ancestor_is_rejected(tmp_path):
    target = tmp_path / "real"
    source = make_pdf(target / "file.pdf")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    results = discover([alias / source.name])

    assert len(results) == 1
    assert results[0].status == "error"
    assert not ready_paths(results)


def test_multiply_hardlinked_input_is_rejected(tmp_path):
    source = make_pdf(tmp_path / "original.pdf")
    alias = tmp_path / "hardlink.pdf"
    os.link(source, alias)

    results = discover([source, alias])

    assert [result.status for result in results] == ["error", "error"]
    assert all("link" in result.message.lower() for result in results)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO support required")
def test_unsupported_file_type_is_error(tmp_path):
    fifo = tmp_path / "stream.pdf"
    os.mkfifo(fifo)

    results = discover([fifo])

    assert len(results) == 1
    assert results[0].status == "error"


def test_unreadable_directory_is_error(tmp_path):
    directory = tmp_path / "unreadable"
    directory.mkdir()
    make_pdf(directory / "hidden.pdf")
    directory.chmod(0)
    try:
        if os.access(directory, os.R_OK | os.X_OK):
            pytest.skip("Current user bypasses filesystem permission bits")
        results = discover([directory])
        assert len(results) == 1
        assert results[0].status == "error"
    finally:
        directory.chmod(0o700)
