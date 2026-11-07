"""Exercise the public command, including installed entry points and prompts."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from pypdf import PdfReader
import pytest

from fixtures.factory import content_snapshot, encrypt_pdf, make_pdf
from pyunlock import cli


def invoke(*arguments: str | Path) -> int:
    """argparse is allowed to signal help and syntax errors with SystemExit."""
    try:
        return cli.main([str(argument) for argument in arguments])
    except SystemExit as error:
        return int(error.code or 0)


def refuse_prompt(*_args: object, **_kwargs: object) -> str:
    pytest.fail("the command unexpectedly requested a password")


def assert_protected(path: Path, password: str, page_count: int = 2) -> None:
    reader = PdfReader(path)
    assert reader.is_encrypted
    assert not reader.decrypt("")
    assert not reader.decrypt("definitely incorrect")
    assert reader.decrypt(password)
    assert len(reader.pages) == page_count
    encryption = reader.trailer["/Encrypt"]
    assert encryption["/V"] == 5
    assert encryption["/Length"] == 256


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["-f"],
        ["-f", "a.pdf", "-a", "change"],
        ["-f", "a.pdf", "-m", "backup"],
        ["-f", "a.pdf", "--unknown"],
    ],
)
def test_invalid_syntax_returns_two(arguments, capsys):
    assert invoke(*arguments) == 2
    output = capsys.readouterr()
    assert "usage:" in output.err.lower()
    assert "Traceback" not in output.err


def test_invalid_syntax_does_not_echo_supplied_password(capsys):
    password = "never-echo-this-secret"
    assert invoke("-f", "synthetic.pdf", "-p", password, "--pasword", password) == 2
    output = capsys.readouterr()
    assert password not in output.out + output.err


def test_help_and_version(capsys):
    assert invoke("--help") == 0
    help_text = capsys.readouterr().out
    for option in ("--files", "--action", "--password", "--mode", "--recursive"):
        assert option in help_text
    assert "unlock" in help_text and "lock" in help_text
    assert invoke("--version") == 0
    assert re.search(r"\b\d+\.\d+\.\d+\b", capsys.readouterr().out)


def test_original_syntax_defaults_to_unlock_and_replace(encrypted_pdf, capsys):
    expected = content_snapshot(encrypted_pdf, "test-password")
    assert invoke("-f", encrypted_pdf, "-p", "test-password") == 0
    assert content_snapshot(encrypted_pdf) == expected
    assert not encrypted_pdf.with_stem(encrypted_pdf.stem + "_unlock").exists()
    output = capsys.readouterr()
    assert "OK" in output.out
    assert "1 unlocked, 0 skipped, 0 failed" in output.out
    assert output.err == ""


@pytest.mark.parametrize("action", ["unlock", "lock"])
@pytest.mark.parametrize("mode", ["replace", "new"])
def test_actions_modes_and_unicode_password(tmp_path, action, mode, capsys):
    source = make_pdf(tmp_path / "รายงาน café.final.PDF", rich=True)
    expected = content_snapshot(source)
    password = "  รหัสผ่าน-π-🔐  "
    if action == "unlock":
        encrypted = encrypt_pdf(source, tmp_path / "encrypted.PDF", password=password)
        source.write_bytes(encrypted.read_bytes())
        encrypted.unlink()
    original = source.read_bytes()
    assert invoke("--files", source, "--action", action, "--mode", mode,
                  "--password", password) == 0
    destination = source if mode == "replace" else source.with_stem(source.stem + "_" + action)
    assert destination.exists()
    if mode == "new":
        assert source.read_bytes() == original
        assert destination.name == "รายงาน café.final_" + action + ".PDF"
    if action == "lock":
        assert_protected(destination, password)
        assert content_snapshot(destination, password) == expected
    else:
        assert not PdfReader(destination).is_encrypted
        assert content_snapshot(destination) == expected
    output = capsys.readouterr()
    assert password not in output.out + output.err
    assert f"1 {'locked' if action == 'lock' else 'unlocked'}, 0 skipped, 0 failed" in output.out


def test_repeated_files_mixed_folders_deduplicate_and_snapshot_before_writes(tmp_path, capsys):
    explicit = make_pdf(tmp_path / "explicit.pdf")
    first = make_pdf(tmp_path / "one" / "b.pdf")
    second = make_pdf(tmp_path / "one" / "a.PDF")
    nested = make_pdf(tmp_path / "one" / "nested" / "nested.pdf")
    third = make_pdf(tmp_path / "two" / "c.pdf")
    (first.parent / "ignore.txt").write_text("not a PDF")
    assert invoke("-a", "lock", "-m", "new", "-p", "shared secret", "-f", explicit,
                  first.parent, "-f", third.parent, explicit, second) == 0
    output = capsys.readouterr()
    assert "4 locked, 0 skipped, 0 failed" in output.out
    assert output.out.count("OK") == 4
    assert output.out.index(str(explicit)) < output.out.index(str(second)) < output.out.index(str(first))
    for source in (explicit, first, second, third):
        assert_protected(source.with_stem(source.stem + "_lock"), "shared secret")
    assert not nested.with_stem("nested_lock").exists()
    assert not list(tmp_path.rglob("*_lock_lock.*"))
    assert "ignore.txt" not in output.out + output.err


def test_recursion_is_opt_in(tmp_path, capsys):
    source = make_pdf(tmp_path / "folder" / "child" / "deep.pdf")
    assert invoke("-a", "lock", "-f", tmp_path / "folder", "-r", "-p", "secret", "-m", "new") == 0
    assert_protected(source.with_stem("deep_lock"), "secret")
    assert "1 locked" in capsys.readouterr().out


def test_unlock_unencrypted_skips_without_prompt_or_rewrite(plain_pdf, monkeypatch, capsys):
    before = plain_pdf.read_bytes()
    monkeypatch.setattr(cli.getpass, "getpass", refuse_prompt)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert invoke("-f", plain_pdf, "-m", "new") == 0
    assert plain_pdf.read_bytes() == before
    assert not plain_pdf.with_stem("report_unlock").exists()
    output = capsys.readouterr()
    assert "SKIP" in output.out and "already unlocked" in output.out
    assert "0 unlocked, 1 skipped, 0 failed" in output.out
    assert output.err == ""


def test_unlock_prompts_once_lazily_and_caches_for_batch(tmp_path, monkeypatch, capsys):
    plain = make_pdf(tmp_path / "plain.pdf")
    first = encrypt_pdf(plain, tmp_path / "one.pdf")
    second = encrypt_pdf(plain, tmp_path / "two.pdf")
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "test-password"

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", answer)
    assert invoke("-f", plain, first, second) == 0
    assert len(prompts) == 1
    assert not PdfReader(first).is_encrypted and not PdfReader(second).is_encrypted
    assert "2 unlocked, 1 skipped, 0 failed" in capsys.readouterr().out


def test_lock_prompts_for_confirmation_once_for_batch(tmp_path, monkeypatch, capsys):
    sources = [make_pdf(tmp_path / name) for name in ("one.pdf", "two.pdf")]
    prompts = []
    password = "   keep whitespace   "

    def answer(prompt):
        prompts.append(prompt)
        return password

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", answer)
    assert invoke("-a", "lock", "-f", *sources) == 0
    assert len(prompts) == 2
    for source in sources:
        assert_protected(source, password)
    assert password not in "".join(capsys.readouterr())


def test_explicit_lock_password_does_not_prompt(plain_pdf, monkeypatch):
    monkeypatch.setattr(cli.getpass, "getpass", refuse_prompt)
    assert invoke("-a", "lock", "-f", plain_pdf, "-p", "secret") == 0
    assert_protected(plain_pdf, "secret")


@pytest.mark.parametrize("password", [None, ""])
def test_empty_lock_password_aborts_before_any_write(tmp_path, monkeypatch, password, capsys):
    sources = [make_pdf(tmp_path / name) for name in ("one.pdf", "two.pdf")]
    original = [source.read_bytes() for source in sources]
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "")
    arguments = ["-a", "lock", "-f", *sources]
    if password is not None:
        arguments.extend(["-p", password])
    assert invoke(*arguments) == 2
    assert [source.read_bytes() for source in sources] == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["one.pdf", "two.pdf"]
    output = capsys.readouterr()
    assert "password" in output.err.lower()
    assert "Traceback" not in output.err


def test_mismatched_confirmation_aborts_batch_without_leaking_answers(tmp_path, monkeypatch, capsys):
    sources = [make_pdf(tmp_path / name) for name in ("one.pdf", "two.pdf")]
    originals = [source.read_bytes() for source in sources]
    answers = iter(["secret-first-answer", "different-second-answer"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: next(answers))
    assert invoke("-a", "lock", "-f", *sources, "-m", "new") == 2
    assert [source.read_bytes() for source in sources] == originals
    assert len(list(tmp_path.iterdir())) == 2
    output = "".join(capsys.readouterr())
    assert "secret-first-answer" not in output
    assert "different-second-answer" not in output
    assert "Traceback" not in output


def test_explicit_empty_unlock_password_is_not_missing(plain_pdf, tmp_path, monkeypatch):
    source = encrypt_pdf(plain_pdf, tmp_path / "empty.pdf", password="")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.getpass, "getpass", refuse_prompt)
    assert invoke("-f", source, "-p", "") == 0
    assert not PdfReader(source).is_encrypted


def test_interactively_empty_unlock_password_is_allowed(plain_pdf, tmp_path, monkeypatch):
    source = encrypt_pdf(plain_pdf, tmp_path / "empty.pdf", password="")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    answers = []

    def answer(prompt):
        answers.append(prompt)
        return ""

    monkeypatch.setattr(cli.getpass, "getpass", answer)
    assert invoke("-f", source) == 0
    assert len(answers) == 1
    assert not PdfReader(source).is_encrypted


def test_encrypted_lock_input_is_rejected_without_requesting_new_password(encrypted_pdf, monkeypatch, capsys):
    before = encrypted_pdf.read_bytes()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", refuse_prompt)
    assert invoke("-a", "lock", "-f", encrypted_pdf) == 1
    assert encrypted_pdf.read_bytes() == before
    assert "already encrypted" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["unlock", "lock"])
def test_noninteractive_missing_password_fails_without_prompt(plain_pdf, tmp_path, monkeypatch, capsys, action):
    source = plain_pdf if action == "lock" else encrypt_pdf(plain_pdf, tmp_path / "encrypted.pdf")
    before = source.read_bytes()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.getpass, "getpass", refuse_prompt)
    assert invoke("-a", action, "-f", source) == 1
    assert source.read_bytes() == before
    output = capsys.readouterr()
    assert "ERROR" in output.err and "password" in output.err.lower()
    assert "1 failed" in output.out
    assert "Traceback" not in output.err


@pytest.mark.parametrize("exception", [KeyboardInterrupt, EOFError])
def test_password_prompt_abort_is_handled(encrypted_pdf, monkeypatch, capsys, exception):
    before = encrypted_pdf.read_bytes()

    def abort(*_):
        raise exception()

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", abort)
    assert invoke("-f", encrypted_pdf) == (130 if exception is KeyboardInterrupt else 1)
    assert encrypted_pdf.read_bytes() == before
    assert "Traceback" not in "".join(capsys.readouterr())


def test_mixed_unlock_batch_reports_success_skip_and_errors(tmp_path, capsys):
    plain = make_pdf(tmp_path / "plain.pdf")
    good = encrypt_pdf(plain, tmp_path / "good.pdf", password="shared-password")
    wrong = encrypt_pdf(plain, tmp_path / "wrong.pdf", password="other-password")
    invalid = tmp_path / "corrupt.pdf"
    invalid.write_bytes(b"synthetic invalid PDF")
    wrong_before, invalid_before = wrong.read_bytes(), invalid.read_bytes()
    missing = tmp_path / "missing.pdf"
    assert invoke("-f", good, plain, wrong, invalid, missing, "-p", "shared-password") == 1
    assert not PdfReader(good).is_encrypted
    assert wrong.read_bytes() == wrong_before and invalid.read_bytes() == invalid_before
    output = capsys.readouterr()
    assert "1 unlocked, 1 skipped, 3 failed" in output.out
    assert "OK" in output.out and "SKIP" in output.out
    assert output.err.count("ERROR") == 3
    assert "incorrect password" in output.err.lower()
    assert "Traceback" not in output.err
    assert "shared-password" not in output.out + output.err


@pytest.mark.parametrize("existing_password", ["old password", ""])
def test_lock_mixed_encrypted_and_plain_batch(tmp_path, capsys, existing_password):
    plain = make_pdf(tmp_path / "plain.pdf")
    encrypted = encrypt_pdf(plain, tmp_path / "encrypted.pdf", password=existing_password)
    encrypted_before = encrypted.read_bytes()
    assert invoke("-a", "lock", "-f", encrypted, plain, "-p", "new-password") == 1
    assert encrypted.read_bytes() == encrypted_before
    assert_protected(plain, "new-password")
    output = capsys.readouterr()
    assert "1 locked, 0 skipped, 1 failed" in output.out
    assert "already encrypted; unlock it first" in output.err
    assert "original unchanged" in output.err
    assert "new-password" not in output.out + output.err


@pytest.mark.parametrize("action", ["lock", "unlock"])
def test_existing_new_destination_is_untouched(tmp_path, capsys, action):
    source = make_pdf(tmp_path / "report.pdf")
    if action == "unlock":
        encrypted = encrypt_pdf(source, tmp_path / "source.pdf", password="secret")
        source.write_bytes(encrypted.read_bytes())
        encrypted.unlink()
    destination = source.with_stem("report_" + action)
    destination.write_bytes(b"existing destination must survive")
    before = source.read_bytes()
    assert invoke("-f", source, "-a", action, "-m", "new", "-p", "secret") == 1
    assert source.read_bytes() == before
    assert destination.read_bytes() == b"existing destination must survive"
    assert "ERROR" in capsys.readouterr().err


def test_new_suffix_is_appended_not_stripped(tmp_path):
    plain = make_pdf(tmp_path / "plain.pdf")
    encrypted = encrypt_pdf(plain, tmp_path / "report_lock.pdf")
    assert invoke("-f", encrypted, "-p", "test-password", "-m", "new") == 0
    assert (tmp_path / "report_lock_unlock.pdf").exists()
    assert not (tmp_path / "report_unlock.pdf").exists()


def test_empty_folder_and_invalid_explicit_file_are_discovery_results(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    ignored = empty / "note.txt"
    ignored.write_text("synthetic text")
    assert invoke("-f", empty, ignored, "-p", "secret") == 1
    output = capsys.readouterr()
    assert "SKIP" in output.out
    assert "ERROR" in output.err
    assert "Traceback" not in output.err
    assert ignored.read_text() == "synthetic text"


@pytest.mark.parametrize("separator", ["\n", "\u2028", "\u2029"])
def test_displayed_filenames_escape_control_characters(tmp_path, capsys, separator):
    source = make_pdf(tmp_path / f"line{separator}break\t\x1b.pdf")
    assert invoke("-a", "lock", "-f", source, "-p", "secret") == 0
    output = capsys.readouterr()
    result_lines = [line for line in output.out.splitlines() if line.startswith("OK")]
    assert len(result_lines) == 1
    assert separator not in result_lines[0]
    assert "line" in result_lines[0] and "break" in result_lines[0]
    assert any(escaped in result_lines[0] for escaped in ("\\t", "\\x09"))
    assert "\x1b" not in output.out + output.err


def test_symlink_before_dot_dot_is_rejected_before_normalization(tmp_path, capsys):
    source = make_pdf(tmp_path / "report.pdf")
    outside = tmp_path / "outside" / "child"
    outside.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    before = source.read_bytes()
    selected = link / ".." / "report.pdf"
    assert invoke("-a", "lock", "-f", selected, "-p", "secret") == 1
    assert source.read_bytes() == before
    assert "symlink" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("explicit_first", [False, True])
def test_explicit_symlink_remains_error_when_also_discovered(tmp_path, capsys, explicit_first):
    source = make_pdf(tmp_path / "folder" / "real.pdf")
    link = source.with_name("linked.pdf")
    link.symlink_to(source)
    selected = [link, source.parent] if explicit_first else [source.parent, link]
    assert invoke("-f", *selected, "-p", "secret") == 1
    output = capsys.readouterr()
    assert "ERROR" in output.err and "symlink" in output.err.lower()
    assert "1 failed" in output.out
    assert (output.out + output.err).count(str(link)) == 1


def test_interruption_reports_partial_completion_summary(tmp_path, monkeypatch, capsys):
    sources = [make_pdf(tmp_path / name) for name in ("one.pdf", "two.pdf")]
    second_before = sources[1].read_bytes()
    real_process = cli.process_pdf
    calls = 0

    def interrupt_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return real_process(*args, **kwargs)

    monkeypatch.setattr(cli, "process_pdf", interrupt_second)
    assert invoke("-a", "lock", "-f", *sources, "-p", "secret") == 130
    assert_protected(sources[0], "secret")
    assert sources[1].read_bytes() == second_before
    output = capsys.readouterr()
    assert "1 locked" in output.out and "Done:" in output.out
    assert "interrupted" in output.err.lower()
    assert "Traceback" not in output.err


def run_installed(tmp_path: Path, *arguments: str | Path, module: bool = False):
    python = Path(os.environ.get("PYUNLOCK_TEST_PYTHON", sys.executable))
    command = [str(python), "-m", "pyunlock"] if module else [str(python.with_name("pyunlock"))]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [*command, *(str(argument) for argument in arguments)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("module", [False, True])
def test_installed_entry_points_help_version_and_round_trip(tmp_path, module):
    version = run_installed(tmp_path, "--version", module=module)
    assert version.returncode == 0, version.stderr
    assert re.search(r"\b\d+\.\d+\.\d+\b", version.stdout)
    help_result = run_installed(tmp_path, "--help", module=module)
    assert help_result.returncode == 0
    assert "--action" in help_result.stdout
    source = make_pdf(tmp_path / "packaged รายงาน.pdf", rich=True)
    expected = content_snapshot(source)
    password = "installed-🔐-password"
    locked = run_installed(tmp_path, "-f", source, "-a", "lock", "-p", password, "-m", "new", module=module)
    assert locked.returncode == 0, locked.stderr
    locked_path = source.with_stem(source.stem + "_lock")
    assert_protected(locked_path, password)
    unlocked = run_installed(tmp_path, "-f", locked_path, "-p", password, module=module)
    assert unlocked.returncode == 0, unlocked.stderr
    assert content_snapshot(locked_path) == expected
    for result in (locked, unlocked):
        assert password not in result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr


def test_installed_noninteractive_missing_password_never_hangs(tmp_path):
    source = make_pdf(tmp_path / "plain.pdf")
    before = source.read_bytes()
    result = run_installed(tmp_path, "-a", "lock", "-f", source)
    assert result.returncode == 1
    assert "password" in result.stderr.lower()
    assert source.read_bytes() == before
