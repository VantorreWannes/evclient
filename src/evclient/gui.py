import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path

from pydantic import TypeAdapter
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from evclient.commands import (
    CloneResult,
    ForgetResult,
    ListResult,
    SaveResult,
    VersionListing,
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
from evclient.types import EvError, UserId, WorkspaceId
from evclient.workspace import Account, Workspace

DEFAULT_ARCHIVE_URL = "https://easyversionarchive.com"
REGISTRY_PATH = Path.home() / ".ev" / "gui_workspaces.json"
ACCOUNTS_REGISTRY_PATH = Path.home() / ".ev" / "gui_accounts.json"

STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #16181d;
    color: #e5e7eb;
}
QListWidget, QTableWidget {
    background-color: #1e222a;
    color: #e5e7eb;
    border: 1px solid #2d3340;
    border-radius: 6px;
    outline: none;
    gridline-color: #262b36;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #2563eb;
    color: #ffffff;
}
QLineEdit, QComboBox {
    background-color: #1e222a;
    color: #e5e7eb;
    border: 1px solid #323947;
    border-radius: 6px;
    padding: 6px 10px;
}
QLineEdit:focus {
    border-color: #3b82f6;
}
QPushButton {
    background-color: #232833;
    color: #e5e7eb;
    border: 1px solid #353c4b;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #2d3442;
}
QPushButton:disabled {
    color: #6b7280;
    background-color: #1b1e25;
    border-color: #262b35;
}
QPushButton#primary {
    background-color: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primary:hover {
    background-color: #1d4ed8;
}
QPushButton#danger {
    color: #f87171;
    border-color: #5c2b2e;
    background-color: #261c1e;
}
QPushButton#danger:hover {
    background-color: #3b2326;
}
QPushButton#danger:disabled {
    color: #6b7280;
    background-color: #1b1e25;
    border-color: #262b35;
}
QTabWidget::pane {
    border: 1px solid #2d3340;
    border-radius: 6px;
    background-color: #1a1d24;
    padding: 8px;
}
QTabBar::tab {
    background-color: #1e222a;
    color: #9ca3af;
    border: 1px solid #2d3340;
    border-bottom: none;
    padding: 6px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #1a1d24;
    color: #f3f4f6;
    font-weight: 600;
}
QHeaderView::section {
    background-color: #232833;
    color: #cbd5e1;
    border: none;
    border-bottom: 1px solid #2d3340;
    padding: 6px 8px;
    font-weight: 600;
}
QStatusBar {
    background-color: #16181d;
    color: #9ca3af;
}
"""


class WorkspaceRegistry:
    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self._path = path

    def load(self) -> list[Path]:
        if not self._path.exists():
            return []
        try:
            raw = TypeAdapter(list[str]).validate_json(self._path.read_bytes())
        except OSError, ValueError:
            return []
        return [Path(item) for item in raw if Path(item).exists()]

    def save(self, paths: list[Path]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = TypeAdapter(list[str]).dump_json([str(path) for path in paths])
        self._path.write_bytes(encoded)


class AccountRegistry:
    def __init__(self, path: Path = ACCOUNTS_REGISTRY_PATH) -> None:
        self._path = path

    def load(self) -> list[Account]:
        if not self._path.exists():
            return []
        try:
            return TypeAdapter(list[Account]).validate_json(self._path.read_bytes())
        except OSError, ValueError:
            return []

    def save(self, accounts: list[Account]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = TypeAdapter(list[Account]).dump_json(accounts)
        self._path.write_bytes(encoded)

    def remember(self, account: Account) -> None:
        accounts = self.load()
        if account not in accounts:
            accounts.append(account)
            self.save(accounts)

    def forget(self, account: Account) -> None:
        accounts = self.load()
        if account in accounts:
            accounts.remove(account)
            self.save(accounts)


class _WorkerThread(QThread):
    def __init__(
        self,
        coroutine_factory: Callable[[], Coroutine[object, object, object]],
        on_succeeded: Callable[[object], None],
        on_failed: Callable[[EvError], None],
    ) -> None:
        super().__init__()
        self._coroutine_factory = coroutine_factory
        self._on_succeeded = on_succeeded
        self._on_failed = on_failed

    def run(self) -> None:
        try:
            result = asyncio.run(self._coroutine_factory())
        except EvError as error:
            self._on_failed(error)
        else:
            self._on_succeeded(result)


class AsyncRunner(QObject):
    _deliver_success = Signal(object, object)
    _deliver_error = Signal(object, object)

    def __init__(
        self,
        parent: QObject,
        on_start: Callable[[], None],
        on_error: Callable[[EvError], None],
    ) -> None:
        super().__init__(parent)
        self._on_start = on_start
        self._on_error = on_error
        self._threads: list[_WorkerThread] = []
        self._deliver_success.connect(
            self._handle_success, Qt.ConnectionType.QueuedConnection
        )
        self._deliver_error.connect(
            self._handle_error, Qt.ConnectionType.QueuedConnection
        )

    @Slot(object, object)
    def _handle_success(
        self, callback: Callable[[object], None], result: object
    ) -> None:
        callback(result)

    @Slot(object, object)
    def _handle_error(
        self, callback: Callable[[EvError], None], error: EvError
    ) -> None:
        callback(error)

    def run[T](
        self,
        coroutine_factory: Callable[[], Coroutine[object, object, T]],
        on_success: Callable[[T], None],
        *,
        on_error: Callable[[EvError], None] | None = None,
    ) -> None:
        self._on_start()
        error_handler = on_error or self._on_error
        worker = _WorkerThread(
            coroutine_factory,
            lambda result: self._deliver_success.emit(on_success, result),
            lambda error: self._deliver_error.emit(error_handler, error),
        )
        self._threads.append(worker)

        worker.finished.connect(
            lambda: self._cleanup(worker), Qt.ConnectionType.QueuedConnection
        )
        worker.start()

    def _cleanup(self, worker: _WorkerThread) -> None:
        if worker in self._threads:
            self._threads.remove(worker)
        worker.deleteLater()


class WorkspaceSidebar(QWidget):
    workspace_selected = Signal(object)
    clone_remote_requested = Signal()

    def __init__(self, registry: WorkspaceRegistry) -> None:
        super().__init__()
        self._registry = registry
        self._paths: list[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)

        title = QLabel("Workspaces")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("+ Add")
        add_button.clicked.connect(self._add_folder)
        remove_button = QPushButton("- Remove")
        remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        layout.addLayout(buttons)

        clone_remote_button = QPushButton("Clone from Archive...")
        clone_remote_button.clicked.connect(self.clone_remote_requested.emit)
        layout.addWidget(clone_remote_button)

        self._load_initial()

    def current_path(self) -> Path | None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._paths):
            return None
        return self._paths[row]

    def add_workspace(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved not in self._paths:
            self._paths.append(resolved)
            self._registry.save(self._paths)
            self._append_item(resolved)
        self._list.setCurrentRow(self._paths.index(resolved))

    def _load_initial(self) -> None:
        saved = self._registry.load()
        if not saved:
            saved = [Path.cwd()]
        self._paths = saved
        for path in self._paths:
            self._append_item(path)
        self._registry.save(self._paths)
        if self._paths:
            self._list.setCurrentRow(0)

    def _append_item(self, path: Path) -> None:
        item = QListWidgetItem(path.name or str(path))
        item.setToolTip(str(path))
        self._list.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._paths):
            self.workspace_selected.emit(self._paths[row])
        else:
            self.workspace_selected.emit(None)

    def _add_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Workspace Folder", str(Path.cwd())
        )
        if chosen:
            self.add_workspace(Path(chosen))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._paths):
            return
        self._paths.pop(row)
        self._list.takeItem(row)
        self._registry.save(self._paths)


class AccountDialog(QDialog):
    def __init__(self, parent: QWidget, known_accounts: list[Account]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Archive Account")
        self.setMinimumWidth(440)
        self.mode: str = "login"
        self._known_accounts = known_accounts

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._url_input = QLineEdit(DEFAULT_ARCHIVE_URL)
        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("Leave blank to generate on Register")

        if self._known_accounts:
            self._saved_combo = QComboBox()
            self._saved_combo.addItem("New account...")
            for account in self._known_accounts:
                self._saved_combo.addItem(f"{account.user_id} @ {account.url}")
            self._saved_combo.currentIndexChanged.connect(self._on_saved_selected)
            form.addRow("Saved Account", self._saved_combo)

        form.addRow("Archive URL", self._url_input)
        form.addRow("User ID", self._user_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        login_button = QPushButton("Login")
        login_button.clicked.connect(lambda: self._accept_mode("login"))
        register_button = QPushButton("Register && Login")
        register_button.setObjectName("primary")
        register_button.clicked.connect(lambda: self._accept_mode("register"))
        buttons.addWidget(cancel_button)
        buttons.addWidget(login_button)
        buttons.addWidget(register_button)
        layout.addLayout(buttons)

        if self._known_accounts:
            self._saved_combo.setCurrentIndex(1)

    def _on_saved_selected(self, index: int) -> None:
        if index <= 0:
            self._url_input.setText(DEFAULT_ARCHIVE_URL)
            self._user_input.clear()
            return
        account = self._known_accounts[index - 1]
        self._url_input.setText(account.url)
        self._user_input.setText(account.user_id)

    def url(self) -> str:
        return self._url_input.text().strip()

    def user_id(self) -> UserId:
        return self._user_input.text().strip()

    def _accept_mode(self, mode: str) -> None:
        if not self.url():
            QMessageBox.warning(self, "EasyVersion", "Archive URL is required.")
            return
        if mode == "login" and not self.user_id():
            QMessageBox.warning(self, "EasyVersion", "User ID is required for Login.")
            return
        self.mode = mode
        self.accept()


class CloneRemoteDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        known_accounts: list[Account],
        runner: AsyncRunner,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone from Archive")
        self.setMinimumWidth(480)
        self._known_accounts = known_accounts
        self._runner = runner

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._url_input = QLineEdit(DEFAULT_ARCHIVE_URL)
        self._user_input = QLineEdit()

        if self._known_accounts:
            self._saved_combo = QComboBox()
            self._saved_combo.addItem("Custom account...")
            for account in self._known_accounts:
                self._saved_combo.addItem(f"{account.user_id} @ {account.url}")
            self._saved_combo.currentIndexChanged.connect(self._on_saved_selected)
            form.addRow("Saved Account", self._saved_combo)

        form.addRow("Archive URL", self._url_input)
        form.addRow("User ID", self._user_input)

        workspace_row = QHBoxLayout()
        self._workspace_combo = QComboBox()
        self._workspace_combo.setEditable(True)
        fetch_button = QPushButton("Fetch")
        fetch_button.clicked.connect(self._fetch_workspaces)
        workspace_row.addWidget(self._workspace_combo, 1)
        workspace_row.addWidget(fetch_button)
        form.addRow("Workspace ID", workspace_row)

        self._version_input = QLineEdit()
        self._version_input.setPlaceholderText("Latest (or version number)")
        form.addRow("Version", self._version_input)

        target_row = QHBoxLayout()
        self._target_input = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_target)
        target_row.addWidget(self._target_input, 1)
        target_row.addWidget(browse_button)
        form.addRow("Target Folder", target_row)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        clone_button = QPushButton("Clone")
        clone_button.setObjectName("primary")
        clone_button.clicked.connect(self._on_accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(clone_button)
        layout.addLayout(buttons)

        if self._known_accounts:
            self._saved_combo.setCurrentIndex(1)

    def url(self) -> str:
        return self._url_input.text().strip()

    def user_id(self) -> UserId:
        return self._user_input.text().strip()

    def workspace_id(self) -> WorkspaceId:
        return self._workspace_combo.currentText().strip()

    def target_path(self) -> Path:
        return Path(self._target_input.text().strip())

    def version(self) -> int | None:
        raw = self._version_input.text().strip()
        if not raw:
            return None
        return int(raw)

    def _on_saved_selected(self, index: int) -> None:
        if index <= 0:
            self._url_input.setText(DEFAULT_ARCHIVE_URL)
            self._user_input.clear()
            return
        account = self._known_accounts[index - 1]
        self._url_input.setText(account.url)
        self._user_input.setText(account.user_id)

    def _fetch_workspaces(self) -> None:
        url = self.url()
        user_id = self.user_id()
        if not url or not user_id:
            QMessageBox.warning(
                self, "EasyVersion", "Archive URL and User ID are required."
            )
            return

        def on_loaded(workspace_ids: tuple[WorkspaceId, ...]) -> None:
            self._workspace_combo.clear()
            self._workspace_combo.addItems(list(workspace_ids))
            if not workspace_ids:
                QMessageBox.information(
                    self, "EasyVersion", "No workspaces found for this user."
                )

        def on_error(error: EvError) -> None:
            QMessageBox.critical(self, "EasyVersion", str(error))

        self._runner.run(
            lambda: list_remote_workspaces(url, user_id),
            on_loaded,
            on_error=on_error,
        )

    def _browse_target(self) -> None:
        suggested = self.workspace_id() or "cloned-workspace"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Clone Workspace As",
            str(Path.cwd() / suggested),
        )
        if target:
            self._target_input.setText(target)

    def _on_accept(self) -> None:
        if (
            not self.url()
            or not self.user_id()
            or not self.workspace_id()
            or not self._target_input.text().strip()
        ):
            QMessageBox.warning(
                self,
                "EasyVersion",
                "URL, User ID, Workspace ID, and Target Folder are required.",
            )
            return
        raw_version = self._version_input.text().strip()
        if raw_version:
            try:
                if int(raw_version) < 1:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(
                    self, "EasyVersion", "Version must be a positive integer."
                )
                return
        self.accept()


class VersionsTab(QWidget):
    save_requested = Signal(object)
    refresh_requested = Signal()
    clone_requested = Signal(object)
    forget_requested = Signal(int)
    forget_all_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._versions: list[int] = []

        layout = QVBoxLayout(self)
        top_bar = QHBoxLayout()
        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText("Version note (optional)...")
        self._note_input.returnPressed.connect(self._emit_save)
        save_button = QPushButton("Save Version")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._emit_save)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        top_bar.addWidget(self._note_input, 1)
        top_bar.addWidget(save_button)
        top_bar.addWidget(refresh_button)
        layout.addLayout(top_bar)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["#", "Note", "Snapshot"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table, 1)

        bottom_bar = QHBoxLayout()
        self._clone_button = QPushButton("Clone Latest...")
        self._clone_button.clicked.connect(
            lambda: self.clone_requested.emit(self.selected_version())
        )
        self._forget_button = QPushButton("Forget Selected")
        self._forget_button.setObjectName("danger")
        self._forget_button.clicked.connect(self._emit_forget)
        self._forget_all_button = QPushButton("Forget All")
        self._forget_all_button.setObjectName("danger")
        self._forget_all_button.clicked.connect(self.forget_all_requested.emit)
        bottom_bar.addWidget(self._clone_button)
        bottom_bar.addStretch(1)
        bottom_bar.addWidget(self._forget_button)
        bottom_bar.addWidget(self._forget_all_button)
        layout.addLayout(bottom_bar)
        self._update_buttons()

    def selected_version(self) -> int | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._versions):
            return None
        return self._versions[row]

    def set_listings(self, listings: tuple[VersionListing, ...]) -> None:
        self.clear()
        ordered = list(reversed(listings))
        self._table.setRowCount(len(ordered))
        for row, listing in enumerate(ordered):
            number_item = QTableWidgetItem(str(listing.number))
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, number_item)
            self._table.setItem(row, 1, QTableWidgetItem(listing.note or ""))
            self._table.setItem(row, 2, QTableWidgetItem(listing.identifier[:16]))
            self._versions.append(listing.number)
        self._update_buttons()

    def clear_note(self) -> None:
        self._note_input.clear()

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._versions = []
        self._update_buttons()

    def _emit_save(self) -> None:
        note = self._note_input.text().strip() or None
        self.save_requested.emit(note)

    def _emit_forget(self) -> None:
        version = self.selected_version()
        if version is not None:
            self.forget_requested.emit(version)

    def _update_buttons(self) -> None:
        selected = self.selected_version()
        has_versions = bool(self._versions)
        self._clone_button.setEnabled(has_versions)
        self._clone_button.setText(
            f"Clone v{selected}..." if selected is not None else "Clone Latest..."
        )
        self._forget_button.setEnabled(selected is not None)
        self._forget_all_button.setEnabled(has_versions)


class ArchivesTab(QWidget):
    add_requested = Signal()
    logout_requested = Signal(object)
    unregister_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._accounts: list[Account] = []

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Archive URL", "User ID"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("+ Add Archive...")
        add_button.setObjectName("primary")
        add_button.clicked.connect(self.add_requested.emit)
        self._logout_button = QPushButton("Logout")
        self._logout_button.clicked.connect(self._emit_logout)
        self._unregister_button = QPushButton("Unregister")
        self._unregister_button.setObjectName("danger")
        self._unregister_button.clicked.connect(self._emit_unregister)
        buttons.addWidget(add_button)
        buttons.addStretch(1)
        buttons.addWidget(self._logout_button)
        buttons.addWidget(self._unregister_button)
        layout.addLayout(buttons)
        self._update_buttons()

    def set_accounts(self, accounts: list[Account]) -> None:
        self._accounts = list(accounts)
        self._table.setRowCount(len(self._accounts))
        for row, account in enumerate(self._accounts):
            self._table.setItem(row, 0, QTableWidgetItem(account.url))
            self._table.setItem(row, 1, QTableWidgetItem(account.user_id))
        self._update_buttons()

    def _selected_account(self) -> Account | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._accounts):
            return None
        return self._accounts[row]

    def _emit_logout(self) -> None:
        account = self._selected_account()
        if account is not None:
            self.logout_requested.emit(account)

    def _emit_unregister(self) -> None:
        account = self._selected_account()
        if account is not None:
            self.unregister_requested.emit(account)

    def _update_buttons(self) -> None:
        has_selection = self._selected_account() is not None
        self._logout_button.setEnabled(has_selection)
        self._unregister_button.setEnabled(has_selection)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EasyVersion")
        self.resize(920, 580)
        self._account_registry = AccountRegistry()

        self._runner = AsyncRunner(
            self,
            on_start=lambda: self.statusBar().showMessage("Working..."),
            on_error=self._show_error,
        )

        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        outer = QVBoxLayout(root_widget)
        outer.setContentsMargins(12, 12, 12, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        self._sidebar = WorkspaceSidebar(WorkspaceRegistry())
        self._sidebar.setMinimumWidth(190)
        splitter.addWidget(self._sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self._workspace_title = QLabel("No workspace selected")
        self._workspace_title.setStyleSheet("font-weight: 600; font-size: 16px;")
        self._workspace_subtitle = QLabel("")
        self._workspace_subtitle.setStyleSheet("color: #64748b;")
        right_layout.addWidget(self._workspace_title)
        right_layout.addWidget(self._workspace_subtitle)

        self._tabs = QTabWidget()
        self._versions_tab = VersionsTab()
        self._archives_tab = ArchivesTab()
        self._tabs.addTab(self._versions_tab, "Versions")
        self._tabs.addTab(self._archives_tab, "Archives (0)")
        right_layout.addWidget(self._tabs, 1)

        splitter.addWidget(right)
        splitter.setSizes([220, 700])

        self._sidebar.workspace_selected.connect(self._on_workspace_selected)
        self._sidebar.clone_remote_requested.connect(self._clone_remote)
        self._versions_tab.save_requested.connect(self._save)
        self._versions_tab.refresh_requested.connect(lambda: self._refresh(quiet=False))
        self._versions_tab.clone_requested.connect(self._clone)
        self._versions_tab.forget_requested.connect(self._forget_version)
        self._versions_tab.forget_all_requested.connect(self._forget_all)
        self._archives_tab.add_requested.connect(self._add_archive)
        self._archives_tab.logout_requested.connect(self._logout)
        self._archives_tab.unregister_requested.connect(self._unregister)

        self._on_workspace_selected(self._sidebar.current_path())

    def _show_error(self, error: EvError) -> None:
        self.statusBar().showMessage(str(error))
        QMessageBox.critical(self, "EasyVersion", str(error))

    def _on_workspace_selected(self, path: Path | None) -> None:
        if path is None:
            self._workspace_title.setText("No workspace selected")
            self._workspace_subtitle.setText("")
            self._archives_tab.set_accounts([])
            self._tabs.setTabText(1, "Archives (0)")
            self._versions_tab.clear()
            self._tabs.setEnabled(False)
            self.statusBar().showMessage("Add or select a workspace")
            return

        self._tabs.setEnabled(True)
        self._workspace_title.setText(path.name or str(path))
        try:
            accounts = Workspace(path=path.expanduser().resolve()).accounts()
        except EvError as error:
            self._workspace_subtitle.setText(str(path))
            self._archives_tab.set_accounts([])
            self._tabs.setTabText(1, "Archives (0)")
            self._versions_tab.clear()
            self.statusBar().showMessage(str(error))
            return

        for account in accounts:
            self._account_registry.remember(account)
        account_summary = (
            ", ".join(f"{item.user_id} @ {item.url}" for item in accounts)
            if accounts
            else "No active archives"
        )
        self._workspace_subtitle.setText(f"{path}  |  {account_summary}")
        self._archives_tab.set_accounts(accounts)
        self._tabs.setTabText(1, f"Archives ({len(accounts)})")
        if not accounts:
            self._versions_tab.clear()
            self.statusBar().showMessage(
                "Add an archive in the Archives tab to get started"
            )
            return
        self._refresh(quiet=True)

    def _refresh(self, *, quiet: bool = False) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return

        def on_done(result: ListResult) -> None:
            self._versions_tab.set_listings(result.listings)
            self.statusBar().showMessage(
                f"Loaded {len(result.listings)} version(s) from {result.account.url}"
            )

        def on_quiet_error(error: EvError) -> None:
            self._versions_tab.clear()
            self.statusBar().showMessage(str(error))

        self._runner.run(
            lambda: list_versions(path),
            on_done,
            on_error=on_quiet_error if quiet else None,
        )

    def _save(self, note: str | None) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return

        def on_done(result: SaveResult) -> None:
            self._versions_tab.clear_note()
            self.statusBar().showMessage(
                f"Saved version {result.version} to {result.account.url}"
            )
            self._refresh(quiet=True)

        self._runner.run(lambda: save(path, note), on_done)

    def _clone(self, version: int | None) -> None:
        source_path = self._sidebar.current_path()
        if source_path is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Clone Workspace As",
            str(source_path.parent / f"{source_path.name}-clone"),
        )
        if not target:
            return
        target_path = Path(target)

        def on_done(result: CloneResult) -> None:
            self._sidebar.add_workspace(target_path)
            self.statusBar().showMessage(
                f"Cloned {result.first}..{result.last} to {target_path}"
            )

        self._runner.run(lambda: clone(source_path, target_path, version), on_done)

    def _clone_remote(self) -> None:
        dialog = CloneRemoteDialog(self, self._account_registry.load(), self._runner)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url = dialog.url()
        user_id = dialog.user_id()
        workspace_id = dialog.workspace_id()
        target_path = dialog.target_path()
        version = dialog.version()

        def on_done(result: CloneResult) -> None:
            self._account_registry.remember(result.account)
            self._sidebar.add_workspace(target_path)
            self.statusBar().showMessage(
                f"Cloned {result.first}..{result.last} from {result.account.url} to {target_path}"
            )

        self._runner.run(
            lambda: clone_remote(url, user_id, workspace_id, target_path, version),
            on_done,
        )

    def _forget_version(self, version: int) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self,
            "Forget Version",
            f"Forget version {version} on all active archives?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def on_done(result: ForgetResult) -> None:
            self.statusBar().showMessage(
                f"Forgot version {result.version} on {len(result.accounts)} archive(s)"
            )
            self._refresh(quiet=True)

        self._runner.run(
            lambda: forget(path, version=version, forget_all=False), on_done
        )

    def _forget_all(self) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self,
            "Forget All",
            "Forget ALL versions on all active archives?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def on_done(result: ForgetResult) -> None:
            self._versions_tab.clear()
            self.statusBar().showMessage(
                f"Forgot all versions on {len(result.accounts)} archive(s)"
            )

        self._runner.run(lambda: forget(path, forget_all=True), on_done)

    def _add_archive(self) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return
        dialog = AccountDialog(self, self._account_registry.load())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url = dialog.url()
        raw_user = dialog.user_id()

        if dialog.mode == "login":
            account = login(path, url, raw_user)
            self._account_registry.remember(account)
            self._on_workspace_selected(path)
            self.statusBar().showMessage(f"Logged in {account.user_id} @ {account.url}")
            return

        def on_registered(created_id: UserId) -> None:
            account = login(path, url, created_id)
            self._account_registry.remember(account)
            self._on_workspace_selected(path)
            self.statusBar().showMessage(
                f"Registered and logged in {account.user_id} @ {account.url}"
            )

        self._runner.run(lambda: register(url, raw_user or None), on_registered)

    def _logout(self, account: Account) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return
        logout(path, account.url, account.user_id)
        self._on_workspace_selected(path)
        self.statusBar().showMessage(f"Logged out {account.user_id} @ {account.url}")

    def _unregister(self, account: Account) -> None:
        path = self._sidebar.current_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self,
            "Unregister",
            f"Delete user '{account.user_id}' from {account.url}?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def on_done(_: None) -> None:
            logout(path, account.url, account.user_id)
            self._account_registry.forget(account)
            self._on_workspace_selected(path)
            self.statusBar().showMessage(
                f"Unregistered {account.user_id} from {account.url}"
            )

        self._runner.run(lambda: unregister(account.url, account.user_id), on_done)


def main() -> None:
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
