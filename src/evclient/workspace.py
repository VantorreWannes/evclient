import logging
from typing import TYPE_CHECKING

from evclient.types import (
    Archive,
    EvError,
    WorkspaceObject,
    decode,
    encode,
)

if TYPE_CHECKING:
    from pathlib import Path

LOGGER = logging.getLogger("evclient.workspace")

CONFIG_DIR = ".ev"
ARCHIVES_FILE = "archives"
WORKSPACE_FILE = "workspace.json"


def _config(workspace_path: Path, name: str) -> Path:
    return workspace_path / CONFIG_DIR / name


def read_archives(workspace_path: Path) -> list[Archive]:
    """Read the active archives, one `<archive:URL> <user:ID>` line each."""
    path = _config(workspace_path, ARCHIVES_FILE)
    if not path.exists():
        LOGGER.debug("no %s for %s", ARCHIVES_FILE, workspace_path)
        return []
    archives = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            url, user_id = line.split()
        except ValueError as error:
            msg = f"corrupt {ARCHIVES_FILE} line {number + 1}: {line!r}"
            raise EvError(msg) from error
        archives.append(Archive(url=url, user_id=user_id))
    LOGGER.debug("read %d archive(s) from %s", len(archives), path)
    return archives


def write_archives(workspace_path: Path, archives: list[Archive]) -> None:
    """Write the active archives, one `<archive:URL> <user:ID>` line each."""
    path = _config(workspace_path, ARCHIVES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{archive.url} {archive.user_id}\n" for archive in archives)
    path.write_text(lines, encoding="utf-8")
    LOGGER.debug("wrote %d archive(s) to %s", len(archives), path)


def read_workspace(workspace_path: Path) -> WorkspaceObject:
    """Read the local workspace container; empty when never saved."""
    path = _config(workspace_path, WORKSPACE_FILE)
    if not path.exists():
        LOGGER.debug("no %s for %s", WORKSPACE_FILE, workspace_path)
        return WorkspaceObject()
    return decode(WorkspaceObject, path.read_bytes())


def write_workspace(workspace_path: Path, workspace: WorkspaceObject) -> None:
    """Write the local workspace container."""
    path = _config(workspace_path, WORKSPACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(workspace))
    LOGGER.debug(
        "wrote workspace (%d snapshot(s)) to %s", len(workspace.snapshots), path
    )


def write_file(workspace_path: Path, relative_path: str, data: bytes) -> None:
    """Materialize one file of a version inside a workspace tree."""
    path = workspace_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    LOGGER.debug("materialized %s (%d bytes)", path, len(data))


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def scan_files(workspace_path: Path) -> list[tuple[str, bytes]]:
    """Collect (posix path, bytes) for every non-hidden workspace file."""
    files = [
        (relative.as_posix(), path.read_bytes())
        for path in sorted(workspace_path.rglob("*"))
        if path.is_file()
        and not _is_hidden(relative := path.relative_to(workspace_path))
    ]
    LOGGER.debug("scanned %s -> %d file(s)", workspace_path, len(files))
    return files
