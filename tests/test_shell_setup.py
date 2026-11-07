"""Exercise installed shell setup against disposable startup files and real shells."""

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

import pyunlock.shell_setup as shell_setup
from pyunlock.shell_setup import ShellSetupError, configure_path


START = b"# >>> pyunlock PATH >>>"
END = b"# <<< pyunlock PATH <<<"


@pytest.fixture
def shell_home(tmp_path):
    home = tmp_path / "home with spaces ไทย ü"
    home.mkdir()
    command = home / ".local/bin/pyunlock"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\nprintf 'isolated pyunlock command\\n'\n")
    command.chmod(0o700)
    return home


def shell_environment(home, shell):
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "BASH_ENV", "ENV", "ZDOTDIR"):
        environment.pop(name, None)
    environment.update(HOME=str(home), SHELL=shell, PATH="/usr/bin:/bin", TERM="dumb")
    return environment


def run_shell(home, shell, flags, command, *, zdotdir=None, path=None):
    if not Path(shell).is_file():
        pytest.skip(f"{shell} is unavailable on this platform")
    environment = shell_environment(home, shell)
    if zdotdir is not None:
        environment["ZDOTDIR"] = str(zdotdir)
    if path is not None:
        environment["PATH"] = path
    return subprocess.run([shell, *flags, command], cwd=home, env=environment,
                          text=True, capture_output=True, timeout=20)


@pytest.mark.parametrize("shell, flags", [
    ("/bin/bash", ["--noprofile", "-ic"]),
    ("/bin/bash", ["--login", "-c"]),
    ("/bin/zsh", ["-ic"]),
    ("/bin/zsh", ["-lc"]),
    ("/bin/zsh", ["-lic"]),
])
def test_fresh_terminal_resolves_installed_command_without_manual_path(shell_home, shell, flags):
    configure_path(shell_home, shell=shell)

    result = run_shell(shell_home, shell, flags, "command -v pyunlock; pyunlock")

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(shell_home / ".local/bin/pyunlock") in result.stdout.splitlines()
    assert "isolated pyunlock command" in result.stdout.splitlines()


@pytest.mark.parametrize("shell, names", [
    ("/bin/bash", [".bashrc", ".profile"]),
    ("/bin/zsh", [".zshrc", ".zprofile"]),
    (None, [".bashrc", ".profile"]),
])
def test_expected_startup_files_are_created_once(shell_home, shell, names):
    changed = configure_path(shell_home, shell=shell)
    assert set(changed) == {shell_home / name for name in names}
    before = {name: (shell_home / name).read_bytes() for name in names}
    for contents in before.values():
        assert contents.count(START) == contents.count(END) == 1

    assert configure_path(shell_home, shell=shell) == []
    assert {name: (shell_home / name).read_bytes() for name in names} == before


@pytest.mark.parametrize("existing, selected", [
    ([".bash_profile", ".bash_login", ".profile"], ".bash_profile"),
    ([".bash_login", ".profile"], ".bash_login"),
    ([".profile"], ".profile"),
])
def test_bash_uses_the_first_existing_login_startup_file(shell_home, existing, selected):
    for name in existing:
        (shell_home / name).write_bytes(b"# existing startup file\n")
    configure_path(shell_home, shell="/bin/bash")

    assert START in (shell_home / selected).read_bytes()
    for name in set(existing) - {selected}:
        assert (shell_home / name).read_bytes() == b"# existing startup file\n"
    result = run_shell(shell_home, "/bin/bash", ["--login", "-c"], "command -v pyunlock")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(shell_home / ".local/bin/pyunlock") in result.stdout.splitlines()


def test_zdotdir_is_used_for_both_zsh_startup_files(shell_home, tmp_path):
    zdotdir = tmp_path / "Zsh settings with spaces ü"
    zdotdir.mkdir()

    changed = configure_path(shell_home, shell="/bin/zsh", zdotdir=str(zdotdir))

    assert set(changed) == {zdotdir / ".zshrc", zdotdir / ".zprofile"}
    assert not (shell_home / ".zshrc").exists()
    assert not (shell_home / ".zprofile").exists()
    for flags in (["-ic"], ["-lc"], ["-lic"]):
        result = run_shell(shell_home, "/bin/zsh", flags, "command -v pyunlock",
                           zdotdir=zdotdir)
        assert result.returncode == 0, result.stdout + result.stderr
        assert str(shell_home / ".local/bin/pyunlock") in result.stdout.splitlines()


