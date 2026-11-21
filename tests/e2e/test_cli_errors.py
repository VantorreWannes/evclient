import logging
import sys
from typing import TYPE_CHECKING

import pytest

from evclient.cli import main
from tests.conftest import RunningServer, free_port

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["ev", *argv])
    main()


def test_cli_error_cases(
    start_server: Callable[[str, int | None], RunningServer],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    server = start_server("e2e_server", None)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_text("hi", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "list"])
    assert exc.value.code == 1
    assert "no active archive: login first" in caplog.text

    caplog.clear()
    _run_cli(monkeypatch, ["archive", server.url, "register", "0"])
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["archive", server.url, "register", "0"])
    assert exc.value.code == 1
    assert "user already exists: 0" in caplog.text

    caplog.clear()
    _run_cli(monkeypatch, ["workspace", str(ws), "login", server.url, "0"])
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "list"])
    assert exc.value.code == 1
    assert "workspace has no versions" in caplog.text

    _run_cli(monkeypatch, ["workspace", str(ws), "save", "-n", "v1"])

    caplog.clear()
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "list", "-v", "99"])
    assert exc.value.code == 1
    assert "version 99 out of range" in caplog.text

    existing = tmp_path / "existing"
    existing.mkdir()
    caplog.clear()
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "clone", str(existing)])
    assert exc.value.code == 1
    assert "target already exists" in caplog.text

    port = server.port
    server.stop()

    caplog.clear()
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "list"])
    assert exc.value.code == 1
    assert f"cannot connect to 127.0.0.1:{port}" in caplog.text

    wiped = start_server("e2e_wiped", port)
    caplog.clear()
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["workspace", str(ws), "list"])
    assert exc.value.code == 1
    assert "HTTP 404 (Not Found)" in caplog.text
    wiped.stop()


def test_cli_failover_warning_and_success(
    server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    dead_url = f"http://127.0.0.1:{free_port()}"
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_text("v1", encoding="utf-8")

    _run_cli(monkeypatch, ["archive", server_url, "register", "0"])
    _run_cli(monkeypatch, ["workspace", str(ws), "login", dead_url, "0"])
    _run_cli(monkeypatch, ["workspace", str(ws), "login", server_url, "0"])
    _run_cli(monkeypatch, ["-V", "workspace", str(ws), "save", "-n", "v1"])
    assert f"{dead_url}: cannot connect to" in caplog.text

    caplog.clear()
    _run_cli(monkeypatch, ["-V", "workspace", str(ws), "list"])
    captured = capsys.readouterr()
    assert "1: " in captured.out
    assert "-- v1" in captured.out
    assert f"{dead_url}: cannot connect to" in caplog.text
