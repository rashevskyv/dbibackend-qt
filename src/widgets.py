"""
Custom Widgets for DBI Backend
"""
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QSplitterHandle, QSplitter,
    QStyledItemDelegate, QCheckBox, QProgressBar, QWidget,
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QRect, QPropertyAnimation, QPoint, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QBrush, QWheelEvent, QPen, QLinearGradient, QPaintEvent, QFont

class FileTreeWidgetItem(QTreeWidgetItem):
    """Custom tree widget item with advanced sorting logic"""

    def _get_status_sort_tuple(self):
        tree = self.treeWidget()
        if not tree: return (9, 0, self.text(1))

        status_data = self.data(3, Qt.ItemDataRole.UserRole) or 0
        size_data = self.data(2, Qt.ItemDataRole.UserRole) or 0
        
        is_checked = True
        widget = tree.itemWidget(self, 0)
        if widget:
            cb = widget.findChild(QCheckBox)
            if cb: is_checked = cb.isChecked()

        # Priority mapping: lower is higher on the list
        if status_data == 1:     # 🔄 Process — Always at the very top
            primary_priority = 0
        elif status_data == 3:   # ❌ Failed — Needs attention
            primary_priority = 1
        elif status_data == 0 and is_checked: # Queued (Checked) — The main queue
            primary_priority = 2
        elif status_data == 4:   # ⏭ Skipped — Intentionally set aside
            primary_priority = 3
        elif status_data == 2:   # ✅ Done — Completed tasks
            primary_priority = 4
        elif status_data == 5:   # ⚠️ Missing — Known issues
            primary_priority = 5
        else:                    # Unchecked or other
            primary_priority = 10

        # Secondary sort: Queued items by size (descending), others alphabetical
        if status_data == 0 and is_checked:
            secondary_sort = -size_data
        else:
            secondary_sort = 0

        return (primary_priority, secondary_sort, self.text(1))

    def __lt__(self, other):
        if not isinstance(other, FileTreeWidgetItem):
            return super().__lt__(other)
        tree = self.treeWidget()
        if not tree:
            return super().__lt__(other)
        sort_column = tree.sortColumn()
        if sort_column == 3:
            return self._get_status_sort_tuple() < other._get_status_sort_tuple()
        elif sort_column == 2:
            self_size = self.data(2, Qt.ItemDataRole.UserRole) or 0
            other_size = other.data(2, Qt.ItemDataRole.UserRole) or 0
            return self_size < other_size
        else:
            return super().__lt__(other)


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle with modern styling"""
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.is_collapsed = False

    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        sizes = splitter.sizes()
        handle_index = splitter.indexOf(self)
        if handle_index > 0 and handle_index < len(sizes):
            widget_after_index = handle_index
            if sizes[widget_after_index] == 0:
                new_sizes = sizes.copy()
                new_sizes[widget_after_index] = 200
                max_index = sizes.index(max(sizes))
                if new_sizes[max_index] > 200: new_sizes[max_index] -= 200
                splitter.setSizes(new_sizes)
            else:
                new_sizes = sizes.copy()
                if widget_after_index > 0: new_sizes[widget_after_index-1] += new_sizes[widget_after_index]
                new_sizes[widget_after_index] = 0
                splitter.setSizes(new_sizes)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        if self.is_collapsed:
            painter.fillRect(rect, QColor('#2196F3'))
        else:
            grip_color = self.palette().text().color()
            grip_color.setAlpha(60) 
            painter.setBrush(QBrush(grip_color))
            painter.setPen(Qt.PenStyle.NoPen)
            cx, cy, radius, spacing = rect.center().x(), rect.center().y(), 2.0, 8
            if self.orientation() == Qt.Orientation.Vertical:
                for offset in [-spacing, 0, spacing]: painter.drawEllipse(QRectF(cx-radius+offset, cy-radius, radius*2, radius*2))
            else:
                for offset in [-spacing, 0, spacing]: painter.drawEllipse(QRectF(cx-radius, cy-radius+offset, radius*2, radius*2))


class CustomSplitter(QSplitter):
    """Custom splitter that uses custom handles"""
    sizes_changed = pyqtSignal()
    def createHandle(self): return CustomSplitterHandle(self.orientation(), self)
    def setSizes(self, sizes): super().setSizes(sizes); self.sizes_changed.emit()


class ZoomableTreeWidget(QTreeWidget):
    """QTreeWidget with Ctrl+Wheel zoom and context awareness"""
    space_pressed = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.file_manager = getattr(main_window, 'file_manager', None)
        self.zoom_level = 0
        self.base_font_size = 9
        self.min_zoom = -5
        self.max_zoom = 10
        self.sortByColumn(3, Qt.SortOrder.AscendingOrder)
        self.header().setSortIndicatorShown(True)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0: self.zoom_level = min(self.zoom_level + 1, self.max_zoom)
            else: self.zoom_level = max(self.zoom_level - 1, self.min_zoom)
            self.apply_zoom()
            event.accept()
        else:
            super().wheelEvent(event)

    def apply_zoom(self):
        new_size = self.base_font_size + self.zoom_level
        font = self.font()
        font.setPointSize(new_size)
        self.setFont(font)
        self.setStyleSheet(f"QTreeWidget {{ font-size: {new_size}pt; }}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            self.space_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ProgressDelegate(QStyledItemDelegate):
    """Delegate to draw a continuous progress bar background across the entire row."""
    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self.tree_widget = tree_widget
        self.progress_data = {}
        self.skipped_files = set()
        self.progress_color = QColor(33, 150, 243, 50) 
        self.skipped_color = QColor(128, 128, 128, 40) # Neutral gray background for skipped

    def set_progress(self, filename: str, progress: int): self.progress_data[filename] = max(0, min(100, progress))
    def mark_skipped(self, filename: str): self.skipped_files.add(filename)
    def clear_all(self): self.progress_data.clear(); self.skipped_files.clear()
    def set_theme_color(self, hex_color: str): c = QColor(hex_color); c.setAlpha(60); self.progress_color = c

    def paint(self, painter, option, index):
        item = self.tree_widget.itemFromIndex(index)
        if item:
            filename = item.text(1)
            is_skipped = filename in self.skipped_files
            progress = self.progress_data.get(filename, 0)
            status_data = item.data(3, Qt.ItemDataRole.UserRole) or 0
            is_done = (status_data == 2)

            if is_skipped or (progress > 0) or is_done:
                painter.save()
                total_width = sum(self.tree_widget.columnWidth(i) for i in range(self.tree_widget.columnCount()) if not self.tree_widget.isColumnHidden(i))
                
                if is_skipped:
                    fill_width = total_width
                    fill_color = self.skipped_color
                else:
                    fill_percent = 100.0 if is_done else progress
                    fill_width = int(total_width * (fill_percent / 100.0))
                    fill_color = self.progress_color
                    
                progress_rect = QRect(0, option.rect.y(), fill_width, option.rect.height())
                painter.setClipRect(option.rect)
                painter.fillRect(progress_rect, QBrush(fill_color))
                painter.restore()
        super().paint(painter, option, index)


class AnimatedProgressBar(QProgressBar):
    """A progress bar that shows a moving gradient animation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.animation_offset = 0.0
        self.bar_color = QColor("#4CAF50")
        self.is_animating = False

    def set_theme_color(self, hex_color):
        self.bar_color = QColor(hex_color)
        self.update()

    def step_animation(self):
        if self.value() >= 100 or self.value() <= 0: return
        self.animation_offset += 0.05
        if self.animation_offset > 1.0: self.animation_offset -= 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        text_color = self.palette().text().color()
        bg_color = QColor("#252526") if text_color.lightness() > 128 else QColor("#e0e0e0")
        painter.fillRect(rect, bg_color)
        if self.maximum() > 0: ratio = self.value() / self.maximum()
        else: ratio = 0
        filled_width = int(rect.width() * ratio)
        if filled_width > 0:
            filled_rect = QRect(0, 0, filled_width, rect.height())
            gradient = QLinearGradient(0, 0, rect.width(), 0)
            c_base = self.bar_color
            c_light = self.bar_color.lighter(160)
            gradient.setColorAt(0, c_base)
            wave_center = self.animation_offset
            if 0 <= wave_center - 0.1 <= 1: gradient.setColorAt(wave_center - 0.1, c_base)
            if 0 <= wave_center <= 1:       gradient.setColorAt(wave_center, c_light)
            if 0 <= wave_center + 0.1 <= 1: gradient.setColorAt(wave_center + 0.1, c_base)
            gradient.setColorAt(1, c_base)
            painter.fillRect(filled_rect, QBrush(gradient))
        text = self.text()
        if self.isTextVisible() and text:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

