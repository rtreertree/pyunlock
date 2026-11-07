"""Real installed commands with a pseudo-terminal: private getpass behavior."""

import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time

import pytest
from pypdf import PdfReader

from fixtures.factory import encrypt_pdf, make_pdf


class TerminalCommand:
    def __init__(self, directory, *arguments, module=False):
        python = Path(os.environ.get("PYUNLOCK_TEST_PYTHON", sys.executable))
        command = [str(python), "-m", "pyunlock"] if module else [str(python.with_name("pyunlock"))]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        self.master, slave = pty.openpty()
        self.output = bytearray()
        try:
            self.process = subprocess.Popen(
                [*command, *map(str, arguments)], cwd=directory, env=environment,
                stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            )
        finally:
            os.close(slave)

    def read_until(self, text):
        expected = text.encode()
        deadline = time.monotonic() + 15
        while expected not in self.output:
            assert time.monotonic() < deadline, bytes(self.output)
            self._read()
            if self.process.poll() is not None:
                assert expected in self.output, bytes(self.output)

    def _read(self):
        if select.select([self.master], [], [], 0.1)[0]:
            try:
                self.output.extend(os.read(self.master, 65536))
            except OSError:
                pass  # Linux returns EIO when the slave is closed.

    def answer(self, text):
        os.write(self.master, text.encode() + b"\n")

    def finish(self):
        deadline = time.monotonic() + 15
        while self.process.poll() is None:
            assert time.monotonic() < deadline, bytes(self.output)
            self._read()
        self._read()
        return self.process.returncode, self.output.decode(errors="replace")

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        os.close(self.master)


def test_installed_lock_getpass_confirmation_does_not_echo(tmp_path):
    sources = [make_pdf(tmp_path / name) for name in ("one.pdf", "two.pdf")]
    password = "private-รหัสผ่าน"
    terminal = TerminalCommand(tmp_path, "-a", "lock", "-f", *sources)
    try:
        terminal.read_until("New password: ")
        terminal.answer(password)
        terminal.read_until("Confirm new password: ")
        terminal.answer(password)
        code, output = terminal.finish()
        assert code == 0, output
        assert password not in output
        assert output.count("New password:") == 1
        assert output.count("Confirm new password:") == 1
        assert "2 locked" in output
        for source in sources:
            reader = PdfReader(source)
            assert reader.is_encrypted and not reader.decrypt("")
            assert reader.decrypt(password)
    finally:
        terminal.close()


def test_installed_module_unlock_prompts_once_and_accepts_empty_password(tmp_path):
    plain = make_pdf(tmp_path / "plain.pdf")
    sources = [encrypt_pdf(plain, tmp_path / name, password="", owner_password="owner")
               for name in ("one.pdf", "two.pdf")]
    terminal = TerminalCommand(tmp_path, "-f", plain, *sources, module=True)
    try:
        terminal.read_until("Password: ")
        terminal.answer("")
        code, output = terminal.finish()
        assert code == 0, output
        assert output.count("Password:") == 1
        assert "2 unlocked, 1 skipped, 0 failed" in output
        assert all(not PdfReader(source).is_encrypted for source in sources)
    finally:
        terminal.close()


@pytest.mark.parametrize("abort", ["mismatch", "interrupt"])
def test_installed_confirmation_abort_preserves_inputs(tmp_path, abort):
    source = make_pdf(tmp_path / "source.pdf")
    original = source.read_bytes()
    terminal = TerminalCommand(tmp_path, "-a", "lock", "-f", source, "-m", "new")
    try:
        terminal.read_until("New password: ")
        terminal.answer("first-private-answer")
        terminal.read_until("Confirm new password: ")
        if abort == "mismatch":
            terminal.answer("second-private-answer")
        else:
            terminal.process.send_signal(signal.SIGINT)
        code, output = terminal.finish()
        assert code == (2 if abort == "mismatch" else 130), output
        assert "first-private-answer" not in output
        assert "second-private-answer" not in output
        assert "Traceback" not in output
        assert source.read_bytes() == original
        assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]
    finally:
        terminal.close()
