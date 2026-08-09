import asyncio

from evclient.operations import call_delete_user_id, call_register_user_id
from evclient.types import User


async def run() -> None:
    uri = "http://127.0.0.1:8000"
    user = User.random()
    user_id = await call_register_user_id(uri, user.id)
    user_id = await call_delete_user_id(uri, user.id)
    print(user_id)  # noqa: T201


def main() -> None:
    asyncio.run(run())
