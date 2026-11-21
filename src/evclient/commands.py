import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

import aiohttp
from aiohttp import ClientResponseError

from evclient.archive import Archive
from evclient.types import (
    Content,
    EvError,
    Manifest,
    Reference,
    RemoteWorkspace,
    Snapshot,
    SnapshotId,
    User,
    UserId,
)
from evclient.workspace import (
    Account,
    CollectedManifest,
    Workspace,
    WorkspaceState,
)

LOGGER = logging.getLogger("evclient.commands")

_REMOTE_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, ValueError)


@dataclass(frozen=True, slots=True)
class VersionListing:
    number: int
    identifier: SnapshotId
    note: str | None


@dataclass(frozen=True, slots=True)
class SaveResult:
    account: Account
    version: int
    snapshot_id: SnapshotId


@dataclass(frozen=True, slots=True)
class ListResult:
    account: Account
    listings: tuple[VersionListing, ...]


@dataclass(frozen=True, slots=True)
class CloneResult:
    account: Account
    first: int
    last: int


@dataclass(frozen=True, slots=True)
class ForgetResult:
    accounts: tuple[Account, ...]
    version: int | None


@dataclass(frozen=True, slots=True)
class Remote:
    session: aiohttp.ClientSession
    base_url: str

    @classmethod
    def connect(cls, session: aiohttp.ClientSession, url: str) -> Remote:
        return cls(session=session, base_url=url.rstrip("/"))

    @property
    def user(self) -> Archive[User]:
        return Archive(
            session=self.session, domain=f"{self.base_url}/user", model=User
        )

    @property
    def workspace(self) -> Archive[RemoteWorkspace]:
        return Archive(
            session=self.session,
            domain=f"{self.base_url}/workspace",
            model=RemoteWorkspace,
        )

    @property
    def snapshot(self) -> Archive[Snapshot]:
        return Archive(
            session=self.session, domain=f"{self.base_url}/snapshot", model=Snapshot
        )

    @property
    def manifest(self) -> Archive[Manifest]:
        return Archive(
            session=self.session, domain=f"{self.base_url}/manifest", model=Manifest
        )

    @property
    def reference(self) -> Archive[Reference]:
        return Archive(
            session=self.session,
            domain=f"{self.base_url}/reference",
            model=Reference,
        )

    @property
    def content(self) -> Archive[Content]:
        return Archive(
            session=self.session, domain=f"{self.base_url}/content", model=Content
        )

    async def update_workspace(self, state: WorkspaceState) -> None:
        remote_workspace = RemoteWorkspace(
            snapshot_ids=set(state.snapshots),
            id=state.identifier,
        )
        await self.workspace.set(remote_workspace.id, remote_workspace)

    async def save_snapshot(
        self,
        collected: CollectedManifest,
        snapshot: Snapshot,
        state: WorkspaceState,
    ) -> None:
        await asyncio.gather(
            *(self.content.set(item.id, item) for item in collected.contents)
        )
        await asyncio.gather(
            *(self.reference.set(item.id, item) for item in collected.references)
        )
        await self.manifest.set(collected.manifest.id, collected.manifest)
        await self.snapshot.set(snapshot.id, snapshot)
        await self.update_workspace(state)

    async def restore_snapshot(
        self, snapshot_id: SnapshotId
    ) -> list[tuple[Path, bytes]]:
        snapshot = await self.snapshot.get(snapshot_id)
        manifest = await self.manifest.get(snapshot.manifest_id)
        references = await asyncio.gather(
            *(
                self.reference.get(reference_id)
                for reference_id in manifest.reference_ids
            )
        )
        contents = await asyncio.gather(
            *(self.content.get(reference.content_id) for reference in references)
        )
        return [
            (reference.file_path, content.data)
            for reference, content in zip(references, contents, strict=True)
        ]

    async def delete_snapshot(self, snapshot_id: SnapshotId) -> bool:
        try:
            snapshot = await self.snapshot.get(snapshot_id)
        except ClientResponseError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise
            return False
        await self._delete_manifest(snapshot.manifest_id)
        await self.snapshot.delete(snapshot_id)
        return True

    async def _delete_manifest(self, manifest_id: str) -> None:
        try:
            manifest = await self.manifest.get(manifest_id)
        except ClientResponseError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise
            return
        for reference_id in manifest.reference_ids:
            try:
                reference = await self.reference.get(reference_id)
            except ClientResponseError as error:
                if error.status != HTTPStatus.NOT_FOUND:
                    raise
                continue
            await self.content.delete(reference.content_id)
            await self.reference.delete(reference_id)
        await self.manifest.delete(manifest_id)

    async def forget_version(
        self,
        account: Account,
        snapshot_id: SnapshotId,
        state: WorkspaceState,
        version: int,
    ) -> None:
        if not await self.delete_snapshot(snapshot_id):
            LOGGER.warning(
                "version %d already forgotten on %s %s",
                version,
                account.url,
                account.user_id,
            )
        await self.update_workspace(state)

    async def forget_all(
        self,
        snapshot_ids: tuple[SnapshotId, ...],
        state: WorkspaceState,
    ) -> None:
        for snapshot_id in dict.fromkeys(snapshot_ids):
            await self.delete_snapshot(snapshot_id)
        await self.update_workspace(state)


