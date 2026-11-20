from dataclasses import dataclass as stdlib_dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import dill
from evserver.types import UserId, WorkspaceId
from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from evserver.types import UserId, WorkspaceId


class EvError(Exception):
    pass


def normalize_url(url: str) -> str:
    return url.rstrip("/")


def new_workspace_identifier() -> WorkspaceId:
    return uuid4().hex


def encode(value: object) -> bytes:
    return dill.dumps(value)


def decode[T](expected_type: type[T], data: bytes) -> T:
    try:
        value = dill.loads(data)  # noqa: S301
    except Exception as error:
        message = f"malformed archive payload: {error}"
        raise EvError(message) from error
    if not isinstance(value, expected_type):
        message = (
            f"unexpected payload type: expected {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )
        raise EvError(message)
    return value


def encode_json[T](value: T) -> bytes:
    return TypeAdapter(type(value)).dump_json(value)


def decode_json[T](model: type[T], data: bytes) -> T:
    try:
        return TypeAdapter(model).validate_json(data)
    except Exception as error:
        message = f"malformed local state: {error}"
        raise EvError(message) from error


@stdlib_dataclass(frozen=True, slots=True)
class Archive:
    url: str
    user_id: UserId


@dataclass(frozen=True, slots=True)
class LocalWorkspace:
    identifier: str
    snapshots: tuple[str, ...] = ()
