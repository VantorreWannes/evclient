import uuid
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import dill
from blake3 import blake3
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from pydantic import AnyUrl

Digest = str
UserId = str
WorkspaceId = Digest
SnapshotId = Digest
ManifestId = Digest
ReferenceId = Digest
ContentId = Digest
ArchiveId = Digest


@dataclass(frozen=True, slots=True)
class Reference:
    file_path: Path
    content_digest: ContentId

    @property
    def id(self) -> ReferenceId:
        return blake3(dill.dumps((self.file_path, self.content_digest))).hexdigest()


@dataclass(frozen=True, slots=True)
class Manifest:
    reference_ids: tuple[ReferenceId, ...]

    @property
    def id(self) -> ManifestId:
        return blake3(dill.dumps(self.reference_ids)).hexdigest()


@dataclass(frozen=True, slots=True)
class Snapshot:
    comment: str | None
    manifest_id: ManifestId

    @property
    def id(self) -> SnapshotId:
        return blake3(dill.dumps(self.comment, self.manifest_id)).hexdigest()


@dataclass(frozen=True, slots=True)
class Workspace:
    directory: Path
    snapshot_ids: tuple[SnapshotId, ...]

    @property
    def id(self) -> SnapshotId:
        return blake3(dill.dumps(self.directory)).hexdigest()


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    workspace_ids: set[WorkspaceId]

    @classmethod
    def random(cls) -> User:
        return User(uuid.uuid4().hex, set())

    @classmethod
    def from_id(cls, user_id: UserId) -> User:
        return User(user_id, set())


@dataclass(frozen=True, slots=True)
class Archive:
    url: str
    user_id: UserId

    @property
    def id(self) -> ArchiveId:
        return blake3(dill.dumps((self.url, self.user_id))).hexdigest()
