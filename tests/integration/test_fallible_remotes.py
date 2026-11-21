import asyncio
from typing import TYPE_CHECKING

import pytest

from evclient.commands import (
    clone,
    forget,
    list_versions,
    login,
    logout,
    register,
    save,
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
        await register(server1.url, "alice")
        await register(server2.url, "alice")

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "file.txt").write_text("v1", encoding="utf-8")

        login(ws, server1.url, "alice")
        login(ws, server2.url, "alice")

        saved = await save(ws, note="replicated")
        assert saved.account.url == server1.url
        assert saved.version == 1

        server1.stop()

        listed = await list_versions(ws)
        assert listed.account.url == server2.url
        assert [(item.number, item.note) for item in listed.listings] == [
            (1, "replicated")
        ]

        cloned_dir = tmp_path / "cloned"
        cloned = await clone(ws, cloned_dir)
        assert cloned.account.url == server2.url
        assert (cloned.first, cloned.last) == (1, 1)
        assert (cloned_dir / "file.txt").read_text(encoding="utf-8") == "v1"

        (ws / "file.txt").write_text("v2", encoding="utf-8")
        expected_version = 2
        saved2 = await save(ws, note="only s2")
        assert saved2.account.url == server2.url
        assert saved2.version == expected_version

        wiped_s1 = start_server("server1_wiped", server1.port)
        listed_after_wipe = await list_versions(ws, version=2)
        assert listed_after_wipe.account.url == server2.url
        wiped_s1.stop()

        forgot1 = await forget(ws, version=1, forget_all=False)
        assert [account.url for account in forgot1.accounts] == [server2.url]

        forgot_all = await forget(ws, version=None, forget_all=True)
        assert [account.url for account in forgot_all.accounts] == [server2.url]

        with pytest.raises(EvError, match="workspace has no versions"):
            await list_versions(ws)

    asyncio.run(run())


def test_all_remotes_failing_raises(server_url: str, tmp_path: Path) -> None:
    dead_url = f"http://127.0.0.1:{free_port()}"

    async def run() -> None:
        await register(server_url, "alice")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("hello", encoding="utf-8")

        login(ws, server_url, "alice")
        await save(ws, note="v1")

        logout(ws, server_url, "alice")
        login(ws, dead_url, "alice")

        with pytest.raises(EvError, match="cannot connect to"):
            await save(ws, note="unreachable")
        with pytest.raises(EvError, match="cannot connect to"):
            await list_versions(ws)
        with pytest.raises(EvError, match="cannot connect to"):
            await clone(ws, tmp_path / "cloned")
        with pytest.raises(EvError, match="cannot connect to"):
            await forget(ws, version=1, forget_all=False)

    asyncio.run(run())


def test_wiped_server_returns_404(
    start_server: Callable[[str, int | None], RunningServer],
    tmp_path: Path,
) -> None:
    server = start_server("server_original", None)

    async def run() -> None:
        await register(server.url, "alice")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("hello", encoding="utf-8")
        login(ws, server.url, "alice")
        await save(ws, note="v1")

        port = server.port
        server.stop()
        start_server("server_wiped", port)

        with pytest.raises(EvError, match="HTTP 404"):
            await list_versions(ws)

        with pytest.raises(EvError, match="HTTP 404"):
            await clone(ws, tmp_path / "cloned")

    asyncio.run(run())
