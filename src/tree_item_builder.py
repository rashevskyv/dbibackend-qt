"""
Tree Item UI Helpers for DBI Backend.
Provides widget builders for tree rows and folder state aggregators.
"""
from pathlib import Path
from typing import Callable, Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QCheckBox, QComboBox, QTreeWidgetItem, QTreeWidget,
    QLabel, QApplication
)
from PyQt6.QtCore import Qt, QPoint, QMimeData
from PyQt6.QtGui import QColor, QIcon, QDrag, QPixmap, QPainter

from .widgets import (
    FileTreeWidgetItem, CHECKED_ROLE, IS_FOLDER_ROLE,
    FILE_PATH_ROLE, IS_CONFLICT_ROLE
)
from .utility_functions import format_size
from .queue_manager import (
    FileRecord, FolderRecord, STATUS_QUEUED, STATUS_PROCESS,
    STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED, STATUS_CONFLICT
)


class DragHandle(QLabel):
    """Visual drag handle widget shown to the left of row checkboxes."""

    def __init__(self, item: QTreeWidgetItem, draggable: bool = True, parent=None):
        super().__init__("⠿", parent)
        self.item = item
        self.draggable = draggable
        self._drag_start_pos = None
        self.setFixedWidth(16)
        self.setFixedHeight(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_draggable(draggable)

    def is_draggable(self) -> bool:
        return self.draggable

    def set_draggable(self, draggable: bool):
        self.draggable = draggable
        if draggable:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.setToolTip("Drag handle to reorder queue")
            self.setStyleSheet("color: #888888; font-size: 13px; font-weight: bold;")
        else:
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
            self.setToolTip("Active or completed items cannot be reordered")
            self.setStyleSheet("color: #444444; font-size: 13px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.draggable:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.draggable or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        tree = self.item.treeWidget()
        if not tree:
            return

        p_str = self.item.data(5, FILE_PATH_ROLE)
        if not p_str:
            return

        drag = QDrag(tree)
        mime = QMimeData()
        mime.setData("application/x-dbibackend-drag-path", p_str.encode('utf-8'))
        is_child = (self.item.parent() is not None)
        mime.setData("application/x-dbibackend-drag-kind", b"child" if is_child else b"top")
        if is_child:
            parent_p_str = self.item.parent().data(5, FILE_PATH_ROLE) or ""
            mime.setData("application/x-dbibackend-drag-parent", parent_p_str.encode('utf-8'))

        pixmap = QPixmap(160, 24)
        pixmap.fill(QColor(33, 150, 243, 180))
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        name = self.item.text(1)
        elided = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, 150)
        painter.drawText(8, 16, elided)
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(10, 12))
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None


def create_row_checkbox_widget(item: QTreeWidgetItem, checkbox: QCheckBox, is_draggable: bool = True) -> QWidget:
    """Wrap a DragHandle and QCheckBox inside a row widget for column 0 placement."""
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(2, 0, 2, 0)
    layout.setSpacing(2)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    handle = DragHandle(item, draggable=is_draggable, parent=w)
    layout.addWidget(handle)
    layout.addWidget(checkbox)
    w.setLayout(layout)
    return w


def create_centered_checkbox_widget(checkbox: QCheckBox) -> QWidget:
    """Wrap a QCheckBox inside a centered, margin-less QWidget for tree item placement."""
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.addWidget(checkbox)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


def update_folder_checkbox_visual(
    folder_item: QTreeWidgetItem,
    is_checked_fn: Callable[[QTreeWidgetItem], bool],
    checkbox_getter: Callable[[QTreeWidgetItem], Optional[QCheckBox]]
):
    """Update folder checkbox state (Checked, Unchecked, or PartiallyChecked) based on its child items."""
    total = folder_item.childCount()
    if total == 0:
        return
    checked_count = sum(1 for i in range(total) if is_checked_fn(folder_item.child(i)))
    cb = checkbox_getter(folder_item)
    if cb is not None:
        cb.blockSignals(True)
        if checked_count == 0:
            cb.setCheckState(Qt.CheckState.Unchecked)
            folder_item.setData(0, CHECKED_ROLE, False)
        elif checked_count == total:
            cb.setCheckState(Qt.CheckState.Checked)
            folder_item.setData(0, CHECKED_ROLE, True)
        else:
            cb.setCheckState(Qt.CheckState.PartiallyChecked)
            folder_item.setData(0, CHECKED_ROLE, True)
        cb.blockSignals(False)


