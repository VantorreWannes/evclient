import asyncio
from abc import ABC, abstractmethod
from collections.abc import Hashable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, override

import aiofiles
import dill
from blake3 import blake3

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from evclient.types import Digest


class Store[K, V](Protocol):
    def get(self, key: K) -> Awaitable[V]: ...

    def set(self, key: K, value: V) -> Awaitable[None]: ...

    def delete(self, key: K) -> Awaitable[None]: ...

    def keys(self) -> Awaitable[tuple[K, ...]]: ...

    def contains(self, key: K) -> Awaitable[bool]: ...

    def values(self) -> Awaitable[tuple[V, ...]]: ...

    def length(self) -> Awaitable[int]: ...


class BaseStore[K, V](ABC):
    @abstractmethod
    def get(self, key: K) -> Awaitable[V]: ...

    @abstractmethod
    def set(self, key: K, value: V) -> Awaitable[None]: ...

    @abstractmethod
    def delete(self, key: K) -> Awaitable[None]: ...

    @abstractmethod
    def keys(self) -> Awaitable[tuple[K, ...]]: ...

    async def contains(self, key: K) -> bool:
        return key in await self.keys()

    async def values(self) -> tuple[V, ...]:
        return tuple(await asyncio.gather(*[self.get(k) for k in await self.keys()]))

    async def length(self) -> int:
        return len(await self.keys())


class MemoryStore[K: Hashable, V](BaseStore[K, V]):
    def __init__(self) -> None:
        self._store: dict[K, V] = {}

    @override
    async def get(self, key: K) -> V:
        return self._store[key]

    @override
    async def set(self, key: K, value: V) -> None:
        self._store[key] = value

    @override
    async def delete(self, key: K) -> None:
        self._store.pop(key, None)

    @override
    async def keys(self) -> tuple[K, ...]:
        return tuple(self._store.keys())


class FileStore[K: Hashable, V](BaseStore[K, V]):
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def load(cls, path: Path) -> dict[K, V]:
        if path.exists():
            return dill.loads(path.read_bytes())  # noqa: S301
        return {}

    @classmethod
    def save(cls, path: Path, key_values: dict[K, V]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(dill.dumps(key_values))

    @override
    async def get(self, key: K) -> V:
        key_values = FileStore[K, V].load(self.path)
        return key_values[key]

    @override
    async def set(self, key: K, value: V) -> None:
        key_values = FileStore[K, V].load(self.path)
        key_values[key] = value
        FileStore[K, V].save(self.path, key_values)

    @override
    async def delete(self, key: K) -> None:
        key_values = FileStore[K, V].load(self.path)
        key_values.pop(key)
        FileStore[K, V].save(self.path, key_values)

    @override
    async def keys(self) -> tuple[K, ...]:
        return tuple(FileStore[K, V].load(self.path).keys())


class DirectoryStore[K, V](BaseStore[K, V]):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.key_store = FileStore[K, Path](directory / "index.dill")

    @classmethod
    def digest(cls, key: K) -> Digest:
        return blake3(dill.dumps(key)).hexdigest()

    def filepath(self, key: K) -> Path:
        return self.directory / self.digest(key)

    @override
    async def get(self, key: K) -> V:
        filepath = await self.key_store.get(key)
        async with aiofiles.open(filepath, mode="rb") as f:
            data = await f.read()
        return dill.loads(data)  # noqa: S301

    @override
    async def set(self, key: K, value: V) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        filepath = self.filepath(key)
        await self.key_store.set(key, filepath)
        data = dill.dumps(value)
        async with aiofiles.open(filepath, mode="wb") as f:
            await f.write(data)
        await self.key_store.set(key, filepath)

    @override
    async def delete(self, key: K) -> None:
        filepath = await self.key_store.get(key)
        if filepath and filepath.exists():
            filepath.unlink()
        await self.key_store.delete(key)

    @override
    async def keys(self) -> tuple[K, ...]:
        return await self.key_store.keys()
