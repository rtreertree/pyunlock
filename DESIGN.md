# pyunlock — Application Design

Status: design specification. The Python application has not been implemented. The install/uninstall scripts and manual commands below are templates for the future repository.

## 1. Purpose

`pyunlock` is a Python command-line application that unlocks PDFs using an existing password or locks PDFs with a new password. It processes one or more files, folders, or a mixture of both in a single command. Processing happens locally; PDFs and passwords are never uploaded.

The first release targets macOS and Linux, including Linux under WSL. It supports known-password decryption and password-based encryption. Password recovery, brute-force guessing, and changing an already encrypted PDF's password in one operation are outside the scope.

## 2. Command-line interface

```text
pyunlock -f PATH [PATH ...] [-a {unlock,lock}] [-p PASSWORD] [-m {replace,new}] [-r]
pyunlock --help
pyunlock --version
```

| Option | Meaning | Default |
| --- | --- | --- |
| `-f`, `--files` | One or more file or folder paths; may be repeated | Required |
| `-a`, `--action` | Operation: `unlock` removes protection; `lock` adds protection | `unlock` |
| `-p`, `--password` | Existing password for unlocking, or new password for locking; shared across the batch | Prompt when needed |
| `-m`, `--mode` | Output mode: `replace` or `new` | `replace` |
| `-r`, `--recursive` | Include PDFs in subfolders | Disabled |
| `-h`, `--help` | Show usage and examples | — |
| `--version` | Show the installed version | — |

Examples:

```bash
# Unlock one file in place; replace is the default.
pyunlock -f invoice.pdf -p 'my-password'

# Keep the original and create invoice_unlock.pdf beside it.
pyunlock -f invoice.pdf -p 'my-password' -m new

# Process several files and folders with the same password.
pyunlock -f invoice.pdf statement.pdf ./receipts ./reports -p 'my-password'

# Repeated -f options are equivalent to one combined list.
pyunlock -f invoice.pdf -f ./reports -p 'my-password'

# Include subfolders and write new files.
pyunlock -f ./archive -p 'my-password' -m new -r

# Omit -p to enter a password without displaying it.
pyunlock -f 'Monthly Statement.pdf'

# Explicitly supply an empty password.
pyunlock -f statement.pdf -p ''

# Lock a PDF in place with a new password.
pyunlock -a lock -f invoice.pdf -p 'new-password'

# Keep the original and create invoice_lock.pdf.
pyunlock -a lock -f invoice.pdf -p 'new-password' -m new

# Lock several files and all PDFs in a folder, including subfolders.
pyunlock -a lock -f invoice.pdf ./reports -p 'new-password' -m new -r

# Prompt for a new password and confirmation without displaying either.
pyunlock -a lock -f invoice.pdf -m new

# Unlock the resulting file; -a unlock is optional.
pyunlock -a unlock -f invoice_lock.pdf -p 'new-password'
```

`--action` selects what happens to the PDF; `--mode` selects where the output is written. Existing commands without `-a` continue to unlock PDFs, with `replace` as the default output mode.

Quote paths containing spaces. Prefix paths beginning with a hyphen with `./`, for example `./-statement.pdf`. Use `--password='-secret'` for passwords beginning with a hyphen. Shell-expanded patterns such as `-f ./*.pdf` work; the application does not expand quoted glob patterns itself.

Password handling:

- For `unlock`, if `-p` is omitted, prompt once with `getpass` when the first encrypted PDF requires it, then reuse the answer for the batch.
- For `lock`, if `-p` is omitted, prompt for the new password and a matching confirmation before writing the first eligible PDF. Reuse the confirmed password for the batch. Mismatched confirmation aborts the invocation with exit code `2` before any file is written.
- Locking requires a nonempty password. Reject `-a lock -p ''` or an empty interactive password with exit code `2` before writing anything. Preserve accepted passwords exactly; do not trim whitespace. An explicitly supplied nonempty `-p` does not require confirmation.
- Without an interactive terminal, files requiring a missing password fail with a clear message; the program must not hang waiting for input. Unlocking can still skip unencrypted inputs. Locking must never fall back to an empty password.
- Distinguish an omitted password from an explicitly empty password; an empty password remains allowed for unlocking.
- Never include passwords in output, logs, or exception messages. Supplying `-p` can expose the value through shell history or process arguments; the prompt avoids those exposures.

