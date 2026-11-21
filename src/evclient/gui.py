import asyncio
import threading
import tkinter as tk
from collections.abc import Callable, Coroutine
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from evclient.commands import (
    CloneResult,
    ForgetResult,
    ListResult,
    SaveResult,
    VersionListing,
    clone,
    forget,
    list_versions,
    login,
    logout,
    register,
    save,
    unregister,
)
from evclient.types import EvError, UserId


def _require_non_empty(variable: tk.StringVar, field_name: str) -> str:
    value = variable.get().strip()
    if not value:
        message = f"{field_name} is required"
        raise EvError(message)
    return value


class AsyncRunner:
    def __init__(
        self,
        root: tk.Tk,
        on_start: Callable[[], None],
        on_error: Callable[[EvError], None],
    ) -> None:
        self._root = root
        self._on_start = on_start
        self._on_error = on_error

    def run[T](
        self,
        coroutine_factory: Callable[[], Coroutine[object, object, T]],
        on_success: Callable[[T], None],
    ) -> None:
        self._on_start()

        def worker() -> None:
            try:
                result = asyncio.run(coroutine_factory())
            except EvError as error:
                self._root.after(0, self._on_error, error)
            else:
                self._root.after(0, on_success, result)

        threading.Thread(target=worker, daemon=True).start()


class WorkspaceBar(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.columnconfigure(1, weight=1)
        self._path_variable = tk.StringVar(value=str(Path.cwd()))

        ttk.Label(self, text="Workspace").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(self, textvariable=self._path_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=6, pady=4
        )
        ttk.Button(self, text="Browse...", command=self._browse).grid(
            row=0, column=2, sticky=tk.E, pady=4
        )

    def path(self) -> Path:
        return Path(_require_non_empty(self._path_variable, "workspace path"))

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self._path_variable.get())
        if chosen:
            self._path_variable.set(chosen)


class AccountPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_register: Callable[[], None],
        on_unregister: Callable[[], None],
        on_login: Callable[[], None],
        on_logout: Callable[[], None],
    ) -> None:
        super().__init__(master, text="Archive Account", padding=8)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(3, weight=1)
        self._url_variable = tk.StringVar()
        self._user_variable = tk.StringVar()

        ttk.Label(self, text="URL").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(self, textvariable=self._url_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=(6, 12)
        )
        ttk.Label(self, text="User").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(self, textvariable=self._user_variable).grid(
            row=0, column=3, sticky=tk.EW, padx=6
        )

        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        ttk.Button(buttons, text="Register", command=on_register).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Unregister", command=on_unregister).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Login", command=on_login).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Logout", command=on_logout).pack(side=tk.LEFT)

    def url(self) -> str:
        return _require_non_empty(self._url_variable, "archive URL")

    def user_id(self) -> UserId:
        return _require_non_empty(self._user_variable, "user ID")

    def optional_user_id(self) -> UserId | None:
        return self._user_variable.get().strip() or None

    def set_user_id(self, user_id: UserId) -> None:
        self._user_variable.set(user_id)


class VersionPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        on_save: Callable[[], None],
        on_refresh: Callable[[], None],
        on_clone: Callable[[], None],
        on_forget_selected: Callable[[], None],
        on_forget_all: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._note_variable = tk.StringVar()
        self._versions: list[int] = []

        actions = ttk.Frame(self)
        actions.grid(row=0, column=0, sticky=tk.EW, pady=(0, 6))
        actions.columnconfigure(1, weight=1)

        ttk.Label(actions, text="Note").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(actions, textvariable=self._note_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(actions, text="Save", command=on_save).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(actions, text="Refresh", command=on_refresh).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(actions, text="Clone...", command=on_clone).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(actions, text="Forget Selected", command=on_forget_selected).grid(
            row=0, column=5, padx=(0, 6)
        )
        ttk.Button(actions, text="Forget All", command=on_forget_all).grid(
            row=0, column=6
        )

        self._listbox = tk.Listbox(self, exportselection=False)
        self._listbox.grid(row=1, column=0, sticky=tk.NSEW)

    def note(self) -> str | None:
        return self._note_variable.get().strip() or None

    def clear_note(self) -> None:
        self._note_variable.set("")

    def selected_version(self) -> int | None:
        selection = self._listbox.curselection()
        if not selection:
            return None
        return self._versions[selection[0]]

    def set_listings(self, listings: tuple[VersionListing, ...]) -> None:
        self.clear()
        for listing in listings:
            suffix = f" -- {listing.note}" if listing.note else ""
            self._listbox.insert(
                tk.END, f"{listing.number}: {listing.identifier}{suffix}"
            )
            self._versions.append(listing.number)

    def clear(self) -> None:
        self._listbox.delete(0, tk.END)
        self._versions = []


class Application:
    def __init__(self, root: tk.Tk) -> None:
        root.title("EasyVersion")
        root.minsize(640, 440)

        self._status_variable = tk.StringVar(value="Ready")
        self._runner = AsyncRunner(
            root,
            on_start=lambda: self._status_variable.set("Working..."),
            on_error=self._show_error,
        )

        container = ttk.Frame(root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        self._workspace_bar = WorkspaceBar(container)
        self._workspace_bar.grid(row=0, column=0, sticky=tk.EW)

        self._account_panel = AccountPanel(
            container,
            on_register=self._register,
            on_unregister=self._unregister,
            on_login=self._login,
            on_logout=self._logout,
        )
        self._account_panel.grid(row=1, column=0, sticky=tk.EW, pady=6)

        self._version_panel = VersionPanel(
            container,
            on_save=self._save,
            on_refresh=self._refresh,
            on_clone=self._clone,
            on_forget_selected=self._forget_selected,
            on_forget_all=self._forget_all,
        )
        self._version_panel.grid(row=2, column=0, sticky=tk.NSEW, pady=6)

        ttk.Label(container, textvariable=self._status_variable).grid(
            row=3, column=0, sticky=tk.W
        )

    def _show_error(self, error: EvError) -> None:
        self._status_variable.set(str(error))
        messagebox.showerror("EasyVersion", str(error))

    def _register(self) -> None:
        try:
            url = self._account_panel.url()
        except EvError as error:
            self._show_error(error)
            return
        user_id = self._account_panel.optional_user_id()

        def on_done(created_id: UserId) -> None:
            self._account_panel.set_user_id(created_id)
            self._status_variable.set(f"Registered user {created_id}")

        self._runner.run(lambda: register(url, user_id), on_done)

    def _unregister(self) -> None:
        try:
            url = self._account_panel.url()
            user_id = self._account_panel.user_id()
        except EvError as error:
            self._show_error(error)
            return

        self._runner.run(
            lambda: unregister(url, user_id),
            lambda _: self._status_variable.set(f"Unregistered user {user_id}"),
        )

    def _login(self) -> None:
        try:
            account = login(
                self._workspace_bar.path(),
                self._account_panel.url(),
                self._account_panel.user_id(),
            )
        except EvError as error:
            self._show_error(error)
            return
        self._status_variable.set(f"Logged in {account.url} ({account.user_id})")

    def _logout(self) -> None:
        try:
            removed = logout(
                self._workspace_bar.path(),
                self._account_panel.url(),
                self._account_panel.user_id(),
            )
        except EvError as error:
            self._show_error(error)
            return
        self._status_variable.set("Logged out" if removed else "Account was not active")

    def _save(self) -> None:
        try:
            workspace_path = self._workspace_bar.path()
        except EvError as error:
            self._show_error(error)
            return
        note = self._version_panel.note()

        def on_done(result: SaveResult) -> None:
            self._version_panel.clear_note()
            self._status_variable.set(
                f"Saved version {result.version} to {result.account.url}"
            )
            self._refresh()

        self._runner.run(lambda: save(workspace_path, note), on_done)

    def _refresh(self) -> None:
        try:
            workspace_path = self._workspace_bar.path()
        except EvError as error:
            self._show_error(error)
            return

        def on_done(result: ListResult) -> None:
            self._version_panel.set_listings(result.listings)
            self._status_variable.set(
                f"Loaded {len(result.listings)} version(s) from {result.account.url}"
            )

        self._runner.run(lambda: list_versions(workspace_path), on_done)

    def _clone(self) -> None:
        try:
            source_path = self._workspace_bar.path()
        except EvError as error:
            self._show_error(error)
            return
        parent = filedialog.askdirectory(title="Select parent folder for clone")
        if not parent:
            return
        target_path = Path(parent) / f"{source_path.name}-clone"
        version = self._version_panel.selected_version()

        def on_done(result: CloneResult) -> None:
            self._status_variable.set(
                f"Cloned {result.first}..{result.last} to {target_path}"
            )

        self._runner.run(lambda: clone(source_path, target_path, version), on_done)

    def _forget_selected(self) -> None:
        version = self._version_panel.selected_version()
        if version is None:
            self._show_error(EvError("select a version first"))
            return
        try:
            workspace_path = self._workspace_bar.path()
        except EvError as error:
            self._show_error(error)
            return

        def on_done(result: ForgetResult) -> None:
            self._status_variable.set(
                f"Forgot version {result.version} on {len(result.accounts)} archive(s)"
            )
            self._refresh()

        self._runner.run(
            lambda: forget(workspace_path, version=version, forget_all=False), on_done
        )

    def _forget_all(self) -> None:
        try:
            workspace_path = self._workspace_bar.path()
        except EvError as error:
            self._show_error(error)
            return

        def on_done(result: ForgetResult) -> None:
            self._version_panel.clear()
            self._status_variable.set(
                f"Forgot all versions on {len(result.accounts)} archive(s)"
            )

        self._runner.run(lambda: forget(workspace_path, forget_all=True), on_done)


def main() -> None:
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
