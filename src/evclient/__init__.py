import argparse
import asyncio
import logging
from pathlib import Path

from evclient.operations import (
    Archive,
    clone_command,
    forget_command,
    list_command,
    login_command,
    logout_command,
    register_command,
    save_command,
    unregister_command,
)
from evclient.types import EvError

LOGGER = logging.getLogger("evclient")


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

    archive_parser = subparsers.add_parser(
        "archive", help="Manage archive user accounts."
    )
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
        "--version",
        "-v",
        dest="version",
        type=int,
        default=None,
        help="Version number.",
    )

    clone_parser = subparsers.add_parser("clone", help="Clone a workspace.")
    clone_parser.add_argument("target", help="Target path, may not exist.")
    clone_parser.add_argument(
        "--version",
        "-v",
        dest="version",
        type=int,
        default=None,
        help="Version number.",
    )

    forget_parser = subparsers.add_parser(
        "forget", help="Forget versions on every archive."
    )
    forget_group = forget_parser.add_mutually_exclusive_group(required=True)
    forget_group.add_argument(
        "--version",
        "-v",
        dest="version",
        type=int,
        default=None,
        help="Version number.",
    )
    forget_group.add_argument(
        "--all", "-a", dest="forget_all", action="store_true", help="All versions."
    )

    return parser


def _workspace(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _version_suffix(note: str | None) -> str:
    return f" -- {note}" if note else ""


def _report_forget(archive: Archive, number: int | None) -> None:
    target = f"version {number}" if number is not None else "all versions"
    LOGGER.info("%s %s: forgot %s", archive.url, archive.user_id, target)


def _archive_url(args: argparse.Namespace) -> str:
    if args.path == ".":
        msg = "archive command requires an archive URL"
        raise EvError(msg)
    return args.path


async def _run(args: argparse.Namespace) -> None:
    if args.command == "archive" and args.action == "register":
        user_id = await register_command(_archive_url(args), args.user)
        print(user_id)  # noqa: T201  (the claimed user ID is program output, not a log)
    elif args.command == "archive" and args.action == "unregister":
        await unregister_command(_archive_url(args), args.user)
    elif args.command == "login":
        archive = login_command(_workspace(args.path), args.archive, args.user)
        LOGGER.info("logged in: %s %s", archive.url, archive.user_id)
    elif args.command == "logout":
        logout_command(_workspace(args.path), args.archive, args.user)
        LOGGER.info("logged out: %s %s", args.archive, args.user)
    elif args.command == "save":
        archive, number, _ = await save_command(_workspace(args.path), args.note)
        LOGGER.info(
            "saved version %d to %s%s", number, archive.url, _version_suffix(args.note)
        )
    elif args.command == "list":
        archive, listings = await list_command(_workspace(args.path), args.version)
        print(f"archive: {archive.url} {archive.user_id}")  # noqa: T201
        for listing in listings:
            print(  # noqa: T201
                f"{listing.number}: {listing.identifier}{_version_suffix(listing.note)}"
            )
    elif args.command == "clone":
        archive, first, last = await clone_command(
            _workspace(args.path), _workspace(args.target), args.version
        )
        span = f"versions {first}..{last}" if first != last else f"version {first}"
        LOGGER.info(
            "cloned %s from %s to %s via %s", span, args.path, args.target, archive.url
        )
    elif args.command == "forget":
        await forget_command(
            _workspace(args.path), args.version, args.forget_all, _report_forget
        )


def _log_level(verbosity: int) -> int:
    return (logging.WARNING, logging.INFO, logging.DEBUG)[min(verbosity, 2)]


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=_log_level(args.verbose), format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(_run(args))
    except (EvError, OSError, ValueError) as error:
        LOGGER.exception("Found an error")
        raise SystemExit(1) from error