def format_error(error: Exception) -> str:
    if isinstance(error, aiohttp.ClientConnectorError):
        detail = error.strerror or "connection failed"
        return f"cannot connect to {error.host}:{error.port} ({detail})"
    if isinstance(error, ClientResponseError):
        return f"HTTP {error.status} ({error.message})"
    if isinstance(error, TimeoutError):
        return "timed out"
    return str(error) or type(error).__name__


def _open_workspace(workspace_path: Path) -> Workspace:
    return Workspace(path=workspace_path.expanduser().resolve())


def _active_accounts(workspace: Workspace) -> list[Account]:
    accounts = workspace.accounts()
    if not accounts:
        message = "no active archive: login first"
        raise EvError(message)
    return accounts


def _resolve_position(count: int, version: int) -> int:
    if count == 0:
        message = "workspace has no versions"
        raise EvError(message)
    if not 1 <= version <= count:
        message = f"version {version} out of range (1..{count})"
        raise EvError(message)
    return version - 1


def _resolve_positions(count: int, version: int | None) -> list[int]:
    if count == 0:
        message = "workspace has no versions"
        raise EvError(message)
    if version is None:
        return list(range(count))
    return [_resolve_position(count, version)]


async def _try_first[T](
    session: aiohttp.ClientSession,
    accounts: list[Account],
    action: Callable[[Remote], Awaitable[T]],
) -> tuple[Account, T]:
    last_error: Exception | None = None
    for account in accounts:
        try:
            return account, await action(Remote.connect(session, account.url))
        except _REMOTE_ERRORS as error:
            LOGGER.warning("%s: %s", account.url, format_error(error))
            last_error = error
    if last_error is None:
        message = "no active archive: login first"
        raise EvError(message)
    raise EvError(format_error(last_error)) from last_error


async def _try_all(
    session: aiohttp.ClientSession,
    accounts: list[Account],
    action: Callable[[Remote, Account], Awaitable[None]],
) -> list[Account]:
    succeeded: list[Account] = []
    last_error: Exception | None = None
    for account in accounts:
        try:
            await action(Remote.connect(session, account.url), account)
        except _REMOTE_ERRORS as error:
            LOGGER.warning("%s: %s", account.url, format_error(error))
            last_error = error
            continue
        succeeded.append(account)
    if not succeeded:
        if last_error is None:
            message = "no active archive: login first"
            raise EvError(message)
        raise EvError(format_error(last_error)) from last_error
    return succeeded


async def register(archive_url: str, user_id: UserId | None = None) -> UserId:
    resolved_id = user_id if user_id is not None else uuid4().hex
    try:
        async with aiohttp.ClientSession() as session:
            users = Remote.connect(session, archive_url).user
            if user_id is not None and await users.contains(resolved_id):
                message = f"user already exists: {resolved_id}"
                raise EvError(message)
            await users.set(resolved_id, User(id=resolved_id))
    except _REMOTE_ERRORS as error:
        raise EvError(format_error(error)) from error
    return resolved_id


async def unregister(archive_url: str, user_id: UserId) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            await Remote.connect(session, archive_url).user.delete(user_id)
    except _REMOTE_ERRORS as error:
        raise EvError(format_error(error)) from error


def login(workspace_path: Path, archive_url: str, user_id: UserId) -> Account:
    account = Account(url=archive_url, user_id=user_id)
    _open_workspace(workspace_path).login(account)
    return account


