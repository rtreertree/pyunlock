# Requirement-to-verification reconciliation

`DESIGN.md` is the source of truth and was read in full before implementation.
No applicable `AGENTS.md` was present. The initial workspace contained only the
design, with no Git metadata or configured remote. The original design is
preserved apart from the explicit automatic-PATH amendment requested later.
The user subsequently pushed the project to `rtreertree/pyunlock`; `origin` now
identifies that repository and its default branch is `main`.

| Design requirement | Implementation | Verification |
| --- | --- | --- |
| Local processing, Python 3.11+, tested crypto dependency | `pyproject.toml`, `src/pyunlock/` | Pass locally on Python 3.12.3, pypdf 7.0.0, cryptography 50.0.2. Application has no network/upload code. The prior committed version also passed hosted Python 3.11/3.12/3.13 checks. |
| Original syntax, unlock/replace defaults, action/mode selection, repeated multi-path `-f`, recursion | `cli.py` | Pass: CLI syntax/defaults/actions/modes/repeated-files/recursion tests. |
| Console/module entry points, help/version, integer `main()` return | packaging, `__main__.py`, `cli.py` | Pass: installed entry points outside checkout, help/version and rich-content round trips. |
| Lazy shared unlock prompt, distinguish omitted/empty password, unencrypted skip without prompt | password provider | Pass: explicit/interactive empty password, shared lazy prompt, noninteractive skips, real terminal module test. |
| Nonempty lock password, exact whitespace, confirmation before first write, mismatch code 2 | password provider, `locker.py` | Pass: empty explicit/interactive passwords, mismatch leaves entire batch intact, whitespace/Unicode, one confirmation per batch. |
| Noninteractive missing password must not hang or become empty | `cli.py` | Pass: both actions fail per file; installed subprocess stdin closed, bounded timeout. |
| Password-free output/errors/logs, no echoing fallback | parser, prompts, quiet PDF logging | Pass: captured output, typo/parser regression, injected secret-bearing exceptions, real terminal no-echo checks. |
| Complete input snapshot, explicit order, sorted folder PDFs, normalized deduplication | `discovery.py` | Pass: order, overlapping selections, relative/absolute deduplication, outputs never enter current batch. |
| Case-insensitive PDFs, shallow/recursive folders, ignored folder non-PDFs, explicit invalid/missing/unreadable paths | `discovery.py` | Pass: uppercase/Unicode, nested folders, invalid files, actual unreadable directory. |
| No symlink traversal; explicit links error, discovered links skip; hardlinks/unsupported explicit types fail | discovery and source opening | Pass: files/folders/ancestors/dangling links, hardlinks, FIFO, bypass-discovery checks; regressions for symlinks hidden by `..` and explicit links after folder discovery. |
| Empty folders skip; no eligible PDFs exits 1 | discovery, CLI | Pass: empty-folder and invalid-explicit-file tests. |
| Both actions/modes, exact replace path, suffix/extension preservation, retain earlier suffixes | PDF modules, shared file I/O | Pass: all combinations, uppercase final extension, original bytes unchanged in new mode. |
| Unencrypted unlock skip unchanged; encrypted lock error including empty opening password; mixed batches continue | `fileio.process_pdf` | Pass: bytes/mtime checks, already-encrypted cases, lazy prompts, mixed batches. |
| Explicit AES-256, equal supplied user/owner password, decrypt return checked, whole-document cloning | `locker.py`, `unlocker.py` | Pass: encryption dictionary V=5/R=6/Length=256/AESV3, empty/wrong rejection, supplied password success, user/owner unlocking. |
| Private unique same-directory temporary files; flush/fsync; action validation before publication | shared file I/O and validators | Pass: location/mode, fsync fault, actual corrupt/page-count/protection output rejection. |
| Unlock unencrypted readability; lock empty-password rejection/supplied-password readability; same page count | both validators | Pass: real substituted invalid outputs, wrong/empty encrypted-output passwords, installed round trips. |
| Read-only source; all handles closed before publication; source identity/size/mtime guard; ordinary permissions | `fileio.py` | Pass: tracked handle closure, concurrent content/identity/symlink substitutions, 0640 preservation and original-byte checks. |
| Atomic no-clobber new publication; existing destination/other input/racing creator safety; unsupported operation fails safely | `fileio._publish` | Pass: existing destination cases, atomic link collision injection, unsupported filesystem operation injection. |
| Directory synchronization where supported; post-publication durability failure is explicit | `fileio._sync_directory` | Pass: injected synchronization failure for both actions/modes reports published readable output. |
| Partial failures continue, no batch rollback, Ctrl+C 130, cleanup, completed files remain | file I/O and CLI | Pass: mixed batches, partial-completion interrupt summary, interrupted write/validation, real terminal SIGINT. Forced-kill cleanup is explicitly outside guarantee. |
| Cleanup failure must not leak exceptions or mask interruption | file I/O, `InterruptedWithCleanup` | Pass: denied unlink before/after publication and interrupted write; fixed error/private leftover name or preserved interruption. |
| Supported pages/text/images/metadata/bookmarks/links/annotations/attachments/forms retained | document cloning | Pass: rich generated fixture compares decoded content and document structures through all four lock/unlock mode round trips. |
| RC4/AES variants; user/owner, correct/wrong/empty/Unicode passwords and paths | PDF modules | Pass: RC4-40/128, AES-128/256-R5/256 generated fixtures, whitespace/Unicode and user/owner passwords. |
| Invalid/unreadable input, unwritable destinations, write/validation/publication failures preserve originals | file I/O | Pass: corrupt inputs, real permission failures, partial writes, validation faults, actual os.replace failure and publication faults for both actions/modes. |
| Plain one-line results, stdout success/skip, stderr failure, summary, codes 0/1/2/130 | `cli.py`, structured results | Pass: discovery failures counted, partial interrupted summary, controls/Unicode separators escaped, installed exit status checks. |
| Fixed managed root/envs/command layout and ownership marker; no sudo; automatic PATH per user amendment | scripts, `shell_setup.py`, README | Pass: isolated HOME with spaces/Unicode, root/marker layout, external PDFs preserved. Shell edits are explicitly authorized, announced and restricted to one guarded PATH block. |
| Current and future Bash/Zsh terminals require no manual PATH configuration | sourceable installer, packaged shell helper | Pass: real Bash/Zsh source/eval and interactive/login tests, unchanged caller options/traps/cwd, exact PATH-component matching, repeated installs, Bash login precedence and exported/unexported ZDOTDIR. Standalone child processes configure future terminals; current-terminal activation uses source/eval. |
| Preserve shell settings; refuse unsafe files; recover append failures without discarding concurrent changes | `shell_setup.py` | Pass: original bytes/inode permissions retained, newline handling, prevalidation of all targets, symlink/hardlink/FIFO/readonly refusal, partial/edited marker refusal, write/fsync/interrupt rollback and concurrent-edit preservation. |
| Fresh permanent env, checks before atomic command switch, retained old envs, failed upgrade keeps working installation | `install.sh` | Pass: real wheel install/update, retained environment, invalid wheel/Git ref/transport, venv/pip/check/version failures, publication collision and interruption. |
| Prerequisites, invalid repo/ref, transport failure, unrelated command/ownership safety | installation scripts | Pass: missing Python/Git/venv/pip, bad repo/ref, locally redirected real Git failures, unrelated file/link/dangling command, symlink parents/root/envs, unsafe markers. Curl is a prerequisite of the documented download commands. |
| Manual installation same layout, repeat refusal, checkout independence | exact README manual block | Pass: real venv/pip in isolated HOME, copied checkout deleted, installed console/module still work. |
| Uninstall normal/retained/incomplete/dangling/repeated; validate both targets before deleting; preserve external files | `uninstall.sh` | Pass: installer suite, multiple real envs, incomplete roots, dangling link, repeat removal, unrelated commands/unmarked or symlinked roots refused. |
| Discover real GitHub remote or preserve explicit placeholder | installer + README + project URLs | Pass: configured origin is rtreertree/pyunlock. Installer defaults, README download/clone URLs and package metadata use the actual repository. Default Git installation tested against GitHub main in an isolated HOME. Design reference templates and the explicit-placeholder rejection test remain unchanged. |
| README prerequisites/examples/exact paths/automated/manual install/update/uninstall and limitations | `README.md` | Reviewed against implementation; exact manual block tested, including immediate activation. DESIGN.md now records the user's automatic-PATH amendment. |
| Shell syntax, sdist/wheel build, noneditable installed application | build and entire test suite | Pass on macOS: isolated build creates sdist, then wheel from sdist; fresh install, pip check, installed package tested without src path overrides. |
| macOS and Linux validation before publication | platform checks + `.github/workflows/tests.yml` | Current changes verified locally on macOS arm64. Baseline commit 46c6b43 passed all six macOS/Ubuntu Python 3.11/3.12/3.13 jobs; check hosted results for the automatic-PATH commit separately. WSL itself remains untested. |

