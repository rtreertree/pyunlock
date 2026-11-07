# pyunlock

Lock and unlock PDFs locally using a known password. Process files and folders
in one batch on macOS or Linux, including WSL. Documents and passwords stay on
your computer. Python 3.11+ is required; installation uses `pypdf[crypto]` 7.x
(tested with 7.0.0).

```bash
pyunlock -f PATH [PATH ...] [-a unlock|lock] [-p PASSWORD] [-m replace|new] [-r]
```

The defaults are **unlock** and **replace**. Replacement happens only after a
temporary output has been written and validated. There is no permanent backup;
choose `-m new` to retain the original.

## Usage

```bash
# Original syntax: unlock in place.
pyunlock -f invoice.pdf -p 'existing-password'

# Private password prompt; create invoice_unlock.pdf.
pyunlock -f invoice.pdf -m new

# Multiple paths, repeated -f, and recursive folder discovery.
pyunlock -f invoice.pdf ./receipts -f ./reports -m new -r

# Lock in place, prompting for a new password and matching confirmation.
pyunlock -a lock -f 'Monthly Statement.pdf'

# Create invoice_lock.pdf; the unencrypted original remains.
pyunlock --action lock -f invoice.pdf -p 'new-password' -m new

# Unlock with an explicitly empty password when the input uses one.
pyunlock -f statement.pdf -p ''

pyunlock --help
pyunlock --version
python3 -m pyunlock --help  # use the Python interpreter where it is installed
```

One action and one password apply to the entire invocation. Omit `-p` to enter
the password without echoing it. Unlocking prompts once, only when an encrypted
input needs a password; locking prompts and confirms once, before its first
eligible output is written. Lock passwords cannot be empty; whitespace is kept
exactly. Without an interactive terminal, provide `-p` or affected inputs fail
promptly. Passwords supplied with `-p` may appear in shell history and process
arguments. Application errors and logs do not include password values.

Quote paths with spaces. Prefix a path starting with a hyphen with `./`, and use
`--password='-secret'` for a password starting with a hyphen. Shell-expanded
patterns such as `-f ./*.pdf` work; quoted patterns are not expanded by pyunlock.

| Option | Meaning | Default |
| --- | --- | --- |
| `-f`, `--files` | One or more PDF files or folders; repeatable | Required |
| `-a`, `--action` | `unlock` or `lock` | `unlock` |
| `-p`, `--password` | Shared existing/new password | Private prompt when needed |
| `-m`, `--mode` | `replace` or `new` | `replace` |
| `-r`, `--recursive` | Include PDFs in subfolders | Off |
| `-h`, `--help` | Usage and examples | — |
| `--version` | Installed version | — |

`new` inserts `_unlock` or `_lock` before the final extension, preserving its
capitalization: `report.final.PDF` becomes `report.final_lock.PDF`. Earlier
suffixes stay: unlocking `report_lock.pdf` produces `report_lock_unlock.pdf`.
An existing destination is an error and is never overwritten or numbered.
Unencrypted inputs are `SKIP` during unlocking, with no copy or rewrite.
Encrypted inputs are errors during locking, including PDFs with an empty opening
password; unlock them first.

Inputs are discovered completely before processing. Explicit input order is
preserved, each folder's discovered PDFs are sorted, and normalized absolute
paths are deduplicated. `.pdf` matching is case-insensitive. Non-PDF folder
entries are ignored; an explicitly selected non-PDF, missing/unreadable path, or
unsupported file is an error. Explicit symlinks (including symlink path
components) are rejected, discovered symlinks are skipped, and multiply
hard-linked PDFs are rejected. Empty folders are skipped; no eligible PDFs is an
unsuccessful invocation.

Results use plain text: `OK` and `SKIP` go to stdout, `ERROR` to stderr. Filenames
have control characters escaped. A final summary counts completed, skipped, and
failed results, including discovery failures. Processing continues after an
individual error. Exit codes are `0` for completion/valid skips without errors,
`1` for processing/discovery errors or no eligible PDFs, `2` for syntax or invalid
lock password/confirmation, and `130` for Ctrl+C. Completed outputs remain after
an interruption or later failure; there is no batch rollback.

## Installation

Prerequisites: Bash, Python 3.11+ with working `venv` and `pip`, and Git for
installation from GitHub. Download commands also need `curl`. On Linux, your
distribution may package `venv` separately (for example, `python3-venv`).
The installer reports missing requirements. No administrator access or virtual
environment activation is needed. Do not run installation or removal with
`sudo`.

