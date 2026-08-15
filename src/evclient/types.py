from blake3 import blake3
from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

Digest = str
UserId = str
WorkspaceId = Digest
SnapshotId = Digest
ManifestId = Digest
ReferenceId = Digest
ContentId = Digest


class EvError(Exception):
    """Raise for any user-facing failure; the client aborts immediately."""


def normalize_url(url: str) -> str:
    """Strip trailing slashes so endpoint paths always join cleanly."""
    return url.rstrip("/")


def hash_bytes(data: bytes) -> Digest:
    """Hash raw bytes; content is identified by the blake3 of itself."""
    return blake3(data).hexdigest()


def encode[T](obj: T) -> bytes:
    """Serialize an object to its canonical JSON payload."""
    return TypeAdapter(type(obj)).dump_json(obj)


def decode[T](model: type[T], data: bytes) -> T:
    """Parse an archive payload back into its object type."""
    return TypeAdapter(model).validate_json(data)


def hash_object[T](obj: T) -> Digest:
    """Hash an object's canonical payload: its address on the archive."""
    return hash_bytes(encode(obj))


@dataclass(frozen=True, slots=True)
class Archive:
    """An active archive account: a URL plus an archive-issued user ID."""

    url: str
    user_id: UserId


@dataclass(frozen=True, slots=True)
class ReferenceObject:
    """A relative file path and a content hash."""

    path: str
    content: ContentId


@dataclass(frozen=True, slots=True)
class ManifestObject:
    """An array of reference hashes."""

    references: tuple[ReferenceId, ...]


@dataclass(frozen=True, slots=True)
class SnapshotObject:
    """A manifest hash and an optional note."""

    manifest: ManifestId
    note: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceObject:
    """An array of snapshot hashes; array position is the version number."""

    snapshots: tuple[SnapshotId, ...] = ()