## 3. Output modes

| Action | Mode | Input | Successful output | Original |
| --- | --- | --- | --- | --- |
| `unlock` | `replace` | `report.pdf` | `report.pdf` | Replaced only after output validation |
| `unlock` | `new` | `report.pdf` | `report_unlock.pdf` | Unchanged |
| `unlock` | `new` | `report.final.PDF` | `report.final_unlock.PDF` | Unchanged |
| `lock` | `replace` | `report.pdf` | `report.pdf` | Replaced only after output validation |
| `lock` | `new` | `report.pdf` | `report_lock.pdf` | Unchanged |
| `lock` | `new` | `report.final.PDF` | `report.final_lock.PDF` | Unchanged |

Insert `_unlock` or `_lock`, according to the action, immediately before the final extension and preserve the extension's capitalization. Outputs stay in the source folder. Locking with `new` deliberately retains the unencrypted original; locking with `replace` does not securely erase old filesystem blocks or backup copies.

- `replace` operates without a file-replacement confirmation prompt because it is the requested default. It does not create a permanent backup; use `new` to retain the original. Interactive lock password confirmation still applies.
- In `new` mode, an existing destination is a per-file error. Do not overwrite it, automatically number it, or overwrite another input in the batch.
- During `unlock`, an already unencrypted PDF is reported as `SKIP` in either mode, with no rewrite or additional copy.
- During `lock`, an already encrypted PDF is reported as `ERROR: already encrypted; unlock it first`, with no changes or additional copy. Do not report success: its existing password may differ from the requested one. This also applies to encrypted PDFs that open with an empty password.
- Filename suffixes do not determine encryption state. Append the action's suffix to the existing stem without stripping earlier suffixes; for example, unlocking `report_lock.pdf` with `new` produces `report_lock_unlock.pdf`.

## 4. Input discovery and batch behavior

1. Accept regular PDF files and directories. Match `.pdf` extensions case-insensitively.
2. For each directory, inspect immediate children only unless `-r` is present.
3. Build the complete input list before writing any outputs. Files created during this run must not become new inputs.
4. Preserve the order of explicit inputs; sort each folder's discovered paths. Deduplicate normalized absolute paths, including overlapping folder selections.
5. Ignore non-PDF files found inside folders. An explicitly selected non-PDF file, missing path, unreadable directory, or unsupported file type is an error.
6. Do not follow file or directory symlinks. Report explicitly supplied symlinks as errors and discovered symlinks as skips. Reject multiply hard-linked input files in the first release to avoid ambiguous replacement behavior.
7. Report an empty folder as `SKIP`. If no eligible PDFs exist anywhere in the invocation, exit with an error.
8. Process PDFs sequentially. Continue after individual failures and return an unsuccessful batch status if any input or discovery step failed.

Use one action and one password per invocation. For unlocking, files using a different password fail independently; users can process them in a separate command. For locking, apply the same new password to every eligible unencrypted PDF; already encrypted inputs fail independently while the batch continues.

## 5. Encryption, decryption, and safe writing

