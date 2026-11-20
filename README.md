# EasyVersion

CLI client for EasyVersion content-hashed workspace archives.

## Output contract

- **stdout is for pipelines.** A command prints only what a caller wants to consume: `register` prints the claimed user ID, `list` prints one `N: hash -- note` line per version. Nothing else goes to stdout.
- **stderr is for humans.** Progress, confirmations, and diagnostics go through logging: default shows WARNING and above, `-v` adds INFO, `-vv` adds DEBUG. The flag is global and is normalized once, in `main`.
- **Expected failures raise `EvError`** and render as one `ERROR: <message>` line, exit code 1, no traceback. Unexpected exceptions propagate with their traceback.
- **Commands never print or log.** A command returns its outcome; the dispatcher decides whether that outcome goes to stdout or INFO.

## Commands

All commands accept `--help` / `-h`.

| Command                                        | stdout                        | INFO log                  |
| ---------------------------------------------- | ----------------------------- | ------------------------- |
| `archive <url> register [user:ID]`             | claimed user ID               | -                         |
| `archive <url> unregister <user:ID>`           | -                             | unregistered user         |
| `workspace <path> login <url> <user:ID>`       | -                             | logged in archive + user  |
| `workspace <path> logout <url> <user:ID>`      | -                             | logged out archive + user |
| `workspace <path> save [-n note]`              | -                             | saved version number      |
| `workspace <path> list [-V n]`                 | `N: hash -- note` per version | -                         |
| `workspace <source> clone <target> [-V n]`     | -                             | cloned version span       |
| `workspace <path> forget {-V n \| -a}`         | -                             | forgot per active archive |

- `--version` short flag is `-V`; the top-level `-v` is verbosity (repeatable, must precede `archive` or `workspace`).
- Exit codes: `0` success, `1` expected failure, `2` usage error.

## Archive

An archive is an `evserver` instance accessed over HTTP using `dill`-serialized `evserver.types` objects (`user`, `workspace`, `snapshot`, `manifest`, `reference`, `content`).

Each resource type exposes `HEAD`, `GET`, `PUT`, and `DELETE` at `/{type}/{id}`:

- `content`, `reference`, `manifest`, and `snapshot` use `sha3_512` IDs computed by `evserver.types` and are treated as immutable (`HEAD` before `PUT`).
- `user` and `workspace` use client-generated IDs and overwrite on `PUT`.

## Client

### Invariants

- All local state lives in `.ev` at the workspace root (`.ev/archives` and `.ev/workspace.json`).
- `login` appends one `<archive:URL> <user:ID>` line to `.ev/archives`; `logout` removes it.
- Version numbers are 1-based positions in `.ev/workspace.json`; `evserver` stores an unordered `snapshot_ids` set on `Workspace`.
- Malformed archive payloads and local state are wrapped into `EvError` at the `decode` and `decode_json` boundaries.
- On internal error the client aborts rather than continue in a partially synced state.

### Extending the client

1. Register the subcommand parser in `build_parser`.
2. Implement `<name>_command(...)` in `operations.py` so it returns its outcome.
3. Add an entry to `_COMMANDS` mapping `<group>/<action>` to the handler.