## Recorded verification

Verified on 2026-11-07 (Asia/Bangkok), macOS arm64, Python 3.12.3,
pypdf 7.0.0, cryptography 50.0.2 and pytest 9.2.0. The full suite passes
**268 tests with no skips**, including real installer integration, shell PATH
setup/activation tests and four installed-command pseudo-terminal cases.
Bash/Zsh installer syntax and `pip check` pass.

Build/test environments and downloaded wheels were confined to `/private/tmp`;
PDFs and fake homes were generated in temporary directories. The fresh packaged
test interpreter was `/private/tmp/pyunlock-path-env/bin/python`, importing
pyunlock from its `site-packages`, without editable installation or `PYTHONPATH`.
Real installer tests used the built wheel and an offline dependency wheelhouse.
Git failure tests redirected requests to local generated repositories; no
invented remote was contacted.

The full run used:

```bash
PYUNLOCK_TEST_WHEEL="$PWD/dist/pyunlock-0.1.0-py3-none-any.whl" \
PYUNLOCK_TEST_WHEELHOUSE=/private/tmp/pyunlock-wheelhouse \
/private/tmp/pyunlock-path-env/bin/python -m pytest -q
```

The previous committed version passed all six hosted jobs on macOS/Ubuntu and
Python 3.11/3.12/3.13: [baseline CI run](https://github.com/rtreertree/pyunlock/actions/runs/42374474279).
Hosted results for the automatic-PATH commit must be checked independently before
claiming that version's coverage beyond the local macOS run. WSL remains an
external platform check. The workflow's embedded shell syntax has been checked.
Representative synthetic fixture success does not establish preservation of
every possible PDF feature. Digital signatures, extended attributes, ACLs,
original timestamps, secure erasure, concurrent-editor locking and forced-kill
cleanup retain the design's stated limits. Filesystems without atomic hard-link
publication fail safely in new mode.

No personal documents were used and no installation was made into the real
home. Only temporary test-home startup files were edited; real startup files
were untouched. No release was published or administrator operations performed.

## Automatic PATH amendment

The user explicitly requested automatic PATH setup, superseding the original
manual-export/no-startup-edits design. The installer now invokes the packaged
`pyunlock.shell_setup` helper before switching the command, announces updates,
and appends a uniquely marked conditional block to the selected shell's files.
Repeated setup adds neither duplicate blocks nor duplicate PATH components.
Existing settings and permissions remain intact. Failed writes roll back only
the helper's own appends, never another editor's changes. Startup-file refusal
or configuration failure preserves the working installation.

The recommended source/eval invocation also changes PATH in the caller after
successful installation. It preserves caller options, traps, cwd and unexported
ZDOTDIR. Direct script execution cannot mutate its parent's environment and
therefore activates the command in future terminals. Manual installation calls
the same helper and activates PATH in its outer shell block. Removal deliberately
retains the guarded shared local-bin PATH entry for other applications.

## GitHub continuation

After the user supplied the repository, its public visibility and `main` default
branch were confirmed through the connected GitHub tools and matched the local
`origin`. A separate smoke test ran the corrected local installer with no
repository or local-source override, installing directly from GitHub commit
`74c969fc557c71b005911cbfad3e01ceb8441cdb` in a temporary HOME with spaces and
Unicode. Python dependencies came from the temporary offline wheelhouse.
The installed console/module worked, a generated rich PDF survived a lock/unlock
round trip, empty/wrong passwords were rejected, and uninstall/repeat removal
passed. The temporary installation was removed afterward. This verifies the
GitHub package source; publishing this change updates the raw installer's
default repository for new users.

Continuation changes: `install.sh`, `README.md`, `REQUIREMENTS.md`,
`pyproject.toml`, `MANIFEST.in`, `tests/test_installation.py`, and the new
`.github/workflows/tests.yml`. No application PDF behavior changed.

## Changed files

The original implementation added the files below. A later user amendment updates
DESIGN.md's PATH requirements and adds the shell helper and its tests.

- Packaging: `pyproject.toml`, `MANIFEST.in`, `.gitignore`.
- Application: `src/pyunlock/__init__.py`, `__main__.py`, `cli.py`,
  `discovery.py`, `models.py`, `fileio.py`, `locker.py`, `unlocker.py`, `shell_setup.py`.
- Installation/removal: executable `install.sh`, `uninstall.sh`.
- Verification: `tests/conftest.py`, `test_cli.py`, `test_discovery.py`,
  `test_fileio.py`, `test_installation.py`, `test_locker.py`, `test_terminal.py`,
  `test_unlocker.py`, `test_shell_setup.py`, plus `tests/fixtures/__init__.py`, `factory.py`, `README.md`.
- Documentation: `README.md`, `REQUIREMENTS.md`.
- Continuous verification: `.github/workflows/tests.yml` (added after the repository was supplied).
- Built deliverables: `dist/pyunlock-0.1.0-py3-none-any.whl` and
  `dist/pyunlock-0.1.0.tar.gz` (build outputs are ignored by Git).
