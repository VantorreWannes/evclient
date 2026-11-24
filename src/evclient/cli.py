import argparse
import asyncio
import logging
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path

from evclient.commands import (
    clone,
    clone_remote,
    forget,
    list_remote_workspaces,
    list_versions,
    login,
    logout,
    register,
    save,
    unregister,
)
from evclient.logger import Logger, LogLevel
from evclient.types import EvError
from evclient.workspace import Account, Workspace

LOGGER = logging.getLogger("evclient")
DEFAULT_ARCHIVE_URL = "https://easyversionarchive.com"


def suggest_tokens(
    raw: str,
    accounts: list[Account],
) -> list[str]:
    trailing_space = raw.endswith(" ")
    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()
    completed = tokens if trailing_space else tokens[:-1]
    prefix = "" if trailing_space else (tokens[-1] if tokens else "")

    urls = list(dict.fromkeys([DEFAULT_ARCHIVE_URL, *(a.url for a in accounts)]))
    users = list(dict.fromkeys(a.user_id for a in accounts))

    candidates: list[str] = []
    if not completed:
        candidates = ["workspace", "archive"]
    elif completed[0] == "archive":
        if len(completed) == 1:
            candidates = urls
        elif len(completed) == 2:
            candidates = ["register", "unregister", "workspaces", "clone"]
        elif len(completed) == 3 and completed[2] in {
            "register",
            "unregister",
            "workspaces",
            "clone",
        }:
            candidates = users
        elif (
            len(completed) >= 4
            and completed[2] == "clone"
            and "--version" not in completed
            and "-v" not in completed
        ):
            candidates = ["--version"]
    elif completed[0] == "workspace":
        if len(completed) == 1:
            candidates = ["."]
        elif len(completed) == 2:
            candidates = ["save", "list", "login", "logout", "clone", "forget"]
        elif len(completed) == 3:
            action = completed[2]
            if action in {"login", "logout"}:
                candidates = urls
            elif action == "save":
                candidates = ["--note"]
            elif action in {"list", "clone"}:
                candidates = ["--version"]
            elif action == "forget":
                candidates = ["--version", "--all"]
        elif len(completed) == 4 and completed[2] in {"login", "logout"}:
            candidates = users

    return [item for item in candidates if item.startswith(prefix)]


def _complete(line: str) -> None:
    try:
        accounts = Workspace(path=Path.cwd()).accounts()
    except EvError:
        accounts = []
    for token in suggest_tokens(line, accounts):
        print(token)


def _note_suffix(note: str | None) -> str:
    return f" -- {note}" if note else ""


def _archive_url(raw: str) -> str:
    if raw == ".":
        message = "archive command requires an archive URL"
        raise EvError(message)
    return raw


async def _register(args: argparse.Namespace) -> None:
    user_id = await register(_archive_url(args.url), args.user)
    print(user_id)


async def _unregister(args: argparse.Namespace) -> None:
    await unregister(_archive_url(args.url), args.user)
    LOGGER.info("unregistered: %s %s", args.url, args.user)


async def _workspaces(args: argparse.Namespace) -> None:
    workspace_ids = await list_remote_workspaces(_archive_url(args.url), args.user)
    for workspace_id in workspace_ids:
        print(workspace_id)


async def _archive_clone(args: argparse.Namespace) -> None:
    result = await clone_remote(
        _archive_url(args.url),
        args.user,
        args.workspace,
        Path(args.target),
        args.version,
    )
    span = (
        f"versions {result.first}..{result.last}"
        if result.first != result.last
        else f"version {result.first}"
    )
    LOGGER.info(
        "cloned %s from %s (%s) to %s",
        span,
        result.account.url,
        args.workspace,
        args.target,
    )


async def _login(args: argparse.Namespace) -> None:
    account = login(Path(args.path), args.archive, args.user)
    LOGGER.info("logged in: %s %s", account.url, account.user_id)


async def _logout(args: argparse.Namespace) -> None:
    logout(Path(args.path), args.archive, args.user)
    LOGGER.info("logged out: %s %s", args.archive, args.user)


async def _save(args: argparse.Namespace) -> None:
    result = await save(Path(args.path), args.note)
    LOGGER.info(
        "saved version %d to %s%s",
        result.version,
        result.account.url,
        _note_suffix(args.note),
    )


async def _list(args: argparse.Namespace) -> None:
    result = await list_versions(Path(args.path), args.version)
    for listing in result.listings:
        print(f"{listing.number}: {listing.identifier}{_note_suffix(listing.note)}")


async def _clone(args: argparse.Namespace) -> None:
    result = await clone(Path(args.path), Path(args.target), args.version)
    span = (
        f"versions {result.first}..{result.last}"
        if result.first != result.last
        else f"version {result.first}"
    )
    LOGGER.info(
        "cloned %s from %s to %s via %s",
        span,
        args.path,
        args.target,
        result.account.url,
    )


