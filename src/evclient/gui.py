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


class Application:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EasyVersion")
        self.root.minsize(640, 440)

        self.workspace_variable = tk.StringVar(value=str(Path.cwd()))
        self.archive_variable = tk.StringVar()
        self.user_variable = tk.StringVar()
        self.note_variable = tk.StringVar()
        self.status_variable = tk.StringVar(value="Ready")
        self._versions: list[int] = []

        self._build_widgets()

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(frame, text="Workspace").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=self.workspace_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=6, pady=4
        )
        ttk.Button(frame, text="Browse...", command=self._choose_workspace).grid(
            row=0, column=2, sticky=tk.E, pady=4
        )

        account_frame = ttk.LabelFrame(frame, text="Archive Account", padding=8)
        account_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=6)
        account_frame.columnconfigure(1, weight=1)
        account_frame.columnconfigure(3, weight=1)

        ttk.Label(account_frame, text="URL").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(account_frame, textvariable=self.archive_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=(6, 12)
        )
        ttk.Label(account_frame, text="User").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(account_frame, textvariable=self.user_variable).grid(
            row=0, column=3, sticky=tk.EW, padx=6
        )

        account_buttons = ttk.Frame(account_frame)
        account_buttons.grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        ttk.Button(account_buttons, text="Register", command=self._register).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(account_buttons, text="Unregister", command=self._unregister).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(account_buttons, text="Login", command=self._login).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(account_buttons, text="Logout", command=self._logout).pack(
            side=tk.LEFT
        )

        action_frame = ttk.Frame(frame)
        action_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=6)
        action_frame.columnconfigure(1, weight=1)

        ttk.Label(action_frame, text="Note").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(action_frame, textvariable=self.note_variable).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(action_frame, text="Save", command=self._save).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(action_frame, text="Refresh", command=self._refresh).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(action_frame, text="Clone...", command=self._clone).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(
            action_frame, text="Forget Selected", command=self._forget_selected
        ).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(action_frame, text="Forget All", command=self._forget_all).grid(
            row=0, column=6
        )

        self.version_listbox = tk.Listbox(frame, exportselection=False)
        self.version_listbox.grid(row=3, column=0, columnspan=3, sticky=tk.NSEW, pady=6)

        ttk.Label(frame, textvariable=self.status_variable).grid(
            row=4, column=0, columnspan=3, sticky=tk.W
        )

    def _workspace_path(self) -> Path:
        raw = self.workspace_variable.get().strip()
        if not raw:
            message = "workspace path is required"
            raise EvError(message)
        return Path(raw)

    def _archive_url(self) -> str:
        raw = self.archive_variable.get().strip()
        if not raw:
            message = "archive URL is required"
            raise EvError(message)
        return raw

    def _user_id(self) -> UserId:
        raw = self.user_variable.get().strip()
        if not raw:
            message = "user ID is required"
            raise EvError(message)
        return raw

    def _selected_version(self) -> int | None:
        selection = self.version_listbox.curselection()
        if not selection:
            return None
        return self._versions[selection[0]]

    def _choose_workspace(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.workspace_variable.get())
        if chosen:
            self.workspace_variable.set(chosen)

    def _run_async[T](
        self,
        coroutine_factory: Callable[[], Coroutine[object, object, T]],
        on_success: Callable[[T], None],
    ) -> None:
        self.status_variable.set("Working...")

        def worker() -> None:
            try:
                result = asyncio.run(coroutine_factory())
            except EvError as error:
                self.root.after(0, self._handle_error, error)
            else:
                self.root.after(0, on_success, result)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_error(self, error: EvError) -> None:
        self.status_variable.set(str(error))
        messagebox.showerror("EasyVersion", str(error))

    def _register(self) -> None:
        try:
            url = self._archive_url()
        except EvError as error:
            self._handle_error(error)
            return
        raw_user = self.user_variable.get().strip()
        user_id = raw_user or None

        def on_done(created_id: UserId) -> None:
            self.user_variable.set(created_id)
            self.status_variable.set(f"Registered user {created_id}")

        self._run_async(lambda: register(url, user_id), on_done)

    def _unregister(self) -> None:
        try:
            url = self._archive_url()
            user_id = self._user_id()
        except EvError as error:
            self._handle_error(error)
            return

        def on_done(_: None) -> None:
            self.status_variable.set(f"Unregistered user {user_id}")

        self._run_async(lambda: unregister(url, user_id), on_done)

    def _login(self) -> None:
        try:
            account = login(
                self._workspace_path(), self._archive_url(), self._user_id()
            )
        except EvError as error:
            self._handle_error(error)
            return
        self.status_variable.set(f"Logged in {account.url} ({account.user_id})")

    def _logout(self) -> None:
        try:
            removed = logout(
                self._workspace_path(), self._archive_url(), self._user_id()
            )
        except EvError as error:
            self._handle_error(error)
            return
        self.status_variable.set("Logged out" if removed else "Account was not active")

    def _save(self) -> None:
        try:
            workspace_path = self._workspace_path()
        except EvError as error:
            self._handle_error(error)
            return
        note = self.note_variable.get().strip() or None

        def on_done(result: SaveResult) -> None:
            self.note_variable.set("")
            self.status_variable.set(
                f"Saved version {result.version} to {result.account.url}"
            )
            self._refresh()

        self._run_async(lambda: save(workspace_path, note), on_done)

    def _refresh(self) -> None:
        try:
            workspace_path = self._workspace_path()
        except EvError as error:
            self._handle_error(error)
            return

        def on_done(result: ListResult) -> None:
            self.version_listbox.delete(0, tk.END)
            self._versions = []
            for listing in result.listings:
                suffix = f" -- {listing.note}" if listing.note else ""
                self.version_listbox.insert(
                    tk.END, f"{listing.number}: {listing.identifier}{suffix}"
                )
                self._versions.append(listing.number)
            self.status_variable.set(
                f"Loaded {len(result.listings)} version(s) from {result.account.url}"
            )

        self._run_async(lambda: list_versions(workspace_path), on_done)

    def _clone(self) -> None:
        try:
            source_path = self._workspace_path()
        except EvError as error:
            self._handle_error(error)
            return
        parent = filedialog.askdirectory(title="Select parent folder for clone")
        if not parent:
            return
        target_path = Path(parent) / f"{source_path.name}-clone"
        version = self._selected_version()

        def on_done(result: CloneResult) -> None:
            self.status_variable.set(
                f"Cloned {result.first}..{result.last} to {target_path}"
            )

        self._run_async(lambda: clone(source_path, target_path, version), on_done)

    def _forget_selected(self) -> None:
        version = self._selected_version()
        if version is None:
            self._handle_error(EvError("select a version first"))
            return
        try:
            workspace_path = self._workspace_path()
        except EvError as error:
            self._handle_error(error)
            return

        def on_done(result: ForgetResult) -> None:
            self.status_variable.set(
                f"Forgot version {result.version} on {len(result.accounts)} archive(s)"
            )
            self._refresh()

        self._run_async(
            lambda: forget(workspace_path, version=version, forget_all=False), on_done
        )

    def _forget_all(self) -> None:
        try:
            workspace_path = self._workspace_path()
        except EvError as error:
            self._handle_error(error)
            return

        def on_done(result: ForgetResult) -> None:
            self.version_listbox.delete(0, tk.END)
            self._versions = []
            self.status_variable.set(
                f"Forgot all versions on {len(result.accounts)} archive(s)"
            )

        self._run_async(lambda: forget(workspace_path, forget_all=True), on_done)


def main() -> None:
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
