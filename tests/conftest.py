import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    message = f"evserver on port {port} failed to start"
    raise TimeoutError(message)


@dataclass
class RunningServer:
    url: str
    port: int
    directory: Path
    process: subprocess.Popen[bytes]

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5.0)


@pytest.fixture
def start_server(
    tmp_path: Path,
) -> Iterator[Callable[[str, int | None], RunningServer]]:
    processes: list[subprocess.Popen[bytes]] = []

    def _start(name: str = "server", port: int | None = None) -> RunningServer:
        server_dir = tmp_path / name
        server_dir.mkdir(parents=True, exist_ok=True)
        resolved_port = free_port() if port is None else port
        process = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "uvicorn",
                "evserver:application",
                "--host",
                "127.0.0.1",
                "--port",
                str(resolved_port),
                "--log-level",
                "error",
            ],
            cwd=server_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        try:
            _wait_for_port(resolved_port)
        except Exception:
            process.terminate()
            process.wait(timeout=5.0)
            raise
        return RunningServer(
            url=f"http://127.0.0.1:{resolved_port}",
            port=resolved_port,
            directory=server_dir,
            process=process,
        )

    try:
        yield _start
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5.0)


@pytest.fixture
def server_url(
    start_server: Callable[[str, int | None], RunningServer],
) -> str:
    return start_server("server", None).url
