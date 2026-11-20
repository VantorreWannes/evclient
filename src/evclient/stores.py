import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, override

from evserver.types import (
    Content,
    ContentId,
    Id,
    Manifest,
    ManifestId,
    Reference,
    ReferenceId,
    Snapshot,
    SnapshotId,
    User,
    Workspace,
    WorkspaceId,
)

from evclient.types import decode, encode, normalize_url

LOGGER = logging.getLogger("evclient.stores")

if TYPE_CHECKING:
    from collections.abc import Awaitable

    import aiohttp

    from evclient.types import Archive


class Store[K, V](Protocol):
    def get(self, key: K) -> Awaitable[V]: ...

    def set(self, key: K, value: V) -> Awaitable[None]: ...

    def delete(self, key: K) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class ObjectStores:
    workspace: Store[WorkspaceId, Workspace]
    snapshot: Store[SnapshotId, Snapshot]
    manifest: Store[ManifestId, Manifest]
    reference: Store[ReferenceId, Reference]
    content: Store[ContentId, Content]


class ArchiveStore[T](Store[Id, T]):
    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        model: type[T],
        *,
        immutable: bool = True,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._model = model
        self._immutable = immutable

    def _url(self, key: Id) -> str:
        return f"{self._base_url}/{key}"

    @override
    async def get(self, key: Id) -> T:
        LOGGER.debug("GET %s", self._url(key))
        async with self._session.get(self._url(key)) as response:
            response.raise_for_status()
            payload = await response.read()
        LOGGER.debug("GET %s -> %d bytes", self._url(key), len(payload))
        return decode(self._model, payload)

    async def has(self, key: Id) -> bool:
        LOGGER.debug("HEAD %s", self._url(key))
        async with self._session.head(self._url(key)) as response:
            exists = response.status == HTTPStatus.OK
        LOGGER.debug("HEAD %s -> %s", self._url(key), "hit" if exists else "miss")
        return exists

    @override
    async def set(self, key: Id, value: T) -> None:
        if self._immutable and await self.has(key):
            return
        payload = encode(value)
        LOGGER.debug("PUT %s (%d bytes)", self._url(key), len(payload))
        async with self._session.put(self._url(key), data=payload) as response:
            response.raise_for_status()

    @override
    async def delete(self, key: Id) -> None:
        LOGGER.debug("DELETE %s", self._url(key))
        async with self._session.delete(self._url(key)) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                LOGGER.debug("DELETE %s -> already gone", self._url(key))
                return
            response.raise_for_status()


def user_store(session: aiohttp.ClientSession, archive_url: str) -> ArchiveStore[User]:
    base = normalize_url(archive_url)
    return ArchiveStore(session, f"{base}/user", User, immutable=False)


def object_stores(session: aiohttp.ClientSession, archive: Archive) -> ObjectStores:
    base = normalize_url(archive.url)
    return ObjectStores(
        workspace=ArchiveStore(
            session, f"{base}/workspace", Workspace, immutable=False
        ),
        snapshot=ArchiveStore(session, f"{base}/snapshot", Snapshot),
        manifest=ArchiveStore(session, f"{base}/manifest", Manifest),
        reference=ArchiveStore(session, f"{base}/reference", Reference),
        content=ArchiveStore(session, f"{base}/content", Content),
    )
