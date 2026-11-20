import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING

import aiohttp
import pytest

from evclient.operations import (
    clone_command,
    forget_command,
    list_command,
    login_command,
    logout_command,
    register_command,
    save_command,
)
from evclient.types import EvError
from tests.conftest import RunningServer, free_port

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_failover_when_primary_down_or_missing(
    start_server: Callable[[str, int | None], RunningServer],
    tmp_path: Path,
) -> None:
    server1 = start_server("server1", None)
    server2 = start_server("server2", None)

    async def run() -> None:
        await register_command(server1.url, "alice")
        await register_command(server2.url, "alice")

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "file.txt").write_text("v1", encoding="utf-8")

        login_command(ws, server1.url, "alice")
        login_command(ws, server2.url, "alice")

        saved_archive, version1, _ = await save_command(ws, note="replicated")
        assert saved_archive.url == server1.url
        assert version1 == 1

        server1.stop()

        list_archive, listings = await list_command(ws)
        assert list_archive.url == server2.url
        assert [(item.number, item.note) for item in listings] == [(1, "replicated")]

        cloned = tmp_path / "cloned"
        clone_archive, first, last = await clone_command(ws, cloned)
        assert clone_archive.url == server2.url
        assert (first, last) == (1, 1)
        assert (cloned / "file.txt").read_text(encoding="utf-8") == "v1"

        (ws / "file.txt").write_text("v2", encoding="utf-8")
        expected_version = 2
        save2_archive, version2, _ = await save_command(ws, note="only s2")
        assert save2_archive.url == server2.url
        assert version2 == expected_version

        wiped_s1 = start_server("server1_wiped", server1.port)
        list_after_wipe, _ = await list_command(ws, version=2)
        assert list_after_wipe.url == server2.url
        wiped_s1.stop()

        forgotten: list[str] = []
        await forget_command(
            ws,
            version=1,
            forget_all=False,
            on_forget=lambda item, _: forgotten.append(item.url),
        )
        assert forgotten == [server2.url]

        await forget_command(
            ws,
            version=None,
            forget_all=True,
            on_forget=lambda item, _: forgotten.append(item.url),
        )
        assert forgotten[-1] == server2.url

        with pytest.raises(EvError, match="workspace has no versions"):
            await list_command(ws)

    asyncio.run(run())


def test_all_remotes_failing_raises(server_url: str, tmp_path: Path) -> None:
    dead_url = f"http://127.0.0.1:{free_port()}"

    async def run() -> None:
        await register_command(server_url, "alice")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("hello", encoding="utf-8")

        login_command(ws, server_url, "alice")
        await save_command(ws, note="v1")

        logout_command(ws, server_url, "alice")
        login_command(ws, dead_url, "alice")

        with pytest.raises(aiohttp.ClientConnectorError):
            await save_command(ws, note="unreachable")
        with pytest.raises(aiohttp.ClientConnectorError):
            await list_command(ws)
        with pytest.raises(aiohttp.ClientConnectorError):
            await clone_command(ws, tmp_path / "cloned")
        with pytest.raises(aiohttp.ClientConnectorError):
            await forget_command(
                ws, version=1, forget_all=False, on_forget=lambda *_: None
            )

    asyncio.run(run())


def test_wiped_server_returns_404(
    start_server: Callable[[str, int | None], RunningServer],
    tmp_path: Path,
) -> None:
    server = start_server("server_original", None)

    async def run() -> None:
        await register_command(server.url, "alice")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("hello", encoding="utf-8")
        login_command(ws, server.url, "alice")
        await save_command(ws, note="v1")

        port = server.port
        server.stop()
        start_server("server_wiped", port)

        with pytest.raises(aiohttp.ClientResponseError) as list_exc:
            await list_command(ws)
        assert list_exc.value.status == HTTPStatus.NOT_FOUND

        with pytest.raises(aiohttp.ClientResponseError) as clone_exc:
            await clone_command(ws, tmp_path / "cloned")
        assert clone_exc.value.status == HTTPStatus.NOT_FOUND

    asyncio.run(run())
