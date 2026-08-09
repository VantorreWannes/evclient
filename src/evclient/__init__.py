import asyncio
from pathlib import Path

from evclient.operations import (
    login_command,
    logout_command,
    register_command,
    unregister_command,
)


async def run() -> None:
    archive_url = "http://127.0.0.1:8000"
    workspace_path = Path("data")
    user_id = await register_command(archive_url)
    await login_command(workspace_path, archive_url, user_id)
    await logout_command(workspace_path, archive_url, user_id)
    await unregister_command(archive_url, user_id)


def main() -> None:
    asyncio.run(run())
