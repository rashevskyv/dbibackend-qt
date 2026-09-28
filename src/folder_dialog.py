"""
Folder addition mode dialog for DBI Backend.
Prompts the user to choose between adding a folder hierarchically or scanning for flat files,
with an option to apply the choice to all folders in the current batch.
"""
from typing import Optional, Tuple
from html import escape
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QStyle
)
from PyQt6.QtCore import Qt


class FolderModeDialog(QDialog):
    """Dialog asking whether to add a folder hierarchically or scan for flat files."""

    MODE_FOLDER = 'folder'
    MODE_FILES = 'files'

    def __init__(self, folder_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Folder")
        self.setMinimumWidth(430)
        self.chosen_mode: Optional[str] = None
        self.apply_to_all: bool = False

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel()
        if parent is not None:
            icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
            icon_label.setPixmap(icon.pixmap(32, 32))
            header_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        msg = QLabel(
            f"<b>How do you want to add the folder:</b><br>"
            f"<span style='color: #2196F3; font-size: 13px;'>\"{escape(folder_name)}\"</span>?<br><br>"
            f"• <b>Add as Folder:</b> Keep folder in queue with expandable files.<br>"
            f"• <b>Add as Files:</b> Scan and add supported Switch files directly."
        )
        msg.setWordWrap(True)
        header_layout.addWidget(msg, 1)
        layout.addLayout(header_layout)

        self.cb_apply_all = QCheckBox("Apply this choice to all folders in current addition")
        layout.addWidget(self.cb_apply_all)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self._on_cancel)

        btn_files = QPushButton("📄 Add as Files")
        btn_files.clicked.connect(self._on_files)

        btn_folder = QPushButton("📁 Add as Folder")
        btn_folder.setDefault(True)
        btn_folder.clicked.connect(self._on_folder)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_files)
        btn_layout.addWidget(btn_folder)
        layout.addLayout(btn_layout)

    def _on_folder(self):
        self.chosen_mode = self.MODE_FOLDER
        self.apply_to_all = self.cb_apply_all.isChecked()
        self.accept()

    def _on_files(self):
        self.chosen_mode = self.MODE_FILES
        self.apply_to_all = self.cb_apply_all.isChecked()
        self.accept()

    def _on_cancel(self):
        self.chosen_mode = None
        self.apply_to_all = False
        self.reject()

    @classmethod
    def ask_mode(cls, folder_name: str, parent=None) -> Tuple[Optional[str], bool]:
        dlg = cls(folder_name, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.chosen_mode, dlg.apply_to_all
        return None, False
