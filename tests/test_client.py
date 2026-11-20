import asyncio
import socket
import threading
import time
from typing import TYPE_CHECKING

import aiohttp
import pytest
import uvicorn
from evserver import application

from evclient import build_parser
from evclient.operations import (
    clone_command,
    forget_command,
    list_command,
    login_command,
    logout_command,
    register_command,
    save_command,
    unregister_command,
)
from evclient.types import EvError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.chdir(server_dir)
    port = _free_port()
    config = uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not server.started:
        if time.monotonic() > deadline:
            msg = "evserver failed to start"
            raise TimeoutError(msg)
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def test_cli_parser_commands() -> None:
    parser = build_parser()

    reg = parser.parse_args(["archive", "http://localhost", "register", "alice"])
    assert (reg.command, reg.action, reg.url, reg.user) == (
        "archive",
        "register",
        "http://localhost",
        "alice",
    )

    unreg = parser.parse_args(["archive", "http://localhost", "unregister", "alice"])
    assert (unreg.command, unreg.action, unreg.url, unreg.user) == (
        "archive",
        "unregister",
        "http://localhost",
        "alice",
    )

    login = parser.parse_args(["workspace", ".", "login", "http://localhost", "alice"])
    assert (login.command, login.action, login.path, login.archive, login.user) == (
        "workspace",
        "login",
        ".",
        "http://localhost",
        "alice",
    )

    save = parser.parse_args(["workspace", ".", "save", "-n", "initial"])
    assert (save.command, save.action, save.path, save.note) == (
        "workspace",
        "save",
        ".",
        "initial",
    )

    lst = parser.parse_args(["-VV", "workspace", ".", "list", "-v", "1"])
    assert (lst.verbose, lst.command, lst.action, lst.path, lst.version) == (
        2,
        "workspace",
        "list",
        ".",
        1,
    )

    clone = parser.parse_args(["workspace", "src", "clone", "dst", "-v", "2"])
    assert (clone.command, clone.action, clone.path, clone.target, clone.version) == (
        "workspace",
        "clone",
        "src",
        "dst",
        2,
    )

    forget = parser.parse_args(["workspace", ".", "forget", "-a"])
    assert (forget.command, forget.action, forget.path, forget.forget_all) == (
        "workspace",
        "forget",
        ".",
        True,
    )


def test_end_to_end_workflow(server_url: str, tmp_path: Path) -> None:
    async def run() -> None:
        generated_id = await register_command(server_url)
        assert generated_id

        claimed_id = await register_command(server_url, "alice")
        assert claimed_id == "alice"

        with pytest.raises(EvError, match="user already exists"):
            await register_command(server_url, "alice")

        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        (workspace_dir / "hello.txt").write_text("v1", encoding="utf-8")

        login_command(workspace_dir, server_url, "alice")

        _, version1, _ = await save_command(workspace_dir, note="first")
        assert version1 == 1

        (workspace_dir / "hello.txt").write_text("v2", encoding="utf-8")
        (workspace_dir / "deleted.txt").write_text("temp", encoding="utf-8")
        (workspace_dir / "sub").mkdir()
        (workspace_dir / "sub" / "extra.txt").write_text("extra", encoding="utf-8")
        expected_second_version = 2
        _, version2, _ = await save_command(workspace_dir, note="second")
        assert version2 == expected_second_version

        (workspace_dir / "deleted.txt").unlink()
        expected_third_version = 3
        _, version3, _ = await save_command(workspace_dir, note="delete temp")
        assert version3 == expected_third_version

        _, listings = await list_command(workspace_dir)
        assert [(item.number, item.note) for item in listings] == [
            (1, "first"),
            (2, "second"),
            (3, "delete temp"),
        ]

        _, single = await list_command(workspace_dir, version=1)
        assert [(item.number, item.note) for item in single] == [(1, "first")]

        cloned_dir = tmp_path / "cloned"
        _, first, last = await clone_command(workspace_dir, cloned_dir)
        assert (first, last) == (1, 3)
        assert (cloned_dir / "hello.txt").read_text(encoding="utf-8") == "v2"
        assert (cloned_dir / "sub" / "extra.txt").read_text(encoding="utf-8") == "extra"
        assert not (cloned_dir / "deleted.txt").exists()

        forgotten: list[tuple[str, int | None]] = []
        await forget_command(
            workspace_dir,
            version=1,
            forget_all=False,
            on_forget=lambda archive, number: forgotten.append(
                (archive.user_id, number)
            ),
        )
        assert forgotten == [("alice", 1)]

        _, remaining = await list_command(workspace_dir)
        assert [(item.number, item.note) for item in remaining] == [
            (1, "second"),
            (2, "delete temp"),
        ]

        await forget_command(
            workspace_dir,
            version=None,
            forget_all=True,
            on_forget=lambda archive, number: forgotten.append(
                (archive.user_id, number)
            ),
        )
        assert forgotten[-1] == ("alice", None)

        assert logout_command(workspace_dir, server_url, "alice") is True
        assert logout_command(workspace_dir, server_url, "alice") is False

        await unregister_command(server_url, "alice")
        await unregister_command(server_url, generated_id)

    asyncio.run(run())


