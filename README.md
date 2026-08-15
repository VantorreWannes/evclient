# EasyVersion

### Goals

- **Many Archives:** Store in many archives at once.
- **Emergent Complexity:** Small implementation surface with reasonable usage requirements.

## Commands

All commands accept `--help` / `-h`.

- **`ev archive <archive:URL> register [user:ID]`:** Claim a user ID on the archive. Archive-chosen when omitted.
- **`ev archive <archive:URL> unregister <user:ID>`:** Forget the user and everything it stored on the archive.
- **`ev <workspace:PATH> login <archive:URL> <user:ID>`:** Add the archive + user to the workspace's active archives.
- **`ev <workspace:PATH> logout <archive:URL> <user:ID>`:** Remove the archive + user from the workspace's active archives.
- **`ev <workspace:PATH> save [--note <note:TEXT> | -n <note:TEXT>]`:** Save the workspace's current state as a new version, with the note when provided.
- **`ev <workspace:PATH> list [--version <version:NUMBER> | -v <version:NUMBER>]`:** List the workspace's versions, or only the requested one, with notes where set.
- **`ev <source:PATH> clone <target:PATH> [--version <version:NUMBER> | -v <version:NUMBER>]`:** Clone the source workspace to the target path, which may not exist yet. Clone the given version when passed, the latest otherwise.
- **`ev <workspace:PATH> forget {--version <version:NUMBER> | -v <version:NUMBER> | --all | -a}`:** Forget the selected version, or all versions, on every active archive. Local files stay untouched.

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
- On internal error the client aborts immediately rather than continue in a partially synced state.
