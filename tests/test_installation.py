"""Isolated installer tests: HOME always points into pytest's temporary directory.

Most cases substitute only the slow venv/pip boundary, leaving the real installer
and its filesystem checks intact. Set PYUNLOCK_TEST_WHEEL and
PYUNLOCK_TEST_WHEELHOUSE to exercise a real packaged install without networking.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALL = REPOSITORY / "install.sh"
UNINSTALL = REPOSITORY / "uninstall.sh"


@pytest.fixture
def isolated(tmp_path):
    home = tmp_path / "home with spaces ü"
    home.mkdir()
    source = tmp_path / "source with spaces"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='pyunlock'\nversion='0.1.0'\n")
    driver = tmp_path / "python_driver.py"
    driver.write_text(
        """import os, pathlib, subprocess, sys
launcher, args = pathlib.Path(sys.argv[1]), sys.argv[2:]
if args == ['-']:
    sys.executable = str(launcher)
    if os.environ.get('PYUNLOCK_TEST_OLD_PYTHON'):
        sys.version_info = (3, 10, 0)
    if os.environ.get('PYUNLOCK_TEST_PUBLICATION_RACE'):
        original_link = os.link
        def race(source, destination, **kwargs):
            pathlib.Path(destination).write_text('concurrent unrelated command')
            return original_link(source, destination, **kwargs)
        os.link = race
    sys.argv = ['-']
    exec(compile(sys.stdin.read(), '<installer>', 'exec'), {'__name__': '__main__'})
elif args[:2] == ['-m', 'venv']:
    if os.environ.get('PYUNLOCK_TEST_FAIL_VENV'):
        sys.exit(1)
    environment = pathlib.Path(args[2])
    (environment / 'bin').mkdir()
    (environment / 'bin/python').write_text(launcher.read_text())
    (environment / 'bin/python').chmod(0o700)
elif args[:3] == ['-m', 'pip', 'install']:
    if os.environ.get('PYUNLOCK_TEST_PACKAGE_LOG'):
        pathlib.Path(os.environ['PYUNLOCK_TEST_PACKAGE_LOG']).write_text(args[3])
    if os.environ.get('PYUNLOCK_TEST_INTERRUPT'):
        import signal, time
        os.kill(os.getppid(), signal.SIGINT)
        time.sleep(0.05)
        sys.exit(130)
    if os.environ.get('PYUNLOCK_TEST_FAIL_PIP'):
        sys.exit(1)
    command = launcher.parent / 'pyunlock'
    command.write_text('#!/bin/sh\\n[ -z "$PYUNLOCK_TEST_BAD_VERSION" ] || exit 1\\nprintf "pyunlock 0.1.0\\\\n"\\n')
    command.chmod(0o700)
elif args[:3] == ['-m', 'pip', 'check']:
    sys.exit(1 if os.environ.get('PYUNLOCK_TEST_FAIL_CHECK') else 0)
elif args == ['-m', 'pip', '--version']:
    if os.environ.get('PYUNLOCK_TEST_MISSING_PIP'):
        sys.exit(1)
    print('pip test double')
elif args == ['-m', 'pyunlock', '--version']:
    print('pyunlock 0.1.0')
elif args == ['-m', 'pyunlock.shell_setup']:
    import runpy
    runpy.run_module('pyunlock.shell_setup', run_name='__main__')
else:
    raise SystemExit('Unexpected test invocation: ' + repr(args))