def update_folder_aggregate_status(folder_item: QTreeWidgetItem):
    """Aggregate statuses of child items and reflect the combined status on the folder row."""
    total = folder_item.childCount()
    if total == 0:
        return
    statuses = [folder_item.child(i).data(4, Qt.ItemDataRole.UserRole) or 0 for i in range(total)]
    if all(s == STATUS_DONE for s in statuses):
        folder_item.setText(4, "✅ Done")
        folder_item.setForeground(4, QColor('#4CAF50'))
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_DONE)
    elif any(s == STATUS_PROCESS for s in statuses):
        folder_item.setText(4, "🔄 Process")
        folder_item.setForeground(4, QColor('#2196F3'))
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_PROCESS)
    elif any(s == STATUS_FAILED for s in statuses):
        folder_item.setText(4, "❌ Failed")
        folder_item.setForeground(4, QColor('#F44336'))
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_FAILED)
    elif any(s == STATUS_CONFLICT for s in statuses):
        folder_item.setText(4, "⚠️ Conflict")
        folder_item.setForeground(4, QColor('#FF9800'))
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_CONFLICT)
    elif all(s == STATUS_SKIPPED for s in statuses):
        folder_item.setText(4, "⏭ Skipped")
        folder_item.setForeground(4, QColor('#808080'))
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_SKIPPED)
    else:
        folder_item.setText(4, "Queued")
        folder_item.setData(4, Qt.ItemDataRole.UserRole, STATUS_QUEUED)


def build_folder_row(
    tree: QTreeWidget,
    folder_path: Path,
    folder_rec: FolderRecord,
    folder_icon: QIcon,
    on_toggle: Callable[[QTreeWidgetItem, int], None],
    on_target: Callable[[QTreeWidgetItem, int], None]
) -> QTreeWidgetItem:
    """Create and configure a folder row in the tree widget."""
    folder_item = FileTreeWidgetItem(tree)
    folder_item.setIcon(1, folder_icon)
    folder_item.setText(1, folder_rec.name)
    folder_item.setText(5, str(folder_path))
    folder_item.setData(0, IS_FOLDER_ROLE, True)
    folder_item.setData(5, FILE_PATH_ROLE, str(folder_path))

    f_cb = QCheckBox()
    f_cb.setTristate(True)
    f_cb.setChecked(folder_rec.checked)
    folder_item.setData(0, CHECKED_ROLE, folder_rec.checked)
    f_cb.stateChanged.connect(lambda state, it=folder_item: on_toggle(it, state))
    f_draggable = (folder_rec.status_code not in (STATUS_PROCESS, STATUS_DONE))
    tree.setItemWidget(folder_item, 0, create_row_checkbox_widget(folder_item, f_cb, is_draggable=f_draggable))

    f_combo = QComboBox()
    f_combo.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    f_combo.addItems(["Auto", "SD Card", "NAND"])
    f_combo.setCurrentIndex(folder_rec.target)
    f_combo.currentIndexChanged.connect(lambda idx, it=folder_item: on_target(it, idx))
    tree.setItemWidget(folder_item, 3, f_combo)
    folder_item.setText(3, "")
    folder_item.setData(3, Qt.ItemDataRole.UserRole, folder_rec.target)

    return folder_item


def build_file_row(
    parent: QTreeWidgetItem,
    file_path: Path,
    rec: FileRecord,
    file_icon: QIcon,
    should_check: bool,
    cur_target: int,
    on_toggle: Callable[[QTreeWidgetItem, int], None],
    on_target: Callable[[Path, int], None]
) -> QTreeWidgetItem:
    """Create and configure a child or standalone file row in the tree widget."""
    item = FileTreeWidgetItem(parent)
    item.setIcon(1, file_icon)
    item.setText(1, rec.name)
    item.setText(2, format_size(rec.size))
    item.setData(2, Qt.ItemDataRole.UserRole, rec.size)
    item.setText(5, str(file_path))
    item.setData(0, IS_FOLDER_ROLE, False)
    item.setData(5, FILE_PATH_ROLE, str(file_path))

    tree = parent.treeWidget() if isinstance(parent, QTreeWidgetItem) else parent

    cb = QCheckBox()
    if rec.in_conflict:
        cb.setChecked(False)
        cb.setEnabled(False)
        cb.setToolTip("Cannot select: duplicate filename conflict")
        item.setData(0, CHECKED_ROLE, False)
        item.setData(0, IS_CONFLICT_ROLE, True)
        item.setText(4, "⚠️ Name Conflict")
        item.setForeground(4, QColor('#FF9800'))
        item.setData(4, Qt.ItemDataRole.UserRole, STATUS_CONFLICT)
    else:
        cb.setChecked(should_check)
        item.setData(0, CHECKED_ROLE, should_check)
        item.setText(4, "Queued")
        item.setData(4, Qt.ItemDataRole.UserRole, STATUS_QUEUED)

    cb.stateChanged.connect(lambda state, it=item: on_toggle(it, state))
    c_draggable = (not rec.in_conflict and rec.status_code not in (STATUS_PROCESS, STATUS_DONE))
    tree.setItemWidget(item, 0, create_row_checkbox_widget(item, cb, is_draggable=c_draggable))

    combo = QComboBox()
    combo.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    combo.addItems(["Auto", "SD Card", "NAND"])
    combo.setCurrentIndex(cur_target)
    combo.currentIndexChanged.connect(lambda idx, path=file_path: on_target(path, idx))
    tree.setItemWidget(item, 3, combo)
    item.setText(3, "")
    item.setData(3, Qt.ItemDataRole.UserRole, cur_target)

    return item
