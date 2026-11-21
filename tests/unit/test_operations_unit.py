import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from evclient.commands import (
    Remote,
    _try_first,
    clone,
    forget,
    list_versions,
    login,
    save,
)
from evclient.types import EvError
from evclient.workspace import Account, Workspace, WorkspaceState

if TYPE_CHECKING:
    from pathlib import Path


def test_commands_require_active_archive(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    async def run() -> None:
        with pytest.raises(EvError, match="no active archive"):
            await save(ws)
        with pytest.raises(EvError, match="no active archive"):
            await list_versions(ws)
        with pytest.raises(EvError, match="no active archive"):
            await clone(ws, tmp_path / "dst")
        with pytest.raises(EvError, match="no active archive"):
            await forget(ws, version=1, forget_all=False)

    asyncio.run(run())


def test_workspace_validation_errors(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    login(ws, "http://127.0.0.1:8081", "alice")

    existing_target = tmp_path / "existing"
    existing_target.mkdir()

    async def run() -> None:
        with pytest.raises(EvError, match="workspace has no versions"):
            await list_versions(ws)
        with pytest.raises(EvError, match="target already exists"):
            await clone(ws, existing_target)
        with pytest.raises(EvError, match="source workspace has nothing to clone"):
            await clone(ws, tmp_path / "missing")
        with pytest.raises(EvError, match="workspace has no versions"):
            await forget(ws, version=1, forget_all=False)

        Workspace(path=ws).write_state(
            WorkspaceState(identifier="w1", snapshots=("snap1",))
        )
        with pytest.raises(EvError, match="choose --version or --all"):
            await forget(ws, version=None, forget_all=False)

    asyncio.run(run())


def test_try_archives_fallback_and_exhaustion() -> None:
    a1 = Account(url="http://127.0.0.1:8081", user_id="alice")
    a2 = Account(url="http://127.0.0.1:8082", user_id="alice")
    session = MagicMock()

    async def run() -> None:
        async def fail_first(remote: Remote) -> str:
            if remote.base_url == a1.url:
                raise TimeoutError
            return "ok"

        winner, value = await _try_first(session, [a1, a2], fail_first)
        assert winner == a2
        assert value == "ok"

        async def fail_all(_: Remote) -> str:
            raise TimeoutError

        with pytest.raises(EvError, match="timed out"):
            await _try_first(session, [a1, a2], fail_all)

        with pytest.raises(EvError, match="no active archive"):
            await _try_first(session, [], fail_all)

    asyncio.run(run())