def test_relative_zdotdir_is_refused_without_creating_startup_files(shell_home):
    with pytest.raises(ShellSetupError):
        configure_path(shell_home, shell="/bin/zsh", zdotdir="relative/settings")
    assert not (shell_home / ".zshrc").exists()
    assert not (shell_home / ".zprofile").exists()


@pytest.mark.parametrize("original", [
    b"# keep my settings\nexport USER_SETTING='kept'\n",
    b"# no final newline\nexport USER_SETTING='kept'",
    b"# preserve non-UTF8 bytes: \xff\n",
])
def test_unrelated_bytes_and_permissions_are_preserved(shell_home, original):
    startup = shell_home / ".bashrc"
    startup.write_bytes(original)
    startup.chmod(0o640)

    configure_path(shell_home, shell="/bin/bash")

    contents = startup.read_bytes()
    assert contents.startswith(original)
    if not original.endswith(b"\n"):
        assert contents[len(original):].startswith(b"\n")
    assert stat.S_IMODE(startup.stat().st_mode) == 0o640
    result = run_shell(shell_home, "/bin/bash", ["--noprofile", "-ic"],
                       "printf '%s\\n' \"$USER_SETTING\"; command -v pyunlock")
    assert result.returncode == 0, result.stdout + result.stderr
    if b"USER_SETTING" in original:
        assert "kept" in result.stdout.splitlines()
    assert str(shell_home / ".local/bin/pyunlock") in result.stdout.splitlines()


@pytest.mark.parametrize("kind", ["symlink", "dangling", "hardlink", "directory", "fifo", "readonly"])
def test_unsafe_startup_file_is_refused_before_modifying_any_target(shell_home, tmp_path, kind):
    first = shell_home / ".bashrc"
    first.write_bytes(b"# untouched first target\n")
    last = shell_home / ".profile"
    external = tmp_path / "unrelated startup"
    external.write_bytes(b"# unrelated content\n")
    if kind == "symlink":
        last.symlink_to(external)
    elif kind == "dangling":
        last.symlink_to(tmp_path / "does not exist")
    elif kind == "hardlink":
        os.link(external, last)
    elif kind == "directory":
        last.mkdir()
    elif kind == "fifo":
        os.mkfifo(last)
    else:
        last.write_bytes(b"# read only\n")
        last.chmod(0o400)

    with pytest.raises(ShellSetupError):
        configure_path(shell_home, shell="/bin/bash")

    assert first.read_bytes() == b"# untouched first target\n"
    assert external.read_bytes() == b"# unrelated content\n"
    if kind == "readonly":
        assert last.read_bytes() == b"# read only\n"
        assert stat.S_IMODE(last.stat().st_mode) == 0o400
    elif kind in ("symlink", "dangling"):
        assert last.is_symlink()
    elif kind == "hardlink":
        assert last.read_bytes() == b"# unrelated content\n"


@pytest.mark.parametrize("contents", [
    START + b"\n# incomplete block\n",
    END + b"\n",
    END + b"\n" + START + b"\n",
    START + b"\n" + START + b"\n" + END + b"\n",
])
def test_partial_or_ambiguous_managed_block_is_refused_without_other_edits(shell_home, contents):
    startup = shell_home / ".profile"
    startup.write_bytes(contents)

    with pytest.raises(ShellSetupError):
        configure_path(shell_home, shell="/bin/bash")

    assert startup.read_bytes() == contents
    assert not (shell_home / ".bashrc").exists()


@pytest.mark.parametrize("shell, flags", [
    ("/bin/bash", ["--noprofile", "-ic"]),
    ("/bin/zsh", ["-lic"]),
])
def test_startup_never_duplicates_an_existing_local_bin_entry(shell_home, shell, flags):
    configure_path(shell_home, shell=shell)
    configure_path(shell_home, shell=shell)
    bin_dir = str(shell_home / ".local/bin")
    result = run_shell(shell_home, shell, flags, "printf '%s\\n' \"$PATH\"",
                       path=f"/usr/bin:{bin_dir}:/bin")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().split(":").count(bin_dir) == 1


@pytest.mark.parametrize("shell, flags, startup", [
    ("/bin/bash", ["--noprofile", "-ic"], ".bashrc"),
    ("/bin/zsh", ["-ic"], ".zshrc"),
])
def test_guard_adds_the_exact_directory_when_only_a_similar_directory_exists(shell_home, shell, flags, startup):
    configure_path(shell_home, shell=shell)
    bin_dir = str(shell_home / ".local/bin")
    result = run_shell(shell_home, shell, flags,
                       f'. "$HOME/{startup}"; . "$HOME/{startup}"; printf \'%s\\n\' "$PATH"',
                       path=f"/usr/bin:{bin_dir}-other:/bin")

    assert result.returncode == 0, result.stdout + result.stderr
    entries = result.stdout.strip().split(":")
    assert entries.count(bin_dir) == 1
    assert entries.count(bin_dir + "-other") == 1


