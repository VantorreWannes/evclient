import asyncio
import logging
from collections.abc import Callable  # noqa: TC003
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003

import aiohttp

from evclient.stores import ObjectStores, object_stores
from evclient.types import (
    Archive,
    Digest,
    EvError,
    ManifestObject,
    ReferenceObject,
    SnapshotObject,
    UserId,
    WorkspaceObject,
    decode,
    encode,
    hash_bytes,
    hash_object,
    normalize_url,
)
from evclient.workspace import (
    read_archives,
    read_workspace,
    scan_files,
    write_archives,
    write_file,
    write_workspace,
)

LOGGER = logging.getLogger("evclient.operations")


def _active_archives(workspace_path: Path) -> list[Archive]:
    archives = read_archives(workspace_path)
    if not archives:
        msg = "no active archive: login first"
        raise EvError(msg)
    return archives


async def _post_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.post(url) as response:
        response.raise_for_status()
        return (await response.text()).strip()


async def register_command(archive_url: str, user_id: UserId | None = None) -> UserId:
    """Claim a user ID; the archive chooses it when omitted."""
    base = normalize_url(archive_url)
    async with aiohttp.ClientSession() as session:
        if user_id is None:
            claimed = await _post_text(session, f"{base}/user/register")
            LOGGER.info("registered archive-chosen user %s on %s", claimed, base)
            return claimed
        async with session.post(f"{base}/user/register/{user_id}") as response:
            response.raise_for_status()
            LOGGER.info("registered user %s on %s", user_id, base)
            return user_id


async def unregister_command(archive_url: str, user_id: UserId) -> None:
    """Forget the user and everything it stored on the archive."""
    url = f"{normalize_url(archive_url)}/user/{user_id}"
    async with aiohttp.ClientSession() as session, session.delete(url) as response:
        response.raise_for_status()
    LOGGER.info("unregistered user %s on %s", user_id, normalize_url(archive_url))


def login_command(workspace_path: Path, archive_url: str, user_id: UserId) -> Archive:
    """Add the archive + user to the workspace's active archives."""
    archive = Archive(url=archive_url, user_id=user_id)
    archives = read_archives(workspace_path)
    if archive not in archives:
        archives.append(archive)
        write_archives(workspace_path, archives)
        LOGGER.info("logged in %s %s in %s", archive_url, user_id, workspace_path)
    else:
        LOGGER.debug(
            "already active: %s %s in %s", archive_url, user_id, workspace_path
        )
    return archive


def logout_command(workspace_path: Path, archive_url: str, user_id: UserId) -> bool:
    """Remove the archive + user from the workspace's active archives."""
    archive = Archive(url=archive_url, user_id=user_id)
    archives = read_archives(workspace_path)
    if archive not in archives:
        LOGGER.debug("not active: %s %s in %s", archive_url, user_id, workspace_path)
        return False
    archives.remove(archive)
    write_archives(workspace_path, archives)
    LOGGER.info("logged out %s %s in %s", archive_url, user_id, workspace_path)
    return True


@dataclass(frozen=True, slots=True)
class VersionListing:
    number: int
    identifier: Digest
    note: str | None


async def _read_snapshots(
    stores: ObjectStores, workspace: WorkspaceObject
) -> list[SnapshotObject]:
    return [
        decode(SnapshotObject, await stores.snapshot.get(snapshot_hash))
        for snapshot_hash in workspace.snapshots
    ]


def _select_positions(count: int, version: int | None, mode: str) -> list[int]:
    """Map an optional 1-based version number onto array positions."""
    if count == 0:
        msg = "workspace has no versions"
        raise EvError(msg)
    if version is None:
        return list(range(count))
    if not 1 <= version <= count:
        msg = f"version {version} out of range (1..{count})"
        raise EvError(msg)
    position = version - 1
    if mode == "single":
        return [position]
    return list(range(position, count))


async def _store_files(
    stores: ObjectStores, files: list[tuple[str, bytes]]
) -> ManifestObject:
    async def store_file(path: str, data: bytes) -> Digest:
        reference = ReferenceObject(path=path, content=hash_bytes(data))
        await stores.content.set(reference.content, data)
        await stores.reference.set(hash_object(reference), encode(reference))
        return hash_object(reference)

    references = [await store_file(path, data) for path, data in files]
    LOGGER.debug("stored %d file(s) as %d reference(s)", len(files), len(references))
    return ManifestObject(references=tuple(references))


async def save_command(
    workspace_path: Path, note: str | None = None
) -> tuple[Archive, int, Digest]:
    """Save the workspace's current state as a new version on the first archive."""
    archive = _active_archives(workspace_path)[0]
    files = scan_files(workspace_path)
    async with aiohttp.ClientSession() as session:
        stores = object_stores(session, archive)
        manifest = await _store_files(stores, files)
        manifest_hash = hash_object(manifest)
        await stores.manifest.set(manifest_hash, encode(manifest))
        snapshot = SnapshotObject(manifest=manifest_hash, note=note)
        snapshot_hash = hash_object(snapshot)
        await stores.snapshot.set(snapshot_hash, encode(snapshot))
        workspace = WorkspaceObject(
            snapshots=(*read_workspace(workspace_path).snapshots, snapshot_hash)
        )
        await stores.workspace.set(hash_object(workspace), encode(workspace))
        write_workspace(workspace_path, workspace)
    LOGGER.info(
        "saved version %d to %s (%d file(s))",
        len(workspace.snapshots),
        archive.url,
        len(files),
    )
    return archive, len(workspace.snapshots), snapshot_hash