Use `pypdf[crypto]` for PDF parsing, password decryption, and encryption. The crypto extra supplies support needed for AES-encrypted PDFs. Start with Python 3.11+ and select a tested dependency version during implementation. [pypdf installation documentation](https://pypdf.readthedocs.io/en/stable/user/installation.html)

### Locking behavior

Locking requires a password to open and read the output PDF. Use `algorithm="AES-256"` explicitly; never rely on the library's default encryption algorithm. No algorithm-selection option is needed in the first release. [pypdf encryption documentation](https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html)

Use the supplied password for both the PDF user and owner passwords. This feature protects opening the document; it does not offer separate printing, copying, or editing restrictions after the password is supplied. The library supports explicit user and owner password arguments. [PdfWriter API](https://pypdf.readthedocs.io/en/stable/modules/PdfWriter.html)

Core operation, after input and password validation:

```python
writer = PdfWriter(clone_from=reader)
writer.encrypt(
    user_password=password,
    owner_password=password,
    algorithm="AES-256",
)
```

### Shared processing workflow

Per-file workflow:

1. Open the source read-only and inspect whether it is encrypted. For `unlock`, skip unencrypted files. For `lock`, reject encrypted files and continue with eligible unencrypted files.
2. For `unlock`, call `reader.decrypt(password)` and check its return value. A failed password is an error; do not write an output. `reader.is_encrypted` remains true after successful decryption, so it must not be used as the success check. For `lock`, obtain the nonempty new password and any required confirmation. [PdfReader API](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html)
3. Create `PdfWriter(clone_from=reader)`. For `unlock`, write without calling `encrypt()`. For `lock`, call `encrypt()` as specified above before writing. Cloning the document is preferred to copying only pages so document-level structures are retained where supported. [pypdf decryption example](https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html)
4. Write to a uniquely named temporary file in the source directory, with owner-only permissions while incomplete. Never open the original for writing.
5. Flush and synchronize the temporary file, then validate according to the action. For `unlock`, reopen without a password and check that it is unencrypted, readable, and has the same page count. For `lock`, reopen and verify that it is encrypted, that an empty password fails to decrypt it, and that the supplied password succeeds and permits reading the original number of pages. An encryption flag alone does not establish that opening is protected. Close all source and validation handles before publishing.
6. In `replace` mode, preserve the source's ordinary permission bits, check that its identity, size, and modification time have not changed since opening, and publish with `os.replace()`. Abort if a change is detected. This check does not provide locking against concurrent editors; users should not modify files during a run.
7. In `new` mode, retain owner-only permissions and publish using a filesystem operation that atomically fails if the destination exists, such as `os.link(temp, destination)` followed by unlinking the temporary name. A separate existence check followed by an overwriting rename is insufficient. If the filesystem cannot provide this operation, fail that file without touching the source.
8. Synchronize the containing directory where supported. Clean up temporary files after handled failures and interruption. Previously completed files remain completed; there is no batch-wide rollback.

An error before publication leaves the source unchanged. A synchronization failure after publication must explicitly report that output was published but durability could not be confirmed. A forced process kill can leave a temporary file, but must not truncate an original PDF.

Preservation goals include pages, text, images, metadata, bookmarks, links, annotations, attachments, and form values where supported. Verify these with representative fixtures. Rewriting does not preserve byte identity or the validity of existing digital signatures. Extended attributes, ACLs, and original timestamps are outside the initial preservation guarantee.

## 6. Output and exit codes

Use plain text with one result per processed PDF and a final summary. Success and skip lines go to stdout; failures go to stderr. Escape control characters in displayed filenames so each result stays on one line. Expected errors must not print a Python traceback.

```text
OK    invoice.pdf -> invoice_unlock.pdf
SKIP  notes.pdf: already unlocked
ERROR statement.pdf: incorrect password; original unchanged

Done: 1 unlocked, 1 skipped, 1 failed.
```

For locking, name the operation in success lines and use a `locked` summary count:

```text
OK    invoice.pdf -> invoice_lock.pdf (locked)
ERROR statement.pdf: already encrypted; unlock it first; original unchanged

Done: 1 locked, 0 skipped, 1 failed.
```

Discovery errors contribute to the failed count. Duplicate paths are silently deduplicated and do not count as additional results. Ignored non-PDF directory entries are omitted from the summary.

| Code | Meaning |
| --- | --- |
| `0` | All eligible inputs completed the selected action or were valid skips, with no discovery errors |
| `1` | One or more processing/discovery errors, or no eligible PDFs found |
| `2` | Invalid syntax, missing `-f`, invalid action/mode, empty lock password, or mismatched password confirmation |
| `130` | Interrupted with Ctrl+C |

## 7. Python package structure

```text
pyunlock/
├── pyproject.toml
├── README.md
├── DESIGN.md
├── install.sh
├── uninstall.sh
├── src/
│   └── pyunlock/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py          # argparse, password prompt, output, exit codes
│       ├── discovery.py    # path validation, folder scanning, deduplication
│       ├── unlocker.py     # decrypt and validate unencrypted output
│       ├── locker.py       # encrypt and validate password-protected output
│       └── fileio.py       # shared temporary-file handling and safe publication
└── tests/
    ├── test_cli.py
    ├── test_discovery.py
    ├── test_unlocker.py
    ├── test_locker.py
    ├── test_fileio.py
    └── fixtures/
```

Use standard-library `argparse`, `pathlib`, `getpass`, `tempfile`, and `os`. Represent each file's result as a small structured object containing its source, optional destination, status, and a password-free error message. The CLI renders results; the PDF layer does not print them.

Minimal packaging template:

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "pyunlock"
version = "0.1.0"
description = "Lock and unlock PDFs locally with a password"
requires-python = ">=3.11"
dependencies = ["pypdf[crypto]>=7,<8"]

[project.scripts]
pyunlock = "pyunlock.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

The dependency range is provisional until compatibility tests pass. Keep `main()` returning an integer exit code and have `__main__.py` call `raise SystemExit(main())`, supporting both `pyunlock` and `python -m pyunlock`. The console command is generated from `[project.scripts]`. [Python packaging guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)

## 8. Installation from Git

### User experience

Publish `install.sh` at the root of the GitHub repository. Replace `YOUR_GITHUB_USERNAME` in both the command and installer before publishing. This URL is a placeholder and is not currently a working installation endpoint.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/pyunlock/main/install.sh)"
```

Requirements: Bash, `curl` to download the installer, Git, and Python 3.11+ with working `venv` and `pip` support. The installer checks requirements and gives actionable errors for missing components.

Install into a private environment under `~/.local/share/pyunlock/envs/` and expose the command at `~/.local/bin/pyunlock`. No administrator access or environment activation is needed. A virtual environment isolates application dependencies from system Python. [Python venv documentation](https://docs.python.org/3/library/venv.html)

### Exact installation locations

Use the same per-user layout on macOS and Linux. `~` means the current user's home directory. Installation paths are fixed for the first release; do not run these commands with `sudo`.

| Item | Location | Purpose |
| --- | --- | --- |
| Application root | `~/.local/share/pyunlock/` | Dedicated directory owned by this installation |
| Ownership marker | `~/.local/share/pyunlock/.pyunlock-managed` | Contains `pyunlock-install-v1`; allows the uninstaller to recognize its directory |
| Installed environments | `~/.local/share/pyunlock/envs/install.XXXXXX/` | Installer creates a unique environment on each install/update |
| Manual environment | `~/.local/share/pyunlock/envs/manual/` | Environment used by the manual steps below |
| Actual executable | `<environment>/bin/pyunlock` | Python-generated command inside an environment |
| Public command | `~/.local/bin/pyunlock` | Symlink to the active environment's executable |
| Python and dependencies | Inside each environment | Application and its dependencies are isolated together |
| Optional Git checkout | Any directory chosen by the user | Source code; separate from the installed application |
| PDF outputs | Beside each input PDF | Never stored in the application installation directory |

For example, on a Mac with username `alice`, the command is `/Users/alice/.local/bin/pyunlock`; on Linux it is typically `/home/alice/.local/bin/pyunlock`. No application configuration file or persistent log directory is needed in the first release. Pip may use its normal shared download cache; uninstalling pyunlock does not remove that shared cache.

Each installation creates a fresh environment in its permanent location, installs and checks it, then switches the command symlink. Do not move an installed virtual environment: its scripts can contain absolute paths. If preparation fails, the existing command keeps working. Retain older successful environments for rollback; automatic pruning is outside the initial installer.

### Reference `install.sh`

This is proposed script content to add when the Python package exists. It installs `main` for development; release copies should set `PYUNLOCK_REF` to a tested tag or full commit and use the corresponding ref in the download URL. Pip supports Git URLs with branch, tag, and commit refs. [pip VCS documentation](https://pip.pypa.io/en/stable/topics/vcs-support/)

```bash
#!/bin/bash
set -euo pipefail

fail() { printf 'pyunlock installer: %s\n' "$*" >&2; exit 1; }

PYUNLOCK_REPO="${PYUNLOCK_REPO:-YOUR_GITHUB_USERNAME/pyunlock}"
PYUNLOCK_REF="${PYUNLOCK_REF:-main}"
PYUNLOCK_PYTHON="${PYUNLOCK_PYTHON:-python3}"
PYUNLOCK_ROOT="$HOME/.local/share/pyunlock"
PYUNLOCK_BIN="$HOME/.local/bin"

[[ "$PYUNLOCK_REPO" != YOUR_GITHUB_USERNAME/* ]] ||
    fail 'Set the GitHub owner/repository before publishing or running this template.'
case "$(uname -s)" in
    Darwin|Linux) ;;
    *) fail 'This installer supports macOS and Linux.' ;;
esac
command -v git >/dev/null 2>&1 || fail 'Install Git, then rerun this installer.'
command -v "$PYUNLOCK_PYTHON" >/dev/null 2>&1 ||
    fail 'Install Python 3.11+ or set PYUNLOCK_PYTHON to its executable.'
"$PYUNLOCK_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
    fail 'Python 3.11 or newer is required.'

[[ ! -L "$PYUNLOCK_ROOT" ]] || fail 'Application root must not be a symlink.'
if [[ -e "$PYUNLOCK_ROOT" ]]; then
    [[ -d "$PYUNLOCK_ROOT" && -f "$PYUNLOCK_ROOT/.pyunlock-managed" && ! -L "$PYUNLOCK_ROOT/.pyunlock-managed" ]] ||
        fail 'Existing application directory is not a managed pyunlock installation.'
    [[ "$(cat "$PYUNLOCK_ROOT/.pyunlock-managed")" == 'pyunlock-install-v1' ]] ||
        fail 'Unrecognized installation marker.'
else
    mkdir -p "$PYUNLOCK_ROOT"
    printf '%s\n' 'pyunlock-install-v1' > "$PYUNLOCK_ROOT/.pyunlock-managed"
fi
[[ ! -L "$PYUNLOCK_ROOT/envs" ]] || fail 'Environment directory must not be a symlink.'
mkdir -p "$PYUNLOCK_ROOT/envs" "$PYUNLOCK_BIN"
PYUNLOCK_ENV="$(mktemp -d "$PYUNLOCK_ROOT/envs/install.XXXXXX")"
PYUNLOCK_STAGE="$(mktemp -d "$PYUNLOCK_BIN/.pyunlock.XXXXXX")"

cleanup() {
    rm -rf -- "$PYUNLOCK_STAGE"
    # Keep environments after publication, including if interrupted immediately after it.
    if [[ "$(readlink "$PYUNLOCK_BIN/pyunlock" 2>/dev/null || true)" != "$PYUNLOCK_ENV/bin/pyunlock" ]]; then
        rm -rf -- "$PYUNLOCK_ENV"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$PYUNLOCK_PYTHON" -m venv "$PYUNLOCK_ENV" ||
    fail 'Python venv/pip support is unavailable. Install it, then retry.'
"$PYUNLOCK_ENV/bin/python" -m pip install \
    "git+https://github.com/${PYUNLOCK_REPO}.git@${PYUNLOCK_REF}"
"$PYUNLOCK_ENV/bin/python" -m pip check
"$PYUNLOCK_ENV/bin/pyunlock" --version

# Publish only after installation and checks succeed.
"$PYUNLOCK_PYTHON" - "$PYUNLOCK_ROOT" "$PYUNLOCK_ENV" "$PYUNLOCK_BIN" "$PYUNLOCK_STAGE" <<'PY'
import os
import sys
from pathlib import Path

root, environment, bin_dir, stage = map(Path, sys.argv[1:])
destination = bin_dir / "pyunlock"
if os.path.lexists(destination):
    managed = False
    if destination.is_symlink():
        existing = Path(os.readlink(destination))
        managed = (
            existing.is_absolute()
            and existing.parent.name == "bin"
            and existing.name == "pyunlock"
            and existing.parent.parent.parent == root / "envs"
        )
    if not managed:
        raise SystemExit(f"Refusing to overwrite an unrelated command: {destination}")
temporary_link = stage / "pyunlock"
temporary_link.symlink_to(environment / "bin" / "pyunlock")
os.replace(temporary_link, destination)
PY

printf 'Installed: %s/pyunlock\n' "$PYUNLOCK_BIN"
case ":$PATH:" in
    *":$PYUNLOCK_BIN:"*) ;;
    *) printf '%s\n' 'Add this line to ~/.zshrc or ~/.bashrc, then open a new terminal:' \
        'export PATH="$HOME/.local/bin:$PATH"' ;;
esac
```

The installer prints the PATH change because a child process cannot update the invoking shell. It must not silently modify shell startup files. After setup, verify with `pyunlock --version` and `pyunlock --help`.

Rerun the installer to update. A failed download or package installation must produce a nonzero exit status. For scripts that must detect download failure independently of Bash execution, use:

```bash
installer="$(curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/pyunlock/main/install.sh)" && /bin/bash -c "$installer"
```

The Homebrew-style command above remains the short interactive form requested. For a published release, use the same release ref in the raw script URL and the installer's package source.

### Manual installation from a Git checkout

After the application is implemented and published, users can clone the source and inspect the installer before running it:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/pyunlock.git
cd pyunlock
less install.sh
/bin/bash install.sh
```

To install directly from the checkout **without running the installer**, use the following steps instead. Run this block from the repository root. These are fresh-install instructions: they refuse an existing application directory or command. Use the installer for updates, or uninstall first and repeat these steps. Python 3.11+, `venv`, and `pip` are required.

```bash
(
    set -euo pipefail
    PYUNLOCK_ROOT="$HOME/.local/share/pyunlock"
    PYUNLOCK_BIN="$HOME/.local/bin"
    PYUNLOCK_ENV="$PYUNLOCK_ROOT/envs/manual"

    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    test -f pyproject.toml || { printf 'Run from the pyunlock repository root.\n' >&2; exit 1; }
    if [[ -e "$PYUNLOCK_ROOT" || -L "$PYUNLOCK_ROOT" || -e "$PYUNLOCK_BIN/pyunlock" || -L "$PYUNLOCK_BIN/pyunlock" ]]; then
        printf 'An installation path already exists; inspect it before continuing.\n' >&2
        exit 1
    fi

    mkdir -p "$HOME/.local/share" "$PYUNLOCK_BIN"
    mkdir "$PYUNLOCK_ROOT"
    printf '%s\n' 'pyunlock-install-v1' > "$PYUNLOCK_ROOT/.pyunlock-managed"
    python3 -m venv "$PYUNLOCK_ENV"
    "$PYUNLOCK_ENV/bin/python" -m pip install .
    "$PYUNLOCK_ENV/bin/python" -m pip check
    "$PYUNLOCK_ENV/bin/pyunlock" --version
    ln -s "$PYUNLOCK_ENV/bin/pyunlock" "$PYUNLOCK_BIN/pyunlock"
)
```

If installation fails after creating the application directory, the uninstall script below can remove that incomplete managed installation. The command is linked only after the package installs successfully.

Make the command available in the current terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
pyunlock --version
pyunlock --help
```

For future terminals, add `export PATH="$HOME/.local/bin:$PATH"` once to `~/.zshrc` when using Zsh, or `~/.bashrc` when using interactive Bash. Login Bash sessions may need the line in `~/.bash_profile` or that file to source `~/.bashrc`. The source checkout can be moved or deleted after this non-editable installation succeeds; the installed environment must remain in place.

### Uninstallation

Publish `uninstall.sh` at the repository root alongside `install.sh`. Run it from a retained Git checkout:

```bash
/bin/bash uninstall.sh
```

Or download and run it, stopping if the download fails:

```bash
uninstaller="$(curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/pyunlock/main/uninstall.sh)" && /bin/bash -c "$uninstaller"
```

This command explicitly requests removal, so the script does not ask for a second confirmation. It removes the managed command symlink and the entire marked application root, including old environments and incomplete installs. It leaves the Git checkout, PDFs, shared pip cache, `~/.local/bin`, and shell startup files in place. Keep documents outside the dedicated application root: everything inside that marked directory is removed.

The uninstaller requires an available Python 3 interpreter; use `PYUNLOCK_PYTHON` to select one if necessary. It validates all paths before deleting anything, refuses an unmarked installation directory or an unrelated command, and returns success when the application is already absent. Stop running pyunlock processes before uninstalling or updating. Concurrent install/uninstall operations are not supported.

### Reference `uninstall.sh`

```bash
#!/bin/bash
set -euo pipefail

PYUNLOCK_PYTHON="${PYUNLOCK_PYTHON:-python3}"
PYUNLOCK_ROOT="$HOME/.local/share/pyunlock"
PYUNLOCK_COMMAND="$HOME/.local/bin/pyunlock"

command -v "$PYUNLOCK_PYTHON" >/dev/null 2>&1 || {
    printf 'Python 3 is required; set PYUNLOCK_PYTHON to its executable.\n' >&2
    exit 1
}

"$PYUNLOCK_PYTHON" - "$PYUNLOCK_ROOT" "$PYUNLOCK_COMMAND" <<'PY'
import os
import shutil
import sys
from pathlib import Path

root, command = map(Path, sys.argv[1:])
marker = root / ".pyunlock-managed"
root_exists = os.path.lexists(root)
command_exists = os.path.lexists(command)

def fail(message):
    raise SystemExit(f"pyunlock uninstaller: {message}")

# Validate every target before removing either one.
if root_exists:
    if root.is_symlink() or not root.is_dir():
        fail(f"Refusing an unexpected application root: {root}")
    if marker.is_symlink() or not marker.is_file():
        fail(f"Installation marker is missing: {marker}")
    if marker.read_text(encoding="utf-8").strip() != "pyunlock-install-v1":
        fail(f"Unrecognized installation marker: {marker}")

if command_exists:
    if not command.is_symlink():
        fail(f"Refusing to remove an unrelated command: {command}")
    target = Path(os.readlink(command))
    managed = (
        target.is_absolute()
        and target.name == "pyunlock"
        and target.parent.name == "bin"
        and target.parent.parent.name not in (".", "..")
        and target.parent.parent.parent == root / "envs"
    )
    if not managed:
        fail(f"Command does not point to a managed environment: {command}")

if command_exists:
    command.unlink()
    print(f"Removed command: {command}")
if root_exists:
    shutil.rmtree(root)
    print(f"Removed application: {root}")
if not root_exists and not command_exists:
    print("pyunlock is already uninstalled.")
else:
    print("pyunlock uninstalled.")
PY
```

Run `command -v pyunlock` afterward. If it still finds a command, another installation exists elsewhere on PATH and is outside this script's scope. A stale shell command cache can be refreshed by opening a new terminal. Retain the `~/.local/bin` PATH entry if other applications use it.

## 9. Acceptance criteria

- A fresh install exposes `pyunlock` after the documented PATH setup. Installation works with spaces in the user's home path and does not modify system Python.
- Installer checks cover missing prerequisites, bad repository/ref, network failure, repeated installation, unrelated command collisions, and failed updates preserving the previous command.
- Manual installation produces the same managed layout and works after removing the source checkout.
- Uninstallation covers a normal install, multiple retained environments, an incomplete install, a dangling managed symlink, and repeated execution. It preserves external PDFs and refuses unrelated commands, unmarked roots, and symlinked application roots before deleting anything.
- Existing commands without `-a` still unlock. `-a lock` and `--action lock` select locking; invalid actions fail before writing.
- For both actions, default `replace` retains the exact path; `new` creates the expected `_unlock` or `_lock` filename and leaves original bytes unchanged.
- Single files, multiple files, multiple folders, mixed inputs, repeated `-f`, Unicode paths, uppercase extensions, recursion, and duplicate paths behave as specified.
- Unlocking covers correct user and owner passwords, empty passwords, RC4, and AES variants supported by the selected library with generated fixtures.
- Locking produces AES-256 output readable with the new password and unreadable with an empty or incorrect password. Include Unicode passwords and multiple files sharing one new password.
- Locking prompts for matching confirmation only when `-p` is omitted. Empty passwords, mismatches, and noninteractive missing passwords produce the specified failures without writing affected files or logging secrets.
- Locking an already encrypted PDF, including one with an empty opening password, fails without changing its bytes. Mixed encrypted/unencrypted batches still lock eligible inputs and return exit code `1`.
- A lock-then-unlock round trip preserves the supported document content and page count. Both actions reject an output that fails validation before publishing.
- Wrong passwords, corrupt PDFs, unreadable paths, unwritable destinations, and existing output names return useful errors without damaging inputs.
- Simulated write, validation, and publication failures preserve originals. A concurrently created `new` destination is never overwritten.
- During unlocking, already unlocked PDFs are unchanged. During locking, they are eligible inputs. Generated outputs are not processed again during the same run.
- Representative document fixtures retain page count and supported content, metadata, bookmarks, annotations, attachments, and form values.
- Mixed batches report every result and return the appropriate exit code. Passwords never appear in captured application output or errors.
- Validate the installer with Bash syntax checks and installation tests on macOS and Linux before publishing it.

## 10. Implementation order

1. Create the package and CLI, including action selection, `--help`, `--version`, and action-specific password prompting.
2. Implement discovery, single-file decryption, and AES-256 encryption with action-specific output validation.
3. Add shared safe publication for both output modes, batch reporting, failure tests, and lock/unlock round-trip tests.
4. Add the installer and uninstaller, set the actual GitHub repository, and test fresh installs, manual installs, upgrades, and removal.
5. Publish a tested release and add the install command plus usage examples to `README.md`.