# --- Toggle Switch ---
class ToggleSwitch(QCheckBox):
    """A custom toggle switch widget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        
        # --- FIX: Set specific colors for USB (Off) and HTTP (On) ---
        self._bg_color_off = QColor("#4CAF50") # Green (USB)
        self._bg_color_on = QColor("#2196F3")  # Blue (HTTP)
        self._handle_color = QColor("#FFFFFF")
        
        self._handle_position = 3.0
        self.animation = QPropertyAnimation(self, b"handle_position", self)
        self.animation.setDuration(200)
        self.stateChanged.connect(self.setup_animation)

    @pyqtProperty(float)
    def handle_position(self): return self._handle_position

    @handle_position.setter
    def handle_position(self, pos): self._handle_position = pos; self.update()

    def set_theme_color(self, color_hex):
        # Override ON color if needed, but defaults are usually fine
        self._bg_color_on = QColor(color_hex)
        self.update()

    def setup_animation(self, state):
        self.animation.stop()
        if state: self.animation.setEndValue(float(self.width() - 19))
        else: self.animation.setEndValue(3.0)
        self.animation.start()

    def hitButton(self, pos: QPoint): return self.rect().contains(pos)

    def paintEvent(self, e: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        track_color = self._bg_color_on if self.isChecked() else self._bg_color_off
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(0, 0, rect.width(), rect.height(), 11, 11)
        p.setBrush(self._handle_color)
        p.drawEllipse(int(self._handle_position), 3, 16, 16)


class MissingFileDialog(QDialog):
    """Dialog shown when a file from a preset is missing"""
    IGNORE = 0
    REMOVE = 1
    UPDATE = 2
    CANCEL = 3

    def __init__(self, filename, filepath, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Not Found")
        self.setMinimumWidth(450)
        self.result_code = self.IGNORE
        self.apply_all = False

        layout = QVBoxLayout(self)

        msg = QLabel(f"<b>File not found:</b><br>{filename}<br><br><b>Path:</b><br>{filepath}")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addSpacing(10)

        self.cb_apply_all = QCheckBox("Apply to all remaining missing files")
        layout.addWidget(self.cb_apply_all)

        layout.addSpacing(15)

        btn_layout = QHBoxLayout()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setToolTip("Cancel preset loading entirely")
        btn_cancel.clicked.connect(self.on_cancel)

        btn_ignore = QPushButton("Ignore")
        btn_ignore.setToolTip("Keep in list but disable")
        btn_ignore.clicked.connect(self.on_ignore)

        btn_remove = QPushButton("Remove")
        btn_remove.setToolTip("Remove from list")
        btn_remove.clicked.connect(self.on_remove)

        btn_update = QPushButton("Update Path")
        btn_update.setToolTip("Locate the file manually")
        btn_update.clicked.connect(self.on_update)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ignore)
        btn_layout.addWidget(btn_remove)
        btn_layout.addWidget(btn_update)

        layout.addLayout(btn_layout)

    def on_cancel(self):
        self.result_code = self.CANCEL
        self.apply_all = False
        self.accept()

    def on_ignore(self):
        self.result_code = self.IGNORE
        self.apply_all = self.cb_apply_all.isChecked()
        self.accept()

    def on_remove(self):
        self.result_code = self.REMOVE
        self.apply_all = self.cb_apply_all.isChecked()
        self.accept()

    def on_update(self):
        self.result_code = self.UPDATE
        self.apply_all = self.cb_apply_all.isChecked()
        self.accept()