async def list_command(
    workspace_path: Path, version: int | None = None
) -> tuple[Archive, list[VersionListing]]:
    """List the workspace's versions, or only the requested one."""
    archive = _active_archives(workspace_path)[0]
    workspace = read_workspace(workspace_path)
    positions = _select_positions(len(workspace.snapshots), version, "single")
    async with aiohttp.ClientSession() as session:
        snapshots = await _read_snapshots(object_stores(session, archive), workspace)
    return archive, [
        VersionListing(
            number=position + 1,
            identifier=workspace.snapshots[position],
            note=snapshots[position].note,
        )
        for position in positions
    ]


async def _restore_snapshot(
    stores: ObjectStores, snapshot_hash: Digest
) -> list[tuple[str, bytes]]:
    snapshot = decode(SnapshotObject, await stores.snapshot.get(snapshot_hash))
    manifest = decode(ManifestObject, await stores.manifest.get(snapshot.manifest))
    references = [
        decode(ReferenceObject, await stores.reference.get(reference_hash))
        for reference_hash in manifest.references
    ]
    contents = await asyncio.gather(
        *(stores.content.get(reference.content) for reference in references)
    )
    return [
        (reference.path, data)
        for reference, data in zip(references, contents, strict=True)
    ]


async def clone_command(
    source_path: Path, target_path: Path, version: int | None = None
) -> tuple[Archive, int, int]:
    """Clone the source workspace to the target path, which may not exist yet."""
    if target_path.exists():  # noqa: ASYNC240
        msg = f"target already exists: {target_path}"
        raise EvError(msg)
    archive = _active_archives(source_path)[0]
    workspace = read_workspace(source_path)
    if not workspace.snapshots:
        msg = "source workspace has nothing to clone"
        raise EvError(msg)
    positions = _select_positions(len(workspace.snapshots), version, "suffix")
    async with aiohttp.ClientSession() as session:
        stores = object_stores(session, archive)
        for position in positions:
            for relative_path, data in await _restore_snapshot(
                stores, workspace.snapshots[position]
            ):
                write_file(target_path, relative_path, data)
    login_command(target_path, archive.url, archive.user_id)
    write_workspace(target_path, WorkspaceObject(snapshots=workspace.snapshots))
    LOGGER.info(
        "cloned version(s) %d..%d from %s to %s",
        positions[0] + 1,
        positions[-1] + 1,
        source_path,
        target_path,
    )
    return archive, positions[0] + 1, positions[-1] + 1


async def _delete_snapshot(stores: ObjectStores, snapshot_payload: bytes) -> None:
    snapshot = decode(SnapshotObject, snapshot_payload)
    manifest_hash = snapshot.manifest
    manifest = decode(ManifestObject, await stores.manifest.get(manifest_hash))
    for reference_hash in manifest.references:
        reference = decode(ReferenceObject, await stores.reference.get(reference_hash))
        await stores.content.delete(reference.content)
        await stores.reference.delete(reference_hash)
    await stores.manifest.delete(manifest_hash)


async def _forget_by_version(
    session: aiohttp.ClientSession,
    archives: list[Archive],
    workspace: WorkspaceObject,
    version: int,
    on_forget: Callable[[Archive, int | None], None],
) -> WorkspaceObject:
    position = _select_positions(len(workspace.snapshots), version, "single")[0]
    snapshot_hash = workspace.snapshots[position]
    trimmed = WorkspaceObject(
        snapshots=workspace.snapshots[:position] + workspace.snapshots[position + 1 :]
    )
    trimmed_hash = hash_object(trimmed)
    for archive in archives:
        stores = object_stores(session, archive)
        payload = await stores.snapshot.get(snapshot_hash)
        await _delete_snapshot(stores, payload)
        await stores.snapshot.delete(snapshot_hash)
        await stores.workspace.set(trimmed_hash, encode(trimmed))
        on_forget(archive, position + 1)
    LOGGER.info("forgot version %d on %d archive(s)", version, len(archives))
    return trimmed


async def _forget_all(
    session: aiohttp.ClientSession,
    archives: list[Archive],
    workspace: WorkspaceObject,
    on_forget: Callable[[Archive, int | None], None],
) -> WorkspaceObject:
    empty = WorkspaceObject()
    empty_hash = hash_object(empty)
    for archive in archives:
        stores = object_stores(session, archive)
        for snapshot_hash in workspace.snapshots:
            payload = await stores.snapshot.get(snapshot_hash)
            await _delete_snapshot(stores, payload)
            await stores.snapshot.delete(snapshot_hash)
        await stores.workspace.set(empty_hash, encode(empty))
        on_forget(archive, None)
    LOGGER.info("forgot all versions on %d archive(s)", len(archives))
    return empty


async def forget_command(
    workspace_path: Path,
    version: int | None,
    forget_all: bool,  # noqa: FBT001
    on_forget: Callable[[Archive, int | None], None],
) -> None:
    """Forget the selected version, or all versions, on every active archive."""
    archives = _active_archives(workspace_path)
    workspace = read_workspace(workspace_path)
    if not workspace.snapshots:
        msg = "workspace has no versions"
        raise EvError(msg)
    async with aiohttp.ClientSession() as session:
        if forget_all:
            result = await _forget_all(session, archives, workspace, on_forget)
        elif version is not None:
            result = await _forget_by_version(
                session, archives, workspace, version, on_forget
            )
        else:
            msg_0 = "choose --version or --all"
            raise EvError(msg_0)
    write_workspace(workspace_path, result)
