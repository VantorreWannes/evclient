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
    unregister,
)
from evclient.types import EvError

if TYPE_CHECKING:
    from pathlib import Path


def test_end_to_end_workflow(server_url: str, tmp_path: Path) -> None:
    async def run() -> None:
        generated_id = await register(server_url)
        assert generated_id

        claimed_id = await register(server_url, "alice")
        assert claimed_id == "alice"

        with pytest.raises(EvError, match="user already exists"):
            await register(server_url, "alice")

        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        (workspace_dir / "hello.txt").write_text("v1", encoding="utf-8")

        login(workspace_dir, server_url, "alice")

        save1 = await save(workspace_dir, note="first")
        assert save1.version == 1

        (workspace_dir / "hello.txt").write_text("v2", encoding="utf-8")
        (workspace_dir / "deleted.txt").write_text("temp", encoding="utf-8")
        (workspace_dir / "sub").mkdir()
        (workspace_dir / "sub" / "extra.txt").write_text("extra", encoding="utf-8")
        expected_second_version = 2
        save2 = await save(workspace_dir, note="second")
        assert save2.version == expected_second_version

        (workspace_dir / "deleted.txt").unlink()
        expected_third_version = 3
        save3 = await save(workspace_dir, note="delete temp")
        assert save3.version == expected_third_version

        listed = await list_versions(workspace_dir)
        assert [(item.number, item.note) for item in listed.listings] == [
            (1, "first"),
            (2, "second"),
            (3, "delete temp"),
        ]

        single = await list_versions(workspace_dir, version=1)
        assert [(item.number, item.note) for item in single.listings] == [(1, "first")]

        cloned_dir = tmp_path / "cloned"
        cloned = await clone(workspace_dir, cloned_dir)
        assert (cloned.first, cloned.last) == (1, 3)
        assert (cloned_dir / "hello.txt").read_text(encoding="utf-8") == "v2"
        assert (cloned_dir / "sub" / "extra.txt").read_text(encoding="utf-8") == "extra"
        assert not (cloned_dir / "deleted.txt").exists()

        forgot1 = await forget(workspace_dir, version=1, forget_all=False)
        assert [(account.user_id, forgot1.version) for account in forgot1.accounts] == [
            ("alice", 1)
        ]

        remaining = await list_versions(workspace_dir)
        assert [(item.number, item.note) for item in remaining.listings] == [
            (1, "second"),
            (2, "delete temp"),
        ]

        forgot_all = await forget(workspace_dir, version=None, forget_all=True)
        assert [
            (account.user_id, forgot_all.version) for account in forgot_all.accounts
        ] == [("alice", None)]

        assert logout(workspace_dir, server_url, "alice") is True
        assert logout(workspace_dir, server_url, "alice") is False

        await unregister(server_url, "alice")
        await unregister(server_url, generated_id)

    asyncio.run(run())


def test_clone_versions(server_url: str, tmp_path: Path) -> None:
    async def run() -> None:
        await register(server_url, "alice")
        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        login(workspace_dir, server_url, "alice")

        (workspace_dir / "README.md").write_text("v1", encoding="utf-8")
        await save(workspace_dir, note="Write initial README.md")

        (workspace_dir / "README.md").unlink()
        (workspace_dir / "other.txt").write_text("added", encoding="utf-8")
        await save(workspace_dir, note="Delete README.md")

        cloned_latest = tmp_path / "cloned_latest"
        latest = await clone(workspace_dir, cloned_latest)
        assert (latest.first, latest.last) == (1, 2)
        assert not (cloned_latest / "README.md").exists()
        assert (cloned_latest / "other.txt").read_text(encoding="utf-8") == "added"

        cloned_v1 = tmp_path / "cloned_v1"
        v1 = await clone(workspace_dir, cloned_v1, version=1)
        assert (v1.first, v1.last) == (1, 1)
        assert (cloned_v1 / "README.md").read_text(encoding="utf-8") == "v1"
        assert not (cloned_v1 / "other.txt").exists()

        v1_listed = await list_versions(cloned_v1)
        assert [(item.number, item.note) for item in v1_listed.listings] == [
            (1, "Write initial README.md")
        ]

        with pytest.raises(EvError, match="target already exists"):
            await clone(workspace_dir, cloned_v1)

    asyncio.run(run())