Source: [rtreertree/pyunlock](https://github.com/rtreertree/pyunlock).
The installer defaults to this repository's `main` branch.

Inspect the scripts in a checkout, then install it into the managed layout:

```bash
git clone https://github.com/rtreertree/pyunlock.git
cd pyunlock
less install.sh
PYUNLOCK_SOURCE="$PWD" /bin/bash install.sh
```

`PYUNLOCK_SOURCE` must be an absolute path to a checkout or wheel. Omit it to
install from `rtreertree/pyunlock` on GitHub. Override the source with
`PYUNLOCK_REPO=owner/repository` and optionally `PYUNLOCK_REF=tag-or-commit`
(default `main`). Set `PYUNLOCK_PYTHON` to select a
Python executable, for example `PYUNLOCK_PYTHON=python3.12`. These variables select
the package/interpreter; installation paths remain fixed under the current
user's home directory.

The short remote install command is:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/rtreertree/pyunlock/main/install.sh)"
```

For scripts, explicitly stop when the download fails:

```bash
installer="$(curl -fsSL https://raw.githubusercontent.com/rtreertree/pyunlock/main/install.sh)" && /bin/bash -c "$installer"
```

For a published release, use the same tested tag or commit in the raw script URL
and `PYUNLOCK_REF`. No release has been published by this implementation task.

| Item | Exact location |
| --- | --- |
| Dedicated application root | `~/.local/share/pyunlock/` |
| Ownership marker (contents `pyunlock-install-v1`) | `~/.local/share/pyunlock/.pyunlock-managed` |
| Automated environments | `~/.local/share/pyunlock/envs/install.XXXXXX/` |
| Manual environment | `~/.local/share/pyunlock/envs/manual/` |
| Actual executable | `<environment>/bin/pyunlock` |
| Public command symlink | `~/.local/bin/pyunlock` |
| Optional checkout | Any directory you choose, separate from the installation |
| PDF outputs | Beside the corresponding input PDF |

Here `~` means your home directory: for example `/Users/alice` on macOS or
`/home/alice` on Linux. Keep documents outside the dedicated application root;
uninstalling removes everything in that marked directory.

Make the command available in the current terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
pyunlock --version
pyunlock --help
```

For future terminals, add that `export` line once to `~/.zshrc` for Zsh or
`~/.bashrc` for interactive Bash. Login Bash may need it in `~/.bash_profile`, or
that file may source `~/.bashrc`. The installer only prints this advice; it does
not edit shell startup files.

### Updating and rollback

Rerun `install.sh`, with the same source selection options if needed. Each run
creates a fresh environment at its permanent path, installs and checks it, then
atomically switches the public command symlink. A failed preparation keeps the
working command. Successful older environments are retained; automatic pruning
is outside this release. Stop running pyunlock and avoid concurrent
install/update/uninstall operations.

For rollback, inspect the retained environments and test the desired absolute
`<environment>/bin/pyunlock --version`. Create a temporary symlink in
`~/.local/bin` pointing to that environment's executable and use Python's
`os.replace()` to switch it over `~/.local/bin/pyunlock`. Do not move environments:
their executable scripts contain absolute paths. Unrelated commands or unmarked
installation directories are refused by the installer and uninstaller.

### Manual fresh installation

The following block installs directly from a checkout without invoking
`install.sh`. Run it with Bash from the repository root. It refuses existing
installation paths and checks parent directories before writing. Use the
installer for updates, or uninstall first. An interrupted/failed manual install
can leave a marked incomplete root; `uninstall.sh` can safely remove it.

```bash
# Manual fresh install
(
    set -euo pipefail
    python3 - <<'PY'
import os
import stat
import subprocess
import sys
from pathlib import Path

def fail(message):
    raise SystemExit(message)

if sys.version_info < (3, 11):
    fail("Python 3.11+ is required.")
if not Path("pyproject.toml").is_file():
    fail("Run from the pyunlock repository root.")
if not os.environ.get("HOME") or not Path(os.environ["HOME"]).is_absolute():
    fail("HOME must name an existing absolute directory.")
home = Path(os.environ["HOME"])
root, bin_dir = home / ".local/share/pyunlock", home / ".local/bin"
command = bin_dir / "pyunlock"
environment = root / "envs/manual"
os.umask(0o077)
for path in (home, home / ".local", home / ".local/share", bin_dir):
    if os.path.lexists(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            fail(f"Refusing unsafe installation parent: {path}")
    elif path == home:
        fail("HOME does not exist.")
if os.path.lexists(root) or os.path.lexists(command):
    fail("Installation path already exists; inspect it before continuing.")
for path in (home / ".local", home / ".local/share", bin_dir):
    path.mkdir(mode=0o700, exist_ok=True)
root.mkdir(mode=0o700)
with (root / ".pyunlock-managed").open("x", encoding="utf-8") as marker:
    marker.write("pyunlock-install-v1\n")
subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
python = str(environment / "bin/python")
subprocess.run([python, "-m", "pip", "install", "."], check=True)
subprocess.run([python, "-m", "pip", "check"], check=True)
subprocess.run([str(environment / "bin/pyunlock"), "--version"], check=True)
subprocess.run([python, "-m", "pyunlock", "--version"], check=True)
command.symlink_to(environment / "bin/pyunlock")  # fails if a command appeared
print(f"Installed: {command}")
PY
)
```

