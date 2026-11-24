import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from evclient.logger import dataclass
from evclient.types import Id

if TYPE_CHECKING:
    import aiohttp

LOGGER = logging.getLogger("evclient.archive")


@dataclass
class Archive[T]:
    session: aiohttp.ClientSession
    domain: str
    model: type[T]

    def url(self, key: Id) -> str:
        return f"{self.domain}/{key}"

    async def get(self, key: Id) -> T:
        url = self.url(key)
        LOGGER.debug("GET %s", url)
        async with self.session.get(url) as response:
            response.raise_for_status()
            payload = await response.read()
        LOGGER.debug("GET %s -> %d bytes", url, len(payload))
        return TypeAdapter(self.model).validate_json(payload)

    async def contains(self, key: Id) -> bool:
        url = self.url(key)
        LOGGER.debug("HEAD %s", url)
        async with self.session.head(url) as response:
            exists = response.status == HTTPStatus.OK
        LOGGER.debug("HEAD %s -> %s", url, "hit" if exists else "miss")
        return exists

    async def set(self, key: Id, value: T) -> None:
        url = self.url(key)
        payload = TypeAdapter(self.model).dump_json(value)
        LOGGER.debug("PUT %s (%d bytes)", url, len(payload))
        async with self.session.put(
            url, data=payload, headers={"Content-Type": "application/json"}
        ) as response:
            response.raise_for_status()

    async def delete(self, key: Id) -> None:
        url = self.url(key)
        LOGGER.debug("DELETE %s", url)
        async with self.session.delete(url) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                LOGGER.debug("DELETE %s -> already gone", url)
                return
            response.raise_for_status()