def logout(workspace_path: Path, archive_url: str, user_id: UserId) -> bool:
    account = Account(url=archive_url, user_id=user_id)
    return _open_workspace(workspace_path).logout(account)


async def save(workspace_path: Path, note: str | None = None) -> SaveResult:
    workspace = _open_workspace(workspace_path)
    accounts = _active_accounts(workspace)
    collected = workspace.collect_manifest()
    state = workspace.state()
    snapshot = Snapshot(manifest_id=collected.manifest.id, note=note)
    updated_state = WorkspaceState(
        identifier=state.identifier,
        snapshots=(*state.snapshots, snapshot.id),
    )
    async with aiohttp.ClientSession() as session:
        succeeded = await _try_all(
            session,
            accounts,
            lambda remote, _: remote.save_snapshot(collected, snapshot, updated_state),
        )
    workspace.write_state(updated_state)
    return SaveResult(
        account=succeeded[0],
        version=len(updated_state.snapshots),
        snapshot_id=snapshot.id,
    )


async def list_versions(workspace_path: Path, version: int | None = None) -> ListResult:
    workspace = _open_workspace(workspace_path)
    accounts = _active_accounts(workspace)
    state = workspace.state()
    positions = _resolve_positions(len(state.snapshots), version)
    async with aiohttp.ClientSession() as session:
        account, snapshots = await _try_first(
            session,
            accounts,
            lambda remote: asyncio.gather(
                *(
                    remote.snapshot.get(state.snapshots[position])
                    for position in positions
                )
            ),
        )
    listings = tuple(
        VersionListing(
            number=position + 1,
            identifier=state.snapshots[position],
            note=snapshot.note,
        )
        for position, snapshot in zip(positions, snapshots, strict=True)
    )
    return ListResult(account=account, listings=listings)


async def clone(
    source_path: Path, target_path: Path, version: int | None = None
) -> CloneResult:
    resolved_target = target_path.expanduser().resolve()
    if resolved_target.exists():
        message = f"target already exists: {target_path}"
        raise EvError(message)
    source = _open_workspace(source_path)
    accounts = _active_accounts(source)
    state = source.state()
    if not state.snapshots:
        message = "source workspace has nothing to clone"
        raise EvError(message)
    if version is None:
        target_position = len(state.snapshots) - 1
        first, last = 1, len(state.snapshots)
        cloned_snapshots = state.snapshots
    else:
        target_position = _resolve_position(len(state.snapshots), version)
        first = last = target_position + 1
        cloned_snapshots = state.snapshots[: target_position + 1]
    async with aiohttp.ClientSession() as session:
        account, restored = await _try_first(
            session,
            accounts,
            lambda remote: remote.restore_snapshot(state.snapshots[target_position]),
        )
    target = Workspace(path=resolved_target)
    for relative_path, data in restored:
        target.write_file(relative_path, data)
    for item in accounts:
        target.login(item)
    target.write_state(
        WorkspaceState(identifier=uuid4().hex, snapshots=cloned_snapshots)
    )
    return CloneResult(account=account, first=first, last=last)


async def forget(
    workspace_path: Path,
    version: int | None = None,
    *,
    forget_all: bool = False,
) -> ForgetResult:
    workspace = _open_workspace(workspace_path)
    accounts = _active_accounts(workspace)
    state = workspace.state()
    if not state.snapshots:
        message = "workspace has no versions"
        raise EvError(message)
    async with aiohttp.ClientSession() as session:
        if forget_all:
            updated_state = WorkspaceState(identifier=state.identifier)
            succeeded = await _try_all(
                session,
                accounts,
                lambda remote, _: remote.forget_all(state.snapshots, updated_state),
            )
            resolved_version = None
        elif version is not None:
            position = _resolve_position(len(state.snapshots), version)
            updated_state = WorkspaceState(
                identifier=state.identifier,
                snapshots=(
                    state.snapshots[:position] + state.snapshots[position + 1 :]
                ),
            )
            succeeded = await _try_all(
                session,
                accounts,
                lambda remote, account: remote.forget_version(
                    account, state.snapshots[position], updated_state, version
                ),
            )
            resolved_version = position + 1
        else:
            message = "choose --version or --all"
            raise EvError(message)
    workspace.write_state(updated_state)
    return ForgetResult(accounts=tuple(succeeded), version=resolved_version)