Set up PATH as above. This is a non-editable installation; the source checkout
can be moved or removed afterward. The installed environment must stay in place.

## Uninstalling

From a retained checkout:

```bash
/bin/bash uninstall.sh
```

Or download the uninstaller, stopping if the download fails:

```bash
uninstaller="$(curl -fsSL https://raw.githubusercontent.com/rtreertree/pyunlock/main/uninstall.sh)" && /bin/bash -c "$uninstaller"
```

Python 3 must be available (select it with `PYUNLOCK_PYTHON` if necessary). No
second confirmation is requested. The script validates the ownership marker,
installation parents and command before removing either target. It removes the
managed command symlink and entire marked root, including retained or incomplete
environments. It handles dangling managed links and repeat removal. It refuses
unrelated commands, unmarked roots and symlinked installation directories.
It leaves your PDFs outside the root, source checkout, shared pip cache,
`~/.local/bin`, and startup files intact. Keep the PATH entry if other apps use it.

Check `command -v pyunlock` afterward. Another installation elsewhere on PATH is
outside this script's scope; a new terminal also clears stale shell command
caches.

## Safety and preservation

Locking explicitly uses AES-256 with the supplied password as both the user and
owner password. It protects opening the document; it offers no separate
printing/copying/editing restrictions after opening. Password recovery, guessing,
and changing an encrypted PDF's password in one operation are outside scope.

Both actions clone the document through pypdf, preserving supported pages, text,
images, metadata, bookmarks, links, annotations, attachments and form values.
Representative fixtures test these structures. PDF features that pypdf cannot
preserve remain outside the guarantee. Rewriting changes bytes and invalidates
existing digital signatures; extended attributes, ACLs and original timestamps
are not preserved. `replace` does not securely erase old filesystem blocks,
snapshots, backups or other copies.

Output is written to a unique owner-only `.pyunlock-*.pdf` temporary file beside
the source, flushed and synchronized. Unlock validation reopens without a
password and checks unencrypted readability and page count. Lock validation
checks encryption, rejection of an empty password, and reading with the supplied
password and the original page count. All PDF handles close before publication.
Replacement preserves ordinary permission bits and checks the source's identity,
size and modification time before `os.replace()`. `new` uses an atomic hard link
that fails if the destination exists, retaining owner-only permissions. A
filesystem without hard-link publication support fails that file safely.

Directory synchronization is performed where supported. A failure after
publication explicitly reports that the output was published but durability
could not be confirmed. Failures before publication leave the original unchanged;
handled errors and Ctrl+C clean up temporary files. If filesystem permissions
prevent cleanup, a fixed error identifies the remaining private temporary name;
an interruption still returns `130`. A forced kill can leave a temporary file,
but cannot truncate the source. These checks do not lock out
concurrent editors: do not modify inputs or installation paths during a run.

## Development and verification

Use generated fixtures and temporary directories. Never run installer tests
against your real home directory. The test suite changes HOME to isolated
directories for installation/removal tests.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python -m build
.venv/bin/python -m pip install --force-reinstall dist/pyunlock-0.1.0-py3-none-any.whl
.venv/bin/python -m pytest
bash -n install.sh uninstall.sh
```

The suite imports the installed package, not `src` through a pytest path setting.
Installed CLI subprocess tests run from temporary directories without
`PYTHONPATH`. To run real installer integration tests without network access,
download dependencies to a wheelhouse and set `PYUNLOCK_TEST_WHEEL` to the absolute
wheel path and `PYUNLOCK_TEST_WHEELHOUSE` to that wheelhouse directory. These tests
otherwise skip explicitly. `PYUNLOCK_TEST_PYTHON` optionally selects the installed
interpreter for subprocess tests. See [REQUIREMENTS.md](REQUIREMENTS.md) for the
requirement-to-test reconciliation and measured platform coverage.

The GitHub Actions workflow in `.github/workflows/tests.yml` runs on pushes,
pull requests and manual dispatch. It builds the source archive and wheel,
installs the wheel in a fresh environment, and runs the full suite (including
real installer tests) on macOS and Ubuntu with Python 3.11, 3.12 and 3.13.
Check the [workflow results](https://github.com/rtreertree/pyunlock/actions)
before publishing. A configured workflow is not evidence of a passing run;
Linux/WSL and Python versions unavailable locally remain unverified until tested.

The dependency choices and PDF operations follow the upstream
[pypdf installation guide](https://pypdf.readthedocs.io/en/stable/user/installation.html),
[encryption/decryption guide](https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html)
and [writer API](https://pypdf.readthedocs.io/en/stable/modules/PdfWriter.html).
