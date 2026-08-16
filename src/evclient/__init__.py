import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

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
from evclient.types import Archive, EvError

LOGGER = logging.getLogger("evclient")


def _note_suffix(note: str | None) -> str:
    return f" -- {note}" if note else ""


def _workspace(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def _archive_url(raw: str) -> str:
    if raw == ".":
        msg = "archive command requires an archive URL"
        raise EvError(msg)
    return raw


def _forget_message(archive: Archive, number: int | None) -> str:
    target = f"version {number}" if number is not None else "all versions"
    return f"{archive.url} {archive.user_id}: forgot {target}"


async def _register(args: argparse.Namespace) -> None:
    user_id = await register_command(_archive_url(args.path), args.user)
    print(user_id)  # noqa: T201


async def _unregister(args: argparse.Namespace) -> None:
    await unregister_command(_archive_url(args.path), args.user)
    LOGGER.info("unregistered: %s %s", args.path, args.user)


async def _login(args: argparse.Namespace) -> None:
    archive = login_command(_workspace(args.path), args.archive, args.user)
    LOGGER.info("logged in: %s %s", archive.url, archive.user_id)


async def _logout(args: argparse.Namespace) -> None:
    logout_command(_workspace(args.path), args.archive, args.user)
    LOGGER.info("logged out: %s %s", args.archive, args.user)


async def _save(args: argparse.Namespace) -> None:
    archive, number, _ = await save_command(_workspace(args.path), args.note)
    LOGGER.info(
        "saved version %d to %s%s", number, archive.url, _note_suffix(args.note)
    )


async def _list(args: argparse.Namespace) -> None:
    _, listings = await list_command(_workspace(args.path), args.version)
    for listing in listings:
        print(f"{listing.number}: {listing.identifier}{_note_suffix(listing.note)}")  # noqa: T201


async def _clone(args: argparse.Namespace) -> None:
    archive, first, last = await clone_command(
        _workspace(args.path), _workspace(args.target), args.version
    )
    span = f"versions {first}..{last}" if first != last else f"version {first}"
    LOGGER.info(
        "cloned %s from %s to %s via %s", span, args.path, args.target, archive.url
    )


async def _forget(args: argparse.Namespace) -> None:
    await forget_command(
        _workspace(args.path),
        args.version,
        args.forget_all,
        lambda archive, number: LOGGER.info("%s", _forget_message(archive, number)),
    )


type CommandHandler = Callable[[argparse.Namespace], Awaitable[None]]

_COMMANDS: dict[str, CommandHandler] = {
    "archive/register": _register,
    "archive/unregister": _unregister,
    "login": _login,
    "logout": _logout,
    "save": _save,
    "list": _list,
    "clone": _clone,
    "forget": _forget,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ev", description="EasyVersion: content-hashed workspace archives."
    )
    parser.add_argument(
        "path", help="Workspace path, or archive URL for `archive` commands."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        dest="verbose",
        action="count",
        default=0,
        help="Increase log verbosity (repeatable).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive_parser = subparsers.add_parser("archive", help="Manage archive accounts.")
    archive_subparsers = archive_parser.add_subparsers(dest="action", required=True)
    register_parser = archive_subparsers.add_parser(
        "register", help="Claim a user ID; archive-chosen when omitted."
    )
    register_parser.add_argument("user", nargs="?", default=None, help="User ID.")
    unregister_parser = archive_subparsers.add_parser(
        "unregister", help="Forget the user and everything it stored."
    )
    unregister_parser.add_argument("user", help="User ID.")

    login_parser = subparsers.add_parser("login", help="Activate an archive account.")
    login_parser.add_argument("archive", help="Archive URL.")
    login_parser.add_argument("user", help="User ID.")

    logout_parser = subparsers.add_parser(
        "logout", help="Deactivate an archive account."
    )
    logout_parser.add_argument("archive", help="Archive URL.")
    logout_parser.add_argument("user", help="User ID.")

    save_parser = subparsers.add_parser(
        "save", help="Save the current state as a version."
    )
    save_parser.add_argument(
        "--note", "-n", dest="note", default=None, help="Version note."
    )

    list_parser = subparsers.add_parser("list", help="List versions.")
    list_parser.add_argument(
        "--version", "-V", dest="version", type=int, default=None, help="Version."
    )

    clone_parser = subparsers.add_parser("clone", help="Clone a workspace.")
    clone_parser.add_argument("target", help="Target path, may not exist.")
    clone_parser.add_argument(
        "--version", "-V", dest="version", type=int, default=None, help="Version."
    )

    forget_parser = subparsers.add_parser(
        "forget", help="Forget versions on every archive."
    )
    forget_group = forget_parser.add_mutually_exclusive_group(required=True)
    forget_group.add_argument(
        "--version", "-V", dest="version", type=int, default=None, help="Version."
    )
    forget_group.add_argument(
        "--all", "-a", dest="forget_all", action="store_true", help="All versions."
    )

    return parser


def _log_level(verbosity: int) -> int:
    return (logging.WARNING, logging.INFO, logging.DEBUG)[min(verbosity, 2)]


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=_log_level(args.verbose), format="%(levelname)s %(name)s: %(message)s"
    )
    key = f"{args.command}/{args.action}" if args.command == "archive" else args.command
    try:
        asyncio.run(_COMMANDS[key](args))
    except (EvError, OSError, ValueError) as error:
        LOGGER.error("%s", error)  # noqa: TRY400 (no traceback for expected errors)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