async def _forget(args: argparse.Namespace) -> None:
    result = await forget(Path(args.path), args.version, forget_all=args.forget_all)
    target = (
        f"version {result.version}" if result.version is not None else "all versions"
    )
    for account in result.accounts:
        LOGGER.info("%s %s: forgot %s", account.url, account.user_id, target)


type CommandHandler = Callable[[argparse.Namespace], Awaitable[None]]

_COMMANDS: dict[str, CommandHandler] = {
    "archive/register": _register,
    "archive/unregister": _unregister,
    "archive/workspaces": _workspaces,
    "archive/clone": _archive_clone,
    "workspace/login": _login,
    "workspace/logout": _logout,
    "workspace/save": _save,
    "workspace/list": _list,
    "workspace/clone": _clone,
    "workspace/forget": _forget,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ev", description="EasyVersion: content-hashed workspace archives."
    )
    parser.add_argument(
        "--verbose",
        "-V",
        dest="verbose",
        action="count",
        default=0,
        help="Increase log verbosity (repeatable).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive_parser = subparsers.add_parser("archive", help="Manage archive accounts.")
    archive_parser.add_argument("url", help="Archive URL.")
    archive_subparsers = archive_parser.add_subparsers(dest="action", required=True)
    register_parser = archive_subparsers.add_parser(
        "register", help="Claim a user ID; client-generated when omitted."
    )
    register_parser.add_argument("user", nargs="?", default=None, help="User ID.")
    unregister_parser = archive_subparsers.add_parser(
        "unregister", help="Forget the user on the archive."
    )
    unregister_parser.add_argument("user", help="User ID.")

    workspaces_parser = archive_subparsers.add_parser(
        "workspaces", help="List workspaces for a user on the archive."
    )
    workspaces_parser.add_argument("user", help="User ID.")

    archive_clone_parser = archive_subparsers.add_parser(
        "clone", help="Clone a workspace from the archive."
    )
    archive_clone_parser.add_argument("user", help="User ID.")
    archive_clone_parser.add_argument("workspace", help="Workspace ID.")
    archive_clone_parser.add_argument("target", help="Target path, may not exist.")
    archive_clone_parser.add_argument(
        "--version", "-v", dest="version", type=int, default=None, help="Version."
    )

    workspace_parser = subparsers.add_parser("workspace", help="Manage workspaces.")
    workspace_parser.add_argument("path", help="Workspace path.")
    workspace_subparsers = workspace_parser.add_subparsers(dest="action", required=True)

    login_parser = workspace_subparsers.add_parser(
        "login", help="Activate an archive account."
    )
    login_parser.add_argument("archive", help="Archive URL.")
    login_parser.add_argument("user", help="User ID.")

    logout_parser = workspace_subparsers.add_parser(
        "logout", help="Deactivate an archive account."
    )
    logout_parser.add_argument("archive", help="Archive URL.")
    logout_parser.add_argument("user", help="User ID.")

    save_parser = workspace_subparsers.add_parser(
        "save", help="Save the current state as a version."
    )
    save_parser.add_argument(
        "--note", "-n", dest="note", default=None, help="Version note."
    )

    list_parser = workspace_subparsers.add_parser("list", help="List versions.")
    list_parser.add_argument(
        "--version", "-v", dest="version", type=int, default=None, help="Version."
    )

    clone_parser = workspace_subparsers.add_parser("clone", help="Clone a workspace.")
    clone_parser.add_argument("target", help="Target path, may not exist.")
    clone_parser.add_argument(
        "--version", "-v", dest="version", type=int, default=None, help="Version."
    )

    forget_parser = workspace_subparsers.add_parser(
        "forget", help="Forget versions on every archive."
    )
    forget_group = forget_parser.add_mutually_exclusive_group(required=True)
    forget_group.add_argument(
        "--version", "-v", dest="version", type=int, default=None, help="Version."
    )
    forget_group.add_argument(
        "--all", "-a", dest="forget_all", action="store_true", help="All versions."
    )

    complete_parser = subparsers.add_parser(
        "complete", help="Print shell completion suggestions."
    )
    complete_parser.add_argument(
        "line", nargs="?", default="", help="Current command line."
    )

    return parser


def _log_level(verbosity: int) -> LogLevel:
    return (LogLevel.WARNING, LogLevel.INFORMATION, LogLevel.DEBUGGING)[
        min(verbosity, 2)
    ]


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "complete":
        _complete(args.line)
        return
    Logger(_log_level(args.verbose)).configure()
    key = f"{args.command}/{args.action}"
    try:
        asyncio.run(_COMMANDS[key](args))
    except EvError as error:
        LOGGER.error("%s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
