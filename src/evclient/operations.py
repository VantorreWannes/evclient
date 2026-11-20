import asyncio
import logging
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

import aiohttp
from aiohttp import ClientResponseError
from evserver.types import (
    Content,
    Manifest,
    Reference,
    ReferenceId,
    Snapshot,
    SnapshotId,
    User,
    UserId,
    Workspace,
)

from evclient.stores import ObjectStores, object_stores, user_store
from evclient.types import (
    Archive,
    EvError,
    LocalWorkspace,
    new_workspace_identifier,
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

_REMOTE_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, ValueError)


def format_error(error: Exception) -> str:
    if isinstance(error, aiohttp.ClientConnectorError):
        detail = error.strerror or "connection failed"
        return f"cannot connect to {error.host}:{error.port} ({detail})"
    if isinstance(error, ClientResponseError):
        return f"HTTP {error.status} ({error.message})"
    if isinstance(error, TimeoutError):
        return "timed out"
    return str(error) or type(error).__name__


async def _try_archives[T](
    archives: list[Archive],
    action: Callable[[Archive], Awaitable[T]],
) -> tuple[Archive, T]:
    last_error: Exception | None = None
    for archive in archives:
        try:
            return archive, await action(archive)
        except _REMOTE_ERRORS as error:
            LOGGER.warning("%s: %s", archive.url, format_error(error))
            last_error = error
    if last_error is None:
        message = "no active archive: login first"
        raise EvError(message)
    raise last_error


def _active_archives(workspace_path: Path) -> list[Archive]:
    archives = read_archives(workspace_path)
    if not archives:
        message = "no active archive: login first"
        raise EvError(message)
    return archives


async def register_command(archive_url: str, user_id: UserId | None = None) -> UserId:
    base = normalize_url(archive_url)
    resolved_id = user_id if user_id is not None else uuid4().hex
    async with aiohttp.ClientSession() as session:
        store = user_store(session, base)
        if user_id is not None and await store.has(resolved_id):
            message = f"user already exists: {resolved_id}"
            raise EvError(message)
        await store.set(resolved_id, User(id=resolved_id))
    LOGGER.info("registered user %s on %s", resolved_id, base)
    return resolved_id


async def unregister_command(archive_url: str, user_id: UserId) -> None:
    base = normalize_url(archive_url)
    async with aiohttp.ClientSession() as session:
        await user_store(session, base).delete(user_id)
    LOGGER.info("unregistered user %s on %s", user_id, base)


def login_command(workspace_path: Path, archive_url: str, user_id: UserId) -> Archive:
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
    identifier: SnapshotId
    note: str | None


def _select_positions(count: int, version: int | None, mode: str) -> list[int]:
    if count == 0:
        message = "workspace has no versions"
        raise EvError(message)
    if version is None:
        return list(range(count))
    if not 1 <= version <= count:
        message = f"version {version} out of range (1..{count})"
        raise EvError(message)
    position = version - 1
    if mode == "single":
        return [position]
    return list(range(position, count))


async def _store_files(
    stores: ObjectStores, files: list[tuple[str, bytes]]
) -> Manifest:
    async def store_file(path: str, data: bytes) -> ReferenceId:
        content = Content(data=data)
        await stores.content.set(content.id, content)
        reference = Reference(file_path=Path(path), content_id=content.id)
        await stores.reference.set(reference.id, reference)
        return reference.id

    references = [await store_file(path, data) for path, data in files]
    LOGGER.debug("stored %d file(s) as %d reference(s)", len(files), len(references))
    return Manifest(reference_ids=set(references))


async def save_command(
    workspace_path: Path, note: str | None = None
) -> tuple[Archive, int, SnapshotId]:
    archives = _active_archives(workspace_path)
    files = scan_files(workspace_path)
    local_workspace = read_workspace(workspace_path)
    first_success: tuple[Archive, LocalWorkspace, SnapshotId] | None = None
    last_error: Exception | None = None
    async with aiohttp.ClientSession() as session:
        for archive in archives:
            try:
                stores = object_stores(session, archive)
                manifest = await _store_files(stores, files)
                await stores.manifest.set(manifest.id, manifest)
                snapshot = Snapshot(manifest_id=manifest.id, note=note)
                await stores.snapshot.set(snapshot.id, snapshot)
                updated_local = LocalWorkspace(
                    identifier=local_workspace.identifier,
                    snapshots=(*local_workspace.snapshots, snapshot.id),
                )
                remote_workspace = Workspace(
                    snapshot_ids=set(updated_local.snapshots),
                    id=updated_local.identifier,
                )
                await stores.workspace.set(remote_workspace.id, remote_workspace)
            except _REMOTE_ERRORS as error:
                LOGGER.warning("%s: %s", archive.url, format_error(error))
                last_error = error
                continue
            if first_success is None:
                first_success = (archive, updated_local, snapshot.id)
    if first_success is None:
        if last_error is None:
            message = "no active archive: login first"
            raise EvError(message)
        raise last_error
    primary_archive, updated_local, snapshot_id = first_success
    write_workspace(workspace_path, updated_local)
    LOGGER.info(
        "saved version %d to %s (%d file(s))",
        len(updated_local.snapshots),
        primary_archive.url,
        len(files),
    )
    return primary_archive, len(updated_local.snapshots), snapshot_id


