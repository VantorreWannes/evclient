import asyncio
import socket
import threading
import time
from typing import TYPE_CHECKING

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

    lst = parser.parse_args(["workspace", ".", "list", "-V", "1"])
    assert (lst.command, lst.action, lst.path, lst.version) == (
        "workspace",
        "list",
        ".",
        1,
    )

    clone = parser.parse_args(["workspace", "src", "clone", "dst", "-V", "2"])
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
        (workspace_dir / "sub").mkdir()
        (workspace_dir / "sub" / "extra.txt").write_text("extra", encoding="utf-8")
        expected_second_version = 2
        _, version2, _ = await save_command(workspace_dir, note="second")
        assert version2 == expected_second_version

        _, listings = await list_command(workspace_dir)
        assert [(item.number, item.note) for item in listings] == [
            (1, "first"),
            (2, "second"),
        ]

        _, single = await list_command(workspace_dir, version=1)
        assert [(item.number, item.note) for item in single] == [(1, "first")]

        cloned_dir = tmp_path / "cloned"
        _, first, last = await clone_command(workspace_dir, cloned_dir, version=2)
        assert (first, last) == (2, 2)
        assert (cloned_dir / "hello.txt").read_text(encoding="utf-8") == "v2"
        assert (cloned_dir / "sub" / "extra.txt").read_text(encoding="utf-8") == "extra"

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
        assert [(item.number, item.note) for item in remaining] == [(1, "second")]

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
