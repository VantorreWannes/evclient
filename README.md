# EasyVersion

### Goals

- **Many Archives:** Store in many archives at once.
- **Emergent Complexity:** Small implementation surface with reasonable usage requirements.

## Output contract

- **stdout is for pipelines.** A command prints only what a caller wants to consume: `register` prints the claimed user ID, `list` prints one `N: hash -- note` line per version. Nothing else goes to stdout.
- **stderr is for humans.** Progress, confirmations, and diagnostics go through logging: default shows WARNING and above, `-v` adds INFO, `-vv` adds DEBUG. The flag is global and is normalized once, in `main`.
- **Expected failures raise `EvError`** and render as one `ERROR: <message>` line, exit code 1, no traceback. Truly unexpected exceptions propagate with their traceback - a bug should be visible.
- **Commands never print or log.** A command _returns its outcome_; the dispatcher alone decides whether that outcome is pipe-worthy (stdout) or log-worthy (INFO). That decision lives in exactly one place, so growing the CLI never re-opens the question.

## Commands

Positional `<path>` is a workspace path, or an archive URL for `archive` commands. All commands accept `--help` / `-h`.

| Command                              | stdout                        | INFO log                  |
| ------------------------------------ | ----------------------------- | ------------------------- |
| `archive <url> register [user:ID]`   | claimed user ID               | -                         |
| `archive <url> unregister <user:ID>` | -                             | unregistered user         |
| `<path> login <url> <user:ID>`       | -                             | logged in archive + user  |
| `<path> logout <url> <user:ID>`      | -                             | logged out archive + user |
| `<path> save [-n note]`              | -                             | saved version number      |
| `<path> list [-V n]`                 | `N: hash -- note` per version | -                         |
| `<source> clone <target> [-V n]`     | -                             | cloned version span       |
| `<path> forget {-V n \| -a}`         | -                             | forgot per active archive |

- `--version` short flag is `-V`; the top-level `-v` is verbosity (repeatable, must precede the command - argparse treats flags after the command as the command's own).
- Exit codes: `0` success, `1` expected failure, `2` usage error.

## Archive

An archive is accessed only programmatically, through its URL.

### Accounts

- **`POST /user/register`:** Claim an archive-chosen user ID. Returns it.
- **`POST /user/register/<user:ID>`:** Claim the given user ID.
- **`DELETE /user/<user:ID>`:** Forget the user and everything it stored.
- **`GET /user/<user:ID>`:** Returns an object containing the user's workspace hashes.

### Objects

Five object types, forming one chain from workspace to content:

| Type        | Contents                                |
| ----------- | --------------------------------------- |
| `workspace` | An array of snapshot hashes             |
| `snapshot`  | A manifest hash and an optional note    |
| `manifest`  | An array of reference hashes            |
| `reference` | A relative file path and a content hash |
| `content`   | Raw bytes                               |

Every object supports the same endpoints under `/user/<user:ID>/<type>/<hash>`:

- **`HEAD`:** Check whether the archive already has the object.
- **`GET`:** Return the object.
- **`PUT`:** Store the object at the given hash.
- **`DELETE`:** Forget the object at the given hash.

### Invariants

- Every object is identified by a blake3 hash of its contents; only users have IDs.

## Client

### Invariants

- All configuration lives in the `.ev` folder at the workspace root.
- `login` appends one `<archive:URL> <user:ID>` line to `.ev/archives`; `logout` removes it.
- A version's number is its position in the workspace's snapshot array. Ordering belongs to the workspace container; no type stores an index.
- User IDs are used exactly as provided by the archive; no client-side mapping.
- Malformed archive payloads are wrapped into `EvError` at the `decode` boundary.
- On internal error the client aborts immediately rather than continue in a partially synced state.

### Extending the client

Adding a command takes three steps, and none of them touch output handling:

1. Register its parser in `build_parser` - flags are labels only.
2. Implement `<name>_command(...)` so it _returns_ its outcome.
3. Add one entry to the dispatcher table mapping the command name to the function.

The dispatcher owns global flags, the output contract, and error rendering; a new command inherits all three without new code. That is the entire pattern - keep it true and the CLI stays DRY at any size.