async def list_command(
    workspace_path: Path, version: int | None = None
) -> tuple[Archive, list[VersionListing]]:
    archives = _active_archives(workspace_path)
    local_workspace = read_workspace(workspace_path)
    positions = _select_positions(len(local_workspace.snapshots), version, "single")
    async with aiohttp.ClientSession() as session:

        async def fetch(archive: Archive) -> list[Snapshot]:
            stores = object_stores(session, archive)
            return await asyncio.gather(
                *(
                    stores.snapshot.get(local_workspace.snapshots[position])
                    for position in positions
                )
            )

        archive, snapshots = await _try_archives(archives, fetch)
    return archive, [
        VersionListing(
            number=position + 1,
            identifier=local_workspace.snapshots[position],
            note=snapshot.note,
        )
        for position, snapshot in zip(positions, snapshots, strict=True)
    ]


async def _restore_snapshot(
    stores: ObjectStores, snapshot_identifier: SnapshotId
) -> list[tuple[str, bytes]]:
    snapshot = await stores.snapshot.get(snapshot_identifier)
    manifest = await stores.manifest.get(snapshot.manifest_id)
    references = [
        await stores.reference.get(reference_identifier)
        for reference_identifier in manifest.reference_ids
    ]
    contents = await asyncio.gather(
        *(stores.content.get(reference.content_id) for reference in references)
    )
    return [
        (reference.file_path.as_posix(), content.data)
        for reference, content in zip(references, contents, strict=True)
    ]


async def clone_command(
    source_path: Path, target_path: Path, version: int | None = None
) -> tuple[Archive, int, int]:
    if target_path.exists():  # noqa: ASYNC240
        message = f"target already exists: {target_path}"
        raise EvError(message)
    archives = _active_archives(source_path)
    local_workspace = read_workspace(source_path)
    if not local_workspace.snapshots:
        message = "source workspace has nothing to clone"
        raise EvError(message)
    if version is None:
        positions = _select_positions(len(local_workspace.snapshots), None, "suffix")
        target_position = positions[-1]
        first, last = positions[0] + 1, positions[-1] + 1
        cloned_snapshots = local_workspace.snapshots
    else:
        target_position = _select_positions(
            len(local_workspace.snapshots), version, "single"
        )[0]
        first = last = target_position + 1
        cloned_snapshots = local_workspace.snapshots[: target_position + 1]
    async with aiohttp.ClientSession() as session:

        async def restore(candidate: Archive) -> list[tuple[str, bytes]]:
            return await _restore_snapshot(
                object_stores(session, candidate),
                local_workspace.snapshots[target_position],
            )

        archive, restored = await _try_archives(archives, restore)
    for relative_path, data in restored:
        write_file(target_path, relative_path, data)
    for item in archives:
        login_command(target_path, item.url, item.user_id)
    write_workspace(
        target_path,
        LocalWorkspace(
            identifier=new_workspace_identifier(),
            snapshots=cloned_snapshots,
        ),
    )
    LOGGER.info(
        "cloned version(s) %d..%d from %s to %s",
        first,
        last,
        source_path,
        target_path,
    )
    return archive, first, last


async def _delete_snapshot(stores: ObjectStores, snapshot: Snapshot) -> None:
    manifest_identifier = snapshot.manifest_id
    try:
        manifest = await stores.manifest.get(manifest_identifier)
    except ClientResponseError as error:
        if error.status != HTTPStatus.NOT_FOUND:
            raise
        LOGGER.debug(
            "manifest %s already gone; skipping its objects", manifest_identifier
        )
        return
    for reference_identifier in manifest.reference_ids:
        try:
            reference = await stores.reference.get(reference_identifier)
        except ClientResponseError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise
            LOGGER.debug("reference %s already gone; skipping", reference_identifier)
            continue
        await stores.content.delete(reference.content_id)
        await stores.reference.delete(reference_identifier)
    await stores.manifest.delete(manifest_identifier)


