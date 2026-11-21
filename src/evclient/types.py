from dataclasses import dataclass
from hashlib import sha3_512
from pathlib import Path

type Id = str
type UserId = Id
type WorkspaceId = Id
type SnapshotId = Id
type ManifestId = Id
type ReferenceId = Id
type ContentId = Id


class EvError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: UserId


@dataclass(frozen=True, slots=True)
class Content:
    data: bytes

    @property
    def id(self) -> ContentId:
        return sha3_512(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class Reference:
    file_path: Path
    content_id: ContentId

    @property
    def id(self) -> ReferenceId:
        return sha3_512(
            str(self.file_path).encode() + self.content_id.encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class Manifest:
    reference_ids: set[ReferenceId]

    @property
    def id(self) -> ManifestId:
        digest = sha3_512()
        for reference_id in self.reference_ids:
            digest.update(reference_id.encode())
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Snapshot:
    manifest_id: ManifestId
    note: str | None = None

    @property
    def id(self) -> SnapshotId:
        digest = sha3_512()
        digest.update(self.manifest_id.encode())
        if self.note:
            digest.update(self.note.encode())
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RemoteWorkspace:
    snapshot_ids: set[SnapshotId]
    id: WorkspaceId
