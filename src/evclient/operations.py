import aiohttp

from evclient.types import User, UserId

REGISTER_USER_ENDPOINT = "/user/register"
REGISTER_USER_ID_ENDPOINT = "/user/register/{user_id}"
DELETE_USER_ENDPOINT = "/user/{user_id}"


async def call_register_user(archive_url: str) -> User:
    url = archive_url + REGISTER_USER_ENDPOINT
    async with (
        aiohttp.ClientSession() as session,
        session.post(url) as response,
    ):
        response.raise_for_status()
        return User(**await response.json())


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


async def register_command(archive_url: str, user_id: UserId | None) -> None:
    if user_id:
        await call_register_user_id(archive_url, user_id)
    else:
        await call_register_user(archive_url)


async def unregister_command(archive_url: str, user_id: UserId) -> None:
    await call_delete_user_id(archive_url, user_id)
