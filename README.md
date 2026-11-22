# EasyVersion

CLI and GUI client for EasyVersion content-hashed workspace archives.

## Output contract

- **stdout is for pipelines.** `register` prints the claimed user ID, `list` prints one `N: hash -- note` line per version, and `workspaces` prints one workspace ID per line. Nothing else goes to stdout.
- **stderr is for humans.** Warnings, confirmations, and diagnostics go through logging: default shows WARNING and above, `-V` adds INFO, `-VV` adds DEBUG. The flag is global and is normalized once, in `main`.
- **Expected failures raise `EvError`** and render as one `ERROR: <message>` line, exit code 1, no traceback. Unexpected exceptions propagate with their traceback.
- **Commands never print or log to stdout.** A command returns its outcome; the CLI or GUI decides how to present it.

## Commands

All commands accept `--help` / `-h`.

| Command                                                        | stdout                        | INFO log                  |
| -------------------------------------------------------------- | ----------------------------- | ------------------------- |
| `archive <url> register [user:ID]`                             | claimed user ID               | -                         |
| `archive <url> unregister <user:ID>`                           | -                             | unregistered user         |
| `archive <url> workspaces <user:ID>`                           | workspace ID per line         | -                         |
| `archive <url> clone <user:ID> <workspace:ID> <target> [-v n]` | -                             | cloned version span       |
| `workspace <path> login <url> <user:ID>`                       | -                             | logged in archive + user  |
| `workspace <path> logout <url> <user:ID>`                      | -                             | logged out archive + user |
| `workspace <path> save [-n note]`                              | -                             | saved version number      |
| `workspace <path> list [-v n]`                                 | `N: hash -- note` per version | -                         |
| `workspace <source> clone <target> [-v n]`                     | -                             | cloned version span       |
| `workspace <path> forget {-v n \| -a}`                         | -                             | forgot per logged-in archive |

- `--version` short flag is `-v`; the top-level `-V` is verbosity (repeatable, must precede `archive` or `workspace`).
- Exit codes: `0` success, `1` expected failure, `2` usage error.

## Archive

An archive is an `evserver` instance accessed over HTTP using JSON payloads (`user`, `workspace`, `snapshot`, `manifest`, `reference`, `content`).

Each resource type exposes `HEAD`, `GET`, `PUT`, and `DELETE` at `/{type}/{id}`:

- `content`, `reference`, `manifest`, and `snapshot` use `sha3_512` IDs. `content.data` is base64-encoded in JSON.
- `user` tracks `workspace_ids` so a client without `.ev` state can discover saved workspaces.
- `workspace` stores an ordered `snapshot_ids` list so version numbers and chronological order are preserved remotely.

## Client

### Invariants

- All local workspace state lives in `.ev` at the workspace root (`.ev/accounts.json` and `.ev/workspace.json`).
- `EvError` wraps transport, HTTP, and `.ev` JSON parse errors at the command boundary.
- GUI preferences (workspace list and saved accounts) live in `~/.ev/gui_workspaces.json` and `~/.ev/gui_accounts.json`.
- Entry points: `ev` (`evclient.cli:main`) for CLI, `easyversion` (`evclient.gui:main`) for GUI.
