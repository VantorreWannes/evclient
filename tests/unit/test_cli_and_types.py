from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import ClientConnectorError, ClientResponseError, RequestInfo
from aiohttp.client_reqrep import ConnectionKey
from yarl import URL

from evclient.cli import _archive_url, _note_suffix, build_parser
from evclient.commands import (
    Remote,
    _resolve_positions,
    format_error,
    login,
    logout,
)
from evclient.types import EvError

if TYPE_CHECKING:
    from pathlib import Path


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

    login_args = parser.parse_args(
        ["workspace", ".", "login", "http://localhost", "alice"]
    )
    assert (
        login_args.command,
        login_args.action,
        login_args.path,
        login_args.archive,
        login_args.user,
    ) == (
        "workspace",
        "login",
        ".",
        "http://localhost",
        "alice",
    )

    save_args = parser.parse_args(["workspace", ".", "save", "-n", "initial"])
    assert (save_args.command, save_args.action, save_args.path, save_args.note) == (
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

    clone_args = parser.parse_args(["workspace", "src", "clone", "dst", "-v", "2"])
    assert (
        clone_args.command,
        clone_args.action,
        clone_args.path,
        clone_args.target,
        clone_args.version,
    ) == (
        "workspace",
        "clone",
        "src",
        "dst",
        2,
    )

    forget_args = parser.parse_args(["workspace", ".", "forget", "-a"])
    assert (
        forget_args.command,
        forget_args.action,
        forget_args.path,
        forget_args.forget_all,
    ) == (
        "workspace",
        "forget",
        ".",
        True,
    )


def test_normalize_url_and_helpers() -> None:
    remote = Remote.connect(MagicMock(), "http://127.0.0.1:8080///")
    assert remote.base_url == "http://127.0.0.1:8080"
    assert _note_suffix(None) == ""
    assert _note_suffix("initial") == " -- initial"
    assert _archive_url("http://localhost:8080") == "http://localhost:8080"
    with pytest.raises(EvError, match="archive command requires an archive URL"):
        _archive_url(".")


def test_select_positions() -> None:
    expected_count = 3
    assert _resolve_positions(expected_count, None) == [0, 1, 2]
    assert _resolve_positions(expected_count, 2) == [1]

    with pytest.raises(EvError, match="workspace has no versions"):
        _resolve_positions(0, None)
    with pytest.raises(EvError, match="out of range"):
        _resolve_positions(expected_count, 4)


def test_format_error() -> None:
    request_info = RequestInfo(
        url=URL("http://127.0.0.1:8081/snapshot/abc"),
        method="GET",
        headers=MagicMock(),
        real_url=URL("http://127.0.0.1:8081/snapshot/abc"),
    )
    response_error = ClientResponseError(
        request_info=request_info,
        history=(),
        status=HTTPStatus.NOT_FOUND,
        message="Not Found",
    )
    assert format_error(response_error) == "HTTP 404 (Not Found)"

    conn_key = ConnectionKey(
        "127.0.0.1",
        8081,
        is_ssl=False,
        ssl=False,
        proxy=None,
        proxy_auth=None,
        proxy_headers_hash=None,
    )
    os_error = OSError(10061, "Connection refused")
    connector_error = ClientConnectorError(conn_key, os_error)
    assert (
        format_error(connector_error)
        == "cannot connect to 127.0.0.1:8081 (Connection refused)"
    )

    assert format_error(TimeoutError()) == "timed out"
    assert format_error(EvError("boom")) == "boom"
    assert format_error(aiohttp.ClientError()) == "ClientError"


def test_login_logout_idempotency(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    login(ws, "http://127.0.0.1:8081", "alice")
    login(ws, "http://127.0.0.1:8081", "alice")
    assert logout(ws, "http://127.0.0.1:8081", "alice") is True
    assert logout(ws, "http://127.0.0.1:8081", "alice") is False
