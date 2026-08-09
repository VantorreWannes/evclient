from typing import TYPE_CHECKING

import aiohttp

from evclient.stores import FileStore, Store
from evclient.types import Archive, User, UserId

if TYPE_CHECKING:
    from pathlib import Path

REGISTER_USER_ENDPOINT = "/user/register"
REGISTER_USER_ID_ENDPOINT = "/user/register/{user_id}"
DELETE_USER_ENDPOINT = "/user/{user_id}"
GET_USER_ENDPOINT = "/user/{user_id}"
ARCHIVE_STORE_FILE = ".ev"


async def get_archive_store(workspace_path: Path) -> Store:
    return FileStore(workspace_path / ARCHIVE_STORE_FILE)


async def call_register_user(archive_url: str) -> UserId:
    url = archive_url + REGISTER_USER_ENDPOINT
    async with (
        aiohttp.ClientSession() as session,
        session.post(url) as response,
    ):
        response.raise_for_status()
        return UserId(await response.json())


async def call_register_user_id(archive_url: str, user_id: UserId) -> None:
    url = archive_url + REGISTER_USER_ID_ENDPOINT.format(user_id=user_id)
    async with (
        aiohttp.ClientSession() as session,
        session.post(url) as response,
    ):
        response.raise_for_status()


async def call_delete_user_id(archive_url: str, user_id: UserId) -> None:
    url = archive_url + DELETE_USER_ENDPOINT.format(user_id=user_id)
    async with (
        aiohttp.ClientSession() as session,
        session.delete(url) as response,
    ):
        response.raise_for_status()


async def call_get_user(archive_url: str, user_id: UserId) -> User:
    url = archive_url + GET_USER_ENDPOINT.format(user_id=user_id)
    async with (
        aiohttp.ClientSession() as session,
        session.get(url) as response,
    ):
        response.raise_for_status()
        return User(**await response.json())


async def register_command(archive_url: str, user_id: UserId | None = None) -> UserId:
    if user_id:
        await call_register_user_id(archive_url, user_id)
        return user_id
    return await call_register_user(archive_url)


async def unregister_command(archive_url: str, user_id: UserId) -> None:
    await call_delete_user_id(archive_url, user_id)


async def login_command(
    workspace_path: Path, archive_url: str, user_id: UserId
) -> None:
    archive = Archive(archive_url, user_id)
    archive_store = await get_archive_store(workspace_path)
    await archive_store.set(archive.id, archive)


async def logout_command(
    workspace_path: Path, archive_url: str, user_id: UserId
) -> None:
    archive = Archive(archive_url, user_id)
    archive_store = await get_archive_store(workspace_path)
    await archive_store.delete(archive.id)