def test_unsupported_shell_has_clear_error_and_leaves_startup_files_alone(shell_home):
    with pytest.raises(ShellSetupError):
        configure_path(shell_home, shell="/usr/bin/fish")
    assert not list(shell_home.glob(".*rc"))
    assert not (shell_home / ".profile").exists()


def test_startup_file_owned_by_another_user_is_refused(shell_home, monkeypatch):
    startup = shell_home / ".bashrc"
    startup.write_bytes(b"# preserve another owner's startup\n")
    owner = startup.stat().st_uid
    monkeypatch.setattr(os, "getuid", lambda: owner + 1)
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)

    with pytest.raises(ShellSetupError):
        configure_path(shell_home, shell="/bin/bash")

    assert startup.read_bytes() == b"# preserve another owner's startup\n"
    assert not (shell_home / ".profile").exists()


@pytest.mark.parametrize("existing", [True, False])
@pytest.mark.parametrize("failure", ["second_write", "partial_write", "second_fsync", "interrupt"])
def test_append_failures_restore_originals_and_remove_new_startup_files(shell_home, monkeypatch, existing, failure):
    paths = [shell_home / ".bashrc", shell_home / ".profile"]
    if existing:
        for path in paths:
            path.write_bytes(b"# original startup without final newline")
            path.chmod(0o640)
    original_write = os.write
    original_fsync = os.fsync
    writes = syncs = 0

    def write(fd, contents):
        nonlocal writes
        writes += 1
        if failure == "partial_write":
            if writes == 1:
                return original_write(fd, contents[:17])
            raise OSError("injected write failure")
        if writes == 2 and failure == "second_write":
            raise OSError("injected write failure")
        if writes == 2 and failure == "interrupt":
            raise KeyboardInterrupt
        return original_write(fd, contents)

    def fsync(fd):
        nonlocal syncs
        syncs += 1
        if failure == "second_fsync" and syncs == 2:
            raise OSError("injected synchronization failure")
        return original_fsync(fd)

    monkeypatch.setattr(shell_setup.os, "write", write)
    monkeypatch.setattr(shell_setup.os, "fsync", fsync)

    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else ShellSetupError):
        configure_path(shell_home, shell="/bin/bash")

    for path in paths:
        if existing:
            assert path.read_bytes() == b"# original startup without final newline"
            assert stat.S_IMODE(path.stat().st_mode) == 0o640
        else:
            assert not path.exists()


def test_failure_cleanup_preserves_concurrent_editor_changes(shell_home, monkeypatch):
    first = shell_home / ".bashrc"
    first.write_bytes(b"# original\n")
    (shell_home / ".profile").write_bytes(b"# login original\n")
    original_write = os.write
    writes = 0

    def write(fd, contents):
        nonlocal writes
        writes += 1
        if writes == 2:
            with first.open("ab") as concurrent:
                concurrent.write(b"# concurrent editor's change\n")
            raise OSError("injected write failure")
        return original_write(fd, contents)

    monkeypatch.setattr(shell_setup.os, "write", write)

    with pytest.raises(ShellSetupError, match="inspect"):
        configure_path(shell_home, shell="/bin/bash")

    assert first.read_bytes().startswith(b"# original\n")
    assert first.read_bytes().endswith(b"# concurrent editor's change\n")
    assert (shell_home / ".profile").read_bytes() == b"# login original\n"


def test_packaged_module_configures_shell_and_reports_expected_errors(shell_home, tmp_path):
    environment = shell_environment(shell_home, "/bin/bash")
    result = subprocess.run([sys.executable, "-m", "pyunlock.shell_setup"], cwd=tmp_path,
                            env=environment, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert START in (shell_home / ".bashrc").read_bytes()
    assert START in (shell_home / ".profile").read_bytes()

    environment["SHELL"] = "/usr/bin/fish"
    failed = subprocess.run([sys.executable, "-m", "pyunlock.shell_setup"], cwd=tmp_path,
                            env=environment, text=True, capture_output=True, timeout=20)
    assert failed.returncode != 0
    assert "shell" in failed.stderr.lower()
    assert "Traceback" not in failed.stderr