def _unique(identifiers: tuple[SnapshotId, ...]) -> list[SnapshotId]:
    return list(dict.fromkeys(identifiers))


async def _delete_snapshots(
    stores: ObjectStores, snapshot_identifiers: tuple[SnapshotId, ...]
) -> None:
    for snapshot_identifier in _unique(snapshot_identifiers):
        try:
            snapshot = await stores.snapshot.get(snapshot_identifier)
        except ClientResponseError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise
            LOGGER.debug("snapshot %s already gone; skipping", snapshot_identifier)
            continue
        await _delete_snapshot(stores, snapshot)
        await stores.snapshot.delete(snapshot_identifier)


async def _forget_by_version(
    session: aiohttp.ClientSession,
    archives: list[Archive],
    local_workspace: LocalWorkspace,
    version: int,
    on_forget: Callable[[Archive, int | None], None],
) -> LocalWorkspace:
    position = _select_positions(len(local_workspace.snapshots), version, "single")[0]
    trimmed = LocalWorkspace(
        identifier=local_workspace.identifier,
        snapshots=(
            local_workspace.snapshots[:position]
            + local_workspace.snapshots[position + 1 :]
        ),
    )
    remote_workspace = Workspace(
        snapshot_ids=set(trimmed.snapshots),
        id=trimmed.identifier,
    )
    snapshot_identifier = local_workspace.snapshots[position]
    succeeded = 0
    last_error: Exception | None = None
    for archive in archives:
        stores = object_stores(session, archive)
        try:
            try:
                snapshot = await stores.snapshot.get(snapshot_identifier)
            except ClientResponseError as error:
                if error.status != HTTPStatus.NOT_FOUND:
                    raise
                LOGGER.warning(
                    "version %d already forgotten on %s %s",
                    version,
                    archive.url,
                    archive.user_id,
                )
            else:
                await _delete_snapshot(stores, snapshot)
                await stores.snapshot.delete(snapshot_identifier)
            await stores.workspace.set(remote_workspace.id, remote_workspace)
        except _REMOTE_ERRORS as error:
            LOGGER.warning("%s: %s", archive.url, format_error(error))
            last_error = error
            continue
        succeeded += 1
        on_forget(archive, position + 1)
    if succeeded == 0 and last_error is not None:
        raise last_error
    LOGGER.info("forgot version %d on %d archive(s)", version, succeeded)
    return trimmed


async def _forget_all(
    session: aiohttp.ClientSession,
    archives: list[Archive],
    local_workspace: LocalWorkspace,
    on_forget: Callable[[Archive, int | None], None],
) -> LocalWorkspace:
    empty = LocalWorkspace(identifier=local_workspace.identifier)
    remote_workspace = Workspace(snapshot_ids=set(), id=empty.identifier)
    succeeded = 0
    last_error: Exception | None = None
    for archive in archives:
        stores = object_stores(session, archive)
        try:
            await _delete_snapshots(stores, local_workspace.snapshots)
            await stores.workspace.set(remote_workspace.id, remote_workspace)
        except _REMOTE_ERRORS as error:
            LOGGER.warning("%s: %s", archive.url, format_error(error))
            last_error = error
            continue
        succeeded += 1
        on_forget(archive, None)
    if succeeded == 0 and last_error is not None:
        raise last_error
    LOGGER.info("forgot all versions on %d archive(s)", succeeded)
    return empty


async def forget_command(
    workspace_path: Path,
    version: int | None,
    forget_all: bool,  # noqa: FBT001
    on_forget: Callable[[Archive, int | None], None],
) -> None:
    archives = _active_archives(workspace_path)
    local_workspace = read_workspace(workspace_path)
    if not local_workspace.snapshots:
        message = "workspace has no versions"
        raise EvError(message)
    async with aiohttp.ClientSession() as session:
        if forget_all:
            result = await _forget_all(session, archives, local_workspace, on_forget)
        elif version is not None:
            result = await _forget_by_version(
                session, archives, local_workspace, version, on_forget
            )
        else:
            message_0 = "choose --version or --all"
            raise EvError(message_0)
    write_workspace(workspace_path, result)