def test_clone_versions(server_url: str, tmp_path: Path) -> None:
    async def run() -> None:
        await register_command(server_url, "alice")
        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        login_command(workspace_dir, server_url, "alice")

        (workspace_dir / "README.md").write_text("v1", encoding="utf-8")
        await save_command(workspace_dir, note="Write initial README.md")

        (workspace_dir / "README.md").unlink()
        (workspace_dir / "other.txt").write_text("added", encoding="utf-8")
        await save_command(workspace_dir, note="Delete README.md")

        cloned_latest = tmp_path / "cloned_latest"
        _, first, last = await clone_command(workspace_dir, cloned_latest)
        assert (first, last) == (1, 2)
        assert not (cloned_latest / "README.md").exists()
        assert (cloned_latest / "other.txt").read_text(encoding="utf-8") == "added"

        cloned_v1 = tmp_path / "cloned_v1"
        _, v1_first, v1_last = await clone_command(workspace_dir, cloned_v1, version=1)
        assert (v1_first, v1_last) == (1, 1)
        assert (cloned_v1 / "README.md").read_text(encoding="utf-8") == "v1"
        assert not (cloned_v1 / "other.txt").exists()

        _, v1_listings = await list_command(cloned_v1)
        assert [(item.number, item.note) for item in v1_listings] == [
            (1, "Write initial README.md")
        ]

        with pytest.raises(EvError, match="target already exists"):
            await clone_command(workspace_dir, cloned_v1)

    asyncio.run(run())


def test_multiple_fallible_remotes(server_url: str, tmp_path: Path) -> None:
    dead_url = f"http://127.0.0.1:{_free_port()}"

    async def run() -> None:
        await register_command(server_url, "alice")
        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        (workspace_dir / "file.txt").write_text("v1", encoding="utf-8")

        login_command(workspace_dir, dead_url, "alice")
        login_command(workspace_dir, server_url, "alice")

        archive, version, _ = await save_command(workspace_dir, note="fallback save")
        assert archive.url == server_url
        assert version == 1

        list_archive, listings = await list_command(workspace_dir)
        assert list_archive.url == server_url
        assert [(item.number, item.note) for item in listings] == [(1, "fallback save")]

        cloned_dir = tmp_path / "cloned"
        clone_archive, first, last = await clone_command(workspace_dir, cloned_dir)
        assert clone_archive.url == server_url
        assert (first, last) == (1, 1)
        assert (cloned_dir / "file.txt").read_text(encoding="utf-8") == "v1"

        forgotten: list[str] = []
        await forget_command(
            workspace_dir,
            version=1,
            forget_all=False,
            on_forget=lambda item, _: forgotten.append(item.url),
        )
        assert forgotten == [server_url]

        with pytest.raises(EvError, match="workspace has no versions"):
            await list_command(workspace_dir)

        logout_command(workspace_dir, server_url, "alice")
        with pytest.raises(aiohttp.ClientError):
            await save_command(workspace_dir, note="all down")

    asyncio.run(run())
