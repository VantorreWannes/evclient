import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, override

from evclient.types import Digest, normalize_url

LOGGER = logging.getLogger("evclient.stores")

if TYPE_CHECKING:
    from collections.abc import Awaitable

    import aiohttp

    from evclient.types import Archive


class Store[K, V](Protocol):
    """Minimal key-value contract shared by every object type."""

    def get(self, key: K) -> Awaitable[V]: ...

    def set(self, key: K, value: V) -> Awaitable[None]: ...

    def delete(self, key: K) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class ObjectStores:
    """The five archive object types as typed store views."""

    workspace: Store[Digest, bytes]
    snapshot: Store[Digest, bytes]
    manifest: Store[Digest, bytes]
    reference: Store[Digest, bytes]
    content: Store[Digest, bytes]


class ArchiveStore(Store[Digest, bytes]):
    """Map the generic HEAD/GET/PUT/DELETE endpoints onto the store contract."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    def _url(self, key: Digest) -> str:
        return f"{self._base_url}/{key}"

    @override
    async def get(self, key: Digest) -> bytes:
        LOGGER.debug("GET %s", self._url(key))
        async with self._session.get(self._url(key)) as response:
            response.raise_for_status()
            payload = await response.read()
        LOGGER.debug("GET %s -> %d bytes", self._url(key), len(payload))
        return payload

    async def _has(self, key: Digest) -> bool:
        LOGGER.debug("HEAD %s", self._url(key))
        async with self._session.head(self._url(key)) as response:
            exists = response.status == HTTPStatus.OK
        LOGGER.debug("HEAD %s -> %s", self._url(key), "hit" if exists else "miss")
        return exists

    @override
    async def set(self, key: Digest, value: bytes) -> None:
        if await self._has(key):
            return
        LOGGER.debug("PUT %s (%d bytes)", self._url(key), len(value))
        async with self._session.put(self._url(key), data=value) as response:
            response.raise_for_status()

    @override
    async def delete(self, key: Digest) -> None:
        LOGGER.debug("DELETE %s", self._url(key))
        async with self._session.delete(self._url(key)) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                LOGGER.debug("DELETE %s -> already gone", self._url(key))
                return
            response.raise_for_status()


def object_stores(session: aiohttp.ClientSession, archive: Archive) -> ObjectStores:
    """Build the five typed store views for one archive account."""
    base = f"{normalize_url(archive.url)}/user/{archive.user_id}"
    return ObjectStores(
        workspace=ArchiveStore(session, f"{base}/workspace"),
        snapshot=ArchiveStore(session, f"{base}/snapshot"),
        manifest=ArchiveStore(session, f"{base}/manifest"),
        reference=ArchiveStore(session, f"{base}/reference"),
        content=ArchiveStore(session, f"{base}/content"),
    )
