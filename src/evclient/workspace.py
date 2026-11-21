from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from evclient.types import (
    Content,
    EvError,
    Manifest,
    Reference,
    SnapshotId,
    UserId,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class Account:
    url: str
    user_id: UserId


@dataclass(frozen=True, slots=True)
class WorkspaceState:
    identifier: WorkspaceId
    snapshots: tuple[SnapshotId, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectedManifest:
    manifest: Manifest
    references: tuple[Reference, ...]
    contents: tuple[Content, ...]


def _read_json[T](path: Path, model: type[T], default: T) -> T:
    if not path.exists():
        return default
    try:
        return TypeAdapter(model).validate_json(path.read_bytes())
    except Exception as error:
        message = f"malformed {path.name}: {error}"
        raise EvError(message) from error


def _write_json[T](path: Path, model: type[T], value: T) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TypeAdapter(model).dump_json(value))


@dataclass(frozen=True, slots=True)
class Workspace:
    path: Path

    def _config(self, name: str) -> Path:
        return self.path / ".ev" / name

    def accounts(self) -> list[Account]:
        return _read_json(self._config("accounts.json"), list[Account], [])

    def login(self, account: Account) -> bool:
        accounts = self.accounts()
        if account in accounts:
            return False
        accounts.append(account)
        _write_json(self._config("accounts.json"), list[Account], accounts)
        return True

    def logout(self, account: Account) -> bool:
        accounts = self.accounts()
        if account not in accounts:
            return False
        accounts.remove(account)
        _write_json(self._config("accounts.json"), list[Account], accounts)
        return True

    def state(self) -> WorkspaceState:
        return _read_json(
            self._config("workspace.json"),
            WorkspaceState,
            WorkspaceState(identifier=uuid4().hex),
        )

    def write_state(self, state: WorkspaceState) -> None:
        _write_json(self._config("workspace.json"), WorkspaceState, state)

    def collect_manifest(self) -> CollectedManifest:
        entries = [
            (
                content := Content(data=entry.read_bytes()),
                Reference(
                    file_path=entry.relative_to(self.path),
                    content_id=content.id,
                ),
            )
            for entry in sorted(self.path.rglob("*"))
            if entry.is_file()
            and not any(
                part.startswith(".") for part in entry.relative_to(self.path).parts
            )
        ]
        contents = tuple(content for content, _ in entries)
        references = tuple(reference for _, reference in entries)
        manifest = Manifest(reference_ids={reference.id for reference in references})
        return CollectedManifest(
            manifest=manifest,
            references=references,
            contents=contents,
        )

    def write_file(self, relative_path: Path, data: bytes) -> None:
        target = self.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
