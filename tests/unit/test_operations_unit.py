import asyncio
from typing import TYPE_CHECKING

import pytest

from evclient.operations import (
    _try_archives,
    clone_command,
    forget_command,
    list_command,
    login_command,
    save_command,
)
from evclient.types import Archive, EvError, LocalWorkspace
from evclient.workspace import write_workspace

if TYPE_CHECKING:
    from pathlib import Path


def test_commands_require_active_archive(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    async def run() -> None:
        with pytest.raises(EvError, match="no active archive"):
            await save_command(ws)
        with pytest.raises(EvError, match="no active archive"):
            await list_command(ws)
        with pytest.raises(EvError, match="no active archive"):
            await clone_command(ws, tmp_path / "dst")
        with pytest.raises(EvError, match="no active archive"):
            await forget_command(
                ws, version=1, forget_all=False, on_forget=lambda *_: None
            )

    asyncio.run(run())


def test_workspace_validation_errors(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    login_command(ws, "http://127.0.0.1:8081", "alice")

    existing_target = tmp_path / "existing"
    existing_target.mkdir()

    async def run() -> None:
        with pytest.raises(EvError, match="workspace has no versions"):
            await list_command(ws)
        with pytest.raises(EvError, match="target already exists"):
            await clone_command(ws, existing_target)
        with pytest.raises(EvError, match="source workspace has nothing to clone"):
            await clone_command(ws, tmp_path / "missing")
        with pytest.raises(EvError, match="workspace has no versions"):
            await forget_command(
                ws, version=1, forget_all=False, on_forget=lambda *_: None
            )

        write_workspace(ws, LocalWorkspace(identifier="w1", snapshots=("snap1",)))
        with pytest.raises(EvError, match="choose --version or --all"):
            await forget_command(
                ws, version=None, forget_all=False, on_forget=lambda *_: None
            )

    asyncio.run(run())


def test_try_archives_fallback_and_exhaustion() -> None:
    a1 = Archive(url="http://127.0.0.1:8081", user_id="alice")
    a2 = Archive(url="http://127.0.0.1:8082", user_id="alice")

    async def run() -> None:
        async def fail_first(archive: Archive) -> str:
            if archive == a1:
                raise TimeoutError
            return "ok"

        winner, value = await _try_archives([a1, a2], fail_first)
        assert winner == a2
        assert value == "ok"

        async def fail_all(_: Archive) -> str:
            raise TimeoutError

        with pytest.raises(TimeoutError):
            await _try_archives([a1, a2], fail_all)

        with pytest.raises(EvError, match="no active archive"):
            await _try_archives([], fail_all)

    asyncio.run(run())