"""
    )
    python = tmp_path / "test python"
    # This path is generated locally, never interpolated from a document or network.
    import shlex
    python.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(driver))} \"$0\" \"$@\"\n")
    python.chmod(0o700)
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("PYUNLOCK_"):
            del environment[key]
    environment.update(HOME=str(home), PYUNLOCK_SOURCE=str(source), PYUNLOCK_PYTHON=str(python), SHELL="/bin/bash")
    environment.pop("ZDOTDIR", None)
    return home, environment


def run_script(script, environment):
    return subprocess.run(["/bin/bash", str(script)], env=environment, text=True,
                          capture_output=True, timeout=120)


def paths(home):
    return home / ".local/share/pyunlock", home / ".local/bin/pyunlock"


def marker_root(home):
    root, command = paths(home)
    (root / "envs").mkdir(parents=True)
    (root / ".pyunlock-managed").write_text("pyunlock-install-v1\n")
    command.parent.mkdir(parents=True)
    return root, command


def test_shell_syntax():
    subprocess.run(["/bin/bash", "-n", str(INSTALL), str(UNINSTALL)], check=True)


def test_fresh_install_upgrade_and_remove_preserves_external_files(isolated):
    home, environment = isolated
    document = home / "my document.pdf"
    document.write_bytes(b"not an installation file")
    rc = home / ".zshrc"
    rc.write_text("keep my configuration\n")
    first = run_script(INSTALL, environment)
    assert first.returncode == 0, first.stderr
    root, command = paths(home)
    old_target = command.readlink()
    assert old_target.is_absolute() and old_target.is_file()
    assert old_target.parent.parent.parent == root / "envs"
    assert (root / ".pyunlock-managed").read_text() == "pyunlock-install-v1\n"
    assert stat_mode(root) == 0o700
    assert not list(command.parent.glob(".pyunlock.*"))
    second = run_script(INSTALL, environment)
    assert second.returncode == 0, second.stderr
    assert command.readlink() != old_target
    assert old_target.is_file()
    assert len(list((root / "envs").iterdir())) == 2
    removed = run_script(UNINSTALL, environment)
    assert removed.returncode == 0, removed.stderr
    assert not root.exists() and not os.path.lexists(command)
    assert command.parent.is_dir()
    assert document.read_bytes() == b"not an installation file"
    assert rc.read_text() == "keep my configuration\n"
    assert run_script(UNINSTALL, environment).returncode == 0


def stat_mode(path):
    import stat
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("failure", ["FAIL_PIP", "FAIL_VENV", "FAIL_CHECK", "BAD_VERSION", "MISSING_PIP"])
def test_failed_upgrade_keeps_working_installation_and_cleans_stage(isolated, failure):
    home, environment = isolated
    assert run_script(INSTALL, environment).returncode == 0
    root, command = paths(home)
    original = command.readlink()
    environment[f"PYUNLOCK_TEST_{failure}"] = "1"
    failed = run_script(INSTALL, environment)
    assert failed.returncode == 1
    assert command.readlink() == original
    assert original.is_file()
    assert list((root / "envs").iterdir()) == [original.parent.parent]
    assert not list(command.parent.glob(".pyunlock.*"))
    assert "Traceback" not in failed.stderr


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling"])
def test_unrelated_command_collision_is_preserved(isolated, tmp_path, kind):
    home, environment = isolated
    root, command = paths(home)
    command.parent.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("keep")
    if kind == "file":
        command.write_text("unrelated command")
    else:
        command.symlink_to(unrelated if kind == "symlink" else tmp_path / "absent")
    before = command.readlink() if command.is_symlink() else command.read_bytes()
    for script in (INSTALL, UNINSTALL):
        result = run_script(script, environment)
        assert result.returncode == 1
        assert not root.exists()
        assert (command.readlink() if command.is_symlink() else command.read_bytes()) == before
    assert unrelated.read_text() == "keep"


@pytest.mark.parametrize("kind", ["missing", "invalid", "symlink", "hardlink"])
def test_untrusted_root_or_marker_is_never_deleted(isolated, tmp_path, kind):
    home, environment = isolated
    root, command = paths(home)
    root.mkdir(parents=True)
    valuable = root / "valuable.pdf"
    valuable.write_text("keep")
    marker = root / ".pyunlock-managed"
    external = tmp_path / "external marker"
    external.write_text("pyunlock-install-v1\n")
    if kind == "invalid":
        marker.write_text("something else\n")
    elif kind == "symlink":
        marker.symlink_to(external)
    elif kind == "hardlink":
        os.link(external, marker)
    for script in (INSTALL, UNINSTALL):
        result = run_script(script, environment)
        assert result.returncode == 1
        assert valuable.read_text() == "keep"
        assert external.read_text() == "pyunlock-install-v1\n"


@pytest.mark.parametrize("component", [".local", ".local/share", ".local/bin", ".local/share/pyunlock", ".local/share/pyunlock/envs"])
def test_symlinked_ancestors_are_refused(isolated, tmp_path, component):
    home, environment = isolated
    external = tmp_path / "external directory"
    external.mkdir()
    valuable = external / "valuable.pdf"
    valuable.write_text("keep")
    target = home / component
    target.parent.mkdir(parents=True, exist_ok=True)
    if component.endswith("envs"):
        (target.parent / ".pyunlock-managed").write_text("pyunlock-install-v1\n")
    target.symlink_to(external, target_is_directory=True)
    before = sorted(path.name for path in external.iterdir())
    for script in (INSTALL, UNINSTALL):
        result = run_script(script, environment)
        assert result.returncode == 1
        assert target.is_symlink()
        assert sorted(path.name for path in external.iterdir()) == before
        assert valuable.read_text() == "keep"


def test_uninstaller_checks_both_targets_before_removing_either(isolated):
    home, environment = isolated
    root, command = marker_root(home)
    (root / "envs/incomplete").mkdir()
    command.write_text("unrelated command")
    assert run_script(UNINSTALL, environment).returncode == 1
    assert (root / "envs/incomplete").is_dir()
    assert command.read_text() == "unrelated command"


@pytest.mark.parametrize("root_present", [True, False])
def test_incomplete_install_and_dangling_managed_command_removal(isolated, root_present):
    home, environment = isolated
    root, command = marker_root(home)
    (root / "envs/incomplete").mkdir()
    command.symlink_to(root / "envs/incomplete/bin/pyunlock")
    if not root_present:
        shutil.rmtree(root)
    result = run_script(UNINSTALL, environment)
    assert result.returncode == 0, result.stderr
    assert not root.exists() and not os.path.lexists(command)


def test_uninstall_incomplete_root_without_command(isolated):
    home, environment = isolated
    root, command = marker_root(home)
    assert not os.path.lexists(command)
    assert run_script(UNINSTALL, environment).returncode == 0
    assert not root.exists()


@pytest.mark.parametrize("bad_target", ["relative", "dotdot", "external_env"])
def test_disguised_managed_command_is_refused(isolated, tmp_path, bad_target):
    home, environment = isolated
    root, command = marker_root(home)
    if bad_target == "relative":
        command.symlink_to("../share/pyunlock/envs/install.x/bin/pyunlock")
    elif bad_target == "dotdot":
        command.symlink_to(str(root / "envs") + "/../external/bin/pyunlock")
    else:
        outside = tmp_path / "external env"
        (outside / "bin").mkdir(parents=True)
        (root / "envs/install.x").symlink_to(outside)
        command.symlink_to(root / "envs/install.x/bin/pyunlock")
    for script in (INSTALL, UNINSTALL):
        assert run_script(script, environment).returncode == 1
        assert command.is_symlink() and root.is_dir()


def test_repository_placeholder_and_bad_ref_fail_before_creating_root(isolated):
    home, environment = isolated
    environment.pop("PYUNLOCK_SOURCE")
    environment["PYUNLOCK_REPO"] = "YOUR_GITHUB_USERNAME/pyunlock"
    result = run_script(INSTALL, environment)
    assert result.returncode == 1 and "placeholder" in result.stderr
    assert not paths(home)[0].exists()
    environment.update(PYUNLOCK_REPO="example/pyunlock", PYUNLOCK_REF="bad ref")
    assert run_script(INSTALL, environment).returncode == 1
    assert not paths(home)[0].exists()


def test_default_github_source_installs_without_source_overrides(isolated, tmp_path):
    home, environment = isolated
    environment.pop("PYUNLOCK_SOURCE")
    recorded_package = tmp_path / "pip-package.txt"
    environment["PYUNLOCK_TEST_PACKAGE_LOG"] = str(recorded_package)

    installed = run_script(INSTALL, environment)

    assert installed.returncode == 0, installed.stderr
    assert recorded_package.read_text() == "git+https://github.com/rtreertree/pyunlock.git@main"
    assert paths(home)[1].is_symlink()
    assert run_script(UNINSTALL, environment).returncode == 0


@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize("method", ["source", "eval"])
def test_sourced_install_activates_current_shell_and_preserves_shell_state(isolated, shell, method):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is unavailable")
    home, environment = isolated
    environment.update(SHELL=executable, PATH="/usr/bin:/bin")
    script = '''
set -eu
trap ':' USR1
before_options=$-
before_traps=$(trap)
before_directory=$PWD
if [ "$2" = eval ]; then eval "$(cat "$1")"; else . "$1"; fi
test "$-" = "$before_options"
test "$(trap)" = "$before_traps"
test "$PWD" = "$before_directory"
test "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock"
pyunlock --version
if command -v _pyunlock_install >/dev/null 2>&1; then exit 9; fi
if [ "$2" = eval ]; then eval "$(cat "$1")"; else . "$1"; fi
test "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock"
pyunlock --version
'''
    result = subprocess.run([executable, "-c", script, "pyunlock-test", str(INSTALL), method],
                            env=environment, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pyunlock 0.1.0" in result.stdout
    startup = home / (".bashrc" if shell == "bash" else ".zshrc")
    assert startup.read_bytes().count(b"# >>> pyunlock PATH >>>") == 1
    # A new interactive terminal must also find the command without activation.
    fresh = subprocess.run([executable, "-ic", 'test "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock" && pyunlock --version'],
                           env=environment, text=True, capture_output=True, timeout=30)
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr


def test_path_setup_failure_preserves_working_upgrade_and_original_shell_files(isolated):
    home, environment = isolated
    assert run_script(INSTALL, environment).returncode == 0
    root, command = paths(home)
    previous = command.readlink()
    bashrc = home / ".bashrc"
    original = bashrc.read_bytes()
    bashrc.chmod(0o400)
    try:
        failed = run_script(INSTALL, environment)
        assert failed.returncode == 1
        assert "PATH setup failed" in failed.stderr
        assert "Traceback" not in failed.stderr
        assert command.readlink() == previous
        assert list((root / "envs").iterdir()) == [previous.parent.parent]
        assert bashrc.read_bytes() == original
    finally:
        bashrc.chmod(0o600)


def test_sourced_zsh_install_honors_unexported_zdotdir(isolated, tmp_path):
    if not Path("/bin/zsh").is_file():
        pytest.skip("Zsh is unavailable")
    home, environment = isolated
    directory = tmp_path / "Zsh settings ü"
    directory.mkdir()
    environment["SHELL"] = "/bin/zsh"
    script = '''
ZDOTDIR=$2
typeset +x ZDOTDIR
. "$1" || exit $?
test "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock" || exit 8
test -f "$ZDOTDIR/.zshrc" && test -f "$ZDOTDIR/.zprofile" || exit 9
if env | grep '^ZDOTDIR='; then exit 10; fi
'''
    result = subprocess.run(["/bin/zsh", "-c", script, "pyunlock-test", str(INSTALL), str(directory)],
                            env=environment, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".zshrc").exists()


def test_missing_git_and_old_python_fail_before_writing(isolated, tmp_path):
    home, environment = isolated
    environment.pop("PYUNLOCK_SOURCE")
    environment.update(PYUNLOCK_REPO="example/pyunlock", PATH=str(tmp_path / "no commands"))
    result = run_script(INSTALL, environment)
    assert result.returncode == 1 and "Install Git" in result.stderr
    assert not paths(home)[0].exists()
    environment["PYUNLOCK_TEST_OLD_PYTHON"] = "1"
    result = run_script(INSTALL, environment)
    assert result.returncode == 1 and "Python 3.11" in result.stderr
    assert not paths(home)[0].exists()


def test_bad_repository_and_git_transport_failure_keep_existing_install(isolated):
    home, environment = isolated
    assert run_script(INSTALL, environment).returncode == 0
    root, command = paths(home)
    original = command.readlink()
    environment.pop("PYUNLOCK_SOURCE")
    environment["PYUNLOCK_REPO"] = "bad/repo/format"
    assert run_script(INSTALL, environment).returncode == 1
    assert command.readlink() == original
    environment.update(PYUNLOCK_REPO="example/pyunlock", PYUNLOCK_TEST_FAIL_PIP="1")
    failure = run_script(INSTALL, environment)
    assert failure.returncode == 1 and "repository/ref, network" in failure.stderr
    assert command.readlink() == original and original.is_file()
    assert len(list((root / "envs").iterdir())) == 1


def test_interrupted_upgrade_keeps_previous_command_and_removes_incomplete_environment(isolated):
    home, environment = isolated
    assert run_script(INSTALL, environment).returncode == 0
    root, command = paths(home)
    original = command.readlink()
    environment["PYUNLOCK_TEST_INTERRUPT"] = "1"
    result = run_script(INSTALL, environment)
    assert result.returncode == 130, result.stderr
    assert command.readlink() == original
    assert list((root / "envs").iterdir()) == [original.parent.parent]


def test_fresh_publication_never_overwrites_a_concurrent_command(isolated):
    home, environment = isolated
    environment["PYUNLOCK_TEST_PUBLICATION_RACE"] = "1"
    result = run_script(INSTALL, environment)
    assert result.returncode == 1
    root, command = paths(home)
    assert command.read_text() == "concurrent unrelated command"
    assert not list((root / "envs").iterdir())
    assert not list(command.parent.glob(".pyunlock.*"))


def test_missing_python_and_invalid_local_source_fail_clearly(isolated):
    home, environment = isolated
    environment["PYUNLOCK_PYTHON"] = str(home / "no such python")
    result = run_script(INSTALL, environment)
    assert result.returncode == 1 and "Python 3.11" in result.stderr
    assert run_script(UNINSTALL, environment).returncode == 1
    environment["PYUNLOCK_PYTHON"] = sys.executable
    environment["PYUNLOCK_SOURCE"] = str(home / "absent wheel.whl")
    assert run_script(INSTALL, environment).returncode == 1
    assert not paths(home)[0].exists()


def test_real_packaged_install_and_failed_update(tmp_path):
    wheel = os.environ.get("PYUNLOCK_TEST_WHEEL")
    wheelhouse = os.environ.get("PYUNLOCK_TEST_WHEELHOUSE")
    if not wheel or not wheelhouse:
        pytest.skip("Set PYUNLOCK_TEST_WHEEL and PYUNLOCK_TEST_WHEELHOUSE for the real packaged integration test.")
    home = tmp_path / "real home with spaces ü"
    home.mkdir()
    environment = os.environ.copy()
    environment.pop("ZDOTDIR", None)
    environment.update(HOME=str(home), PYUNLOCK_PYTHON=sys.executable,
                       PYUNLOCK_SOURCE=str(Path(wheel).resolve()), PIP_NO_INDEX="1",
                       PIP_FIND_LINKS=str(Path(wheelhouse).resolve()), PIP_DISABLE_PIP_VERSION_CHECK="1", SHELL="/bin/bash")
    result = run_script(INSTALL, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    root, command = paths(home)
    first_environment = command.readlink()
    updated = subprocess.run(["/bin/bash", "-c",
                              '. "$1" && test "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock" && pyunlock --version',
                              "pyunlock-test", str(INSTALL)], env=environment, text=True,
                             capture_output=True, timeout=120)
    assert updated.returncode == 0, updated.stdout + updated.stderr
    previous = command.readlink()
    assert previous != first_environment and first_environment.is_file()
    assert len(list((root / "envs").iterdir())) == 2
    assert subprocess.run([str(command), "--help"], env=environment, capture_output=True).returncode == 0
    assert subprocess.run([str(previous.parent / "python"), "-m", "pyunlock", "--version"],
                          env=environment, capture_output=True).returncode == 0
    # An invalid wheel is present, so failure occurs in actual pip, after venv creation.
    broken = tmp_path / "pyunlock-999.0-py3-none-any.whl"
    broken.write_bytes(b"not a wheel")
    environment["PYUNLOCK_SOURCE"] = str(broken)
    failed = run_script(INSTALL, environment)
    assert failed.returncode == 1
    assert command.readlink() == previous and previous.is_file()
    assert len(list((root / "envs").iterdir())) == 2
    assert subprocess.run([str(command), "--version"], env=environment, capture_output=True).returncode == 0
    if shutil.which("git"):
        mirror = tmp_path / "local Git mirror"
        mirror.mkdir()
        git_origin = mirror / "pyunlock.git"
        subprocess.run(["git", "init", "--bare", str(git_origin)], check=True, capture_output=True)
        environment.pop("PYUNLOCK_SOURCE")
        environment.update(PYUNLOCK_REPO="fixture/pyunlock", PYUNLOCK_REF="nonexistent-ref",
                           GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.{mirror.as_uri()}/.insteadOf",
                           GIT_CONFIG_VALUE_0="https://github.com/fixture/")
        # Real Git checkout failure, redirected locally so this test never needs networking.
        bad_ref = run_script(INSTALL, environment)
        assert bad_ref.returncode == 1 and "Package installation failed" in bad_ref.stderr
        assert command.readlink() == previous and previous.is_file()
        shutil.rmtree(git_origin)
        transport_failure = run_script(INSTALL, environment)
        assert transport_failure.returncode == 1 and "Package installation failed" in transport_failure.stderr
        assert command.readlink() == previous and len(list((root / "envs").iterdir())) == 2
    assert run_script(UNINSTALL, environment).returncode == 0
    assert not root.exists() and not os.path.lexists(command)


def manual_install_block():
    import re
    readme = (REPOSITORY / "README.md").read_text()
    blocks = re.findall(r"```bash\n(.*?)```", readme, re.DOTALL)
    return next(block for block in blocks if block.startswith("# Manual fresh install\n"))


def test_documented_manual_install_survives_source_removal(tmp_path):
    wheelhouse = os.environ.get("PYUNLOCK_TEST_WHEELHOUSE")
    if not wheelhouse:
        pytest.skip("Set PYUNLOCK_TEST_WHEELHOUSE for the real documented manual install integration test.")
    home = tmp_path / "manual home with spaces ü"
    home.mkdir()
    checkout = tmp_path / "temporary source checkout"
    shutil.copytree(REPOSITORY, checkout, ignore=shutil.ignore_patterns(
        ".git", ".venv", "dist", "build", "*.egg-info", "__pycache__", ".pytest_cache"))
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("ZDOTDIR", None)
    environment.update(HOME=str(home), PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""),
                       PIP_NO_INDEX="1", PIP_FIND_LINKS=str(Path(wheelhouse).resolve()),
                       PIP_DISABLE_PIP_VERSION_CHECK="1", PYUNLOCK_PYTHON=sys.executable, SHELL="/bin/bash")
    installed = subprocess.run(["/bin/bash", "-c", manual_install_block() + '\ntest "$(command -v pyunlock)" = "$HOME/.local/bin/pyunlock" && pyunlock --version'], cwd=checkout,
                               env=environment, text=True, capture_output=True, timeout=120)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    root, command = paths(home)
    assert command.readlink() == root / "envs/manual/bin/pyunlock"
    assert (root / ".pyunlock-managed").read_text() == "pyunlock-install-v1\n"
    before = command.readlink()
    duplicate = subprocess.run(["/bin/bash", "-c", manual_install_block()], cwd=checkout,
                               env=environment, text=True, capture_output=True, timeout=120)
    assert duplicate.returncode != 0 and command.readlink() == before
    shutil.rmtree(checkout)
    for arguments in ([str(command), "--help"],
                      [str(root / "envs/manual/bin/python"), "-m", "pyunlock", "--version"]):
        result = subprocess.run(arguments, cwd=tmp_path, env=environment, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    assert run_script(UNINSTALL, environment).returncode == 0
    assert not root.exists() and not os.path.lexists(command)
