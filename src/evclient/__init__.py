import asyncio

from evclient.operations import call_delete_user_id, call_register_user_id
from evclient.types import User


async def run() -> None:
    uri = "http://127.0.0.1:8000"
    user = User.random()
    await call_register_user_id(uri, user.id)
    await call_delete_user_id(uri, user.id)


def main() -> None:
    asyncio.run(run())
