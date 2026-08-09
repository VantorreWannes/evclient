# EasyVersion

### Goals

- **Many Archives:** Can store in many archives at once.
- **Emergent Complexity:** Small implementation surface but reasonable usage requirements.

## Commands

- **`ev [COMMANDS | OPTIONS | ARGUMENTS | FLAGS]... [--help | -h]`:** List all sub commands + a small description of the intended usage.
- **`ev archive <archive:URL> register [user:ID]`:** Request to claim a new user ID on the given archive URL.
- **`ev archive <archive:URL> unregister <user:ID>`:** Request to be forgotten with the passed user ID on the given archive URL.
- **`ev <workspace:PATH> login <api:URL> <user:ID>`:** Add this api URL + user ID to the list of active archives for the specified workspace.
- **`ev <workspace:PATH> logout <api:URL> <user:ID>`:** Remove this api URL + user ID from the list of active archives for the specified workspace.
- **`ev <workspace:PATH> save [--note <comment:TEXT> | -n <comment:TEXT>]`:** Save the current state of this workspace as a new version. With the specified comment if provided.
- **`ev <workspace:PATH> list [--version <version:NUMBER> | -v <version:NUMBER>]`:** List every version of the passed workspace so far or just the specific one requested. With their respective notes if set.
- **`ev <source:PATH> clone <target:PATH> [--version <version:NUMBER> | -v <version:NUMBER>]`:** Clone the source workspace to the target workspace. Target may not exist yet. Clone the workspace as it was on the specified version if passed.
- **`ev <source:PATH> forget {--version <version:NUMBER> | -v <version:NUMBER> | --all | -a}`:** Request the active workspaces to forget the selected version. Or all if requested. Does not clear the current workspace state.

## Archive

- **URL Specified:** Each archive only be accessed programatically by users through its URL.

### Endpoints

#### Accounts

##### `POST /user/register`

- Claims an available user.
- If successful returns the claimed user.

##### `POST /user/register:id`

- Attempts to claim the specfied user.

##### `DELETE /user/:user_id/`

- Attempts to forget the provided user.

##### `GET /user/:user_id/`

- Returns an object containing:
  - An array of all workspace IDs for the given user.

#### Workspace

##### `GET /user/:user_id/workspace/:workspace_id`

- Returns a workspace object containing:
  - An array of all snapshot IDs for the given user's workspace.

##### `PUT /user/:user_id/workspace/:workspace_id`

- Replace the user's specified workspace with the new workspace object containing:
  - An array of all snapshot IDs for the given user's workspace.

##### `DELETE /user/:user_id/workspace/:workspace_id`

- Forget the user's specified workspace.

#### Snapshot

##### `GET /user/:user_id/snapshot/:snapshot_id`

- Returns an object containing:
  - An array of all manifest IDs for the given user's snapshot.
  - An optional note string for the given user's snapshot.

##### `PUT /user/:user_id/snapshot/:snapshot_id`

- Create the user's specified snapshot from the provided snapshot object containing:
  - A manifest IDs for the given user's snapshot.
  - An optional note string for the given user's snapshot.

##### `DELETE /user/:user_id/snapshot/:snapshot_id`

- Forget the user's specified snapshot.

#### Manifest

##### `GET /user/:user_id/manifest/:manifest_id`

- Returns an object containing:
  - An array of all reference IDs for the given user's manifest.

##### `PUT /user/:user_id/manifest/:manifest_id`

- Create the user's specified manifest from the provided manifest object containing:
  - An array of all reference IDs for the given user's manifest.

##### `DELETE /user/:user_id/manifest/:manifest_id`

- Forget the user's specified manifest.

#### Reference

##### `GET /user/:user_id/reference/:reference_id`

- Returns an object containing:
  - The reference's relative file path.
  - The reference's content digest.

##### `PUT /user/:user_id/reference/:reference_id`

- Create the user's specified reference from the provided reference object containing:
  - The reference's relative file path.
  - The reference's content digest.

##### `DELETE /user/:user_id/reference/:reference_id`

- Forget the user's specified reference.

#### Content

##### `GET /user/:user_id/content/:content_id`

- Returns a byte stream containing:
  - The encoded content data.

##### `PUT /user/:user_id/content/:content_id`

- Create the user's specified reference from the provided content byte stream containing:
  - The encoded content data.

##### `DELETE /user/:user_id/content/:content_id`

- Forget the user's specified reference.

### Invariants

- All non user IDs are blake3 hashes.

## Client

### Invariants

- All config information is stored in the `.ev` folder at the workspace root.
- The workspace login command appends the provided archive configuration to the currently active archive configurations in `.ev/archives`.
- If an internal error happens the program should never continue.
- User IDs are provided and used as is by the archive. No extra mapping.
