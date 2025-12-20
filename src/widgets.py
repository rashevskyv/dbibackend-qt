"""
Custom Widgets for DBI Backend
"""
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QSplitterHandle, QSplitter,
    QStyledItemDelegate
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QRect
from PyQt6.QtGui import QColor, QPainter, QBrush, QWheelEvent, QPen

class FileTreeWidgetItem(QTreeWidgetItem):
    """Custom tree widget item that properly sorts numeric values and statuses"""
    
    def __lt__(self, other):
        """Override comparison for proper sorting"""
        if not isinstance(other, FileTreeWidgetItem):
            return super().__lt__(other)
            
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        
        if column == 0:
            self_state = self.data(0, Qt.ItemDataRole.UserRole) or 0
            other_state = other.data(0, Qt.ItemDataRole.UserRole) or 0
            return self_state < other_state
        
        if column == 2:
            self_size = self.data(2, Qt.ItemDataRole.UserRole) or 0
            other_size = other.data(2, Qt.ItemDataRole.UserRole) or 0
            return self_size < other_size

        if column == 3:
            self_status = self.data(3, Qt.ItemDataRole.UserRole) or 0
            other_status = other.data(3, Qt.ItemDataRole.UserRole) or 0
            return self_status < other_status
            
        return super().__lt__(other)


class CustomSplitterHandle(QSplitterHandle):
    """Custom splitter handle with modern styling"""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.is_collapsed = False

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to collapse/expand sections"""
        splitter = self.splitter()
        sizes = splitter.sizes()
        handle_index = splitter.indexOf(self)

        if handle_index > 0 and handle_index < len(sizes):
            widget_after_index = handle_index
            if sizes[widget_after_index] == 0:
                new_sizes = sizes.copy()
                new_sizes[widget_after_index] = 200
                max_index = sizes.index(max(sizes))
                if new_sizes[max_index] > 200:
                    new_sizes[max_index] -= 200
                splitter.setSizes(new_sizes)
            else:
                new_sizes = sizes.copy()
                if widget_after_index > 0:
                    new_sizes[widget_after_index - 1] += new_sizes[widget_after_index]
                new_sizes[widget_after_index] = 0
                splitter.setSizes(new_sizes)

    def paintEvent(self, event):
        """Custom paint to show a subtle grip instead of a thick bar."""
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

            cx, cy = rect.center().x(), rect.center().y()
            radius, spacing = 2.0, 8

            if self.orientation() == Qt.Orientation.Vertical:
                for offset in [-spacing, 0, spacing]:
                    painter.drawEllipse(QRectF(cx - radius + offset, cy - radius, radius * 2, radius * 2))
            else:
                for offset in [-spacing, 0, spacing]:
                    painter.drawEllipse(QRectF(cx - radius, cy - radius + offset, radius * 2, radius * 2))


class CustomSplitter(QSplitter):
    """Custom splitter that uses custom handles"""
    sizes_changed = pyqtSignal()

    def createHandle(self):
        return CustomSplitterHandle(self.orientation(), self)

    def setSizes(self, sizes):
        super().setSizes(sizes)
        self.sizes_changed.emit()


class ZoomableTreeWidget(QTreeWidget):
    """QTreeWidget with Ctrl+Wheel zoom support and Space signal"""
    
    # Signal emitted when Space is pressed (to be handled by main window)
    space_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
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
        """Handle key press events"""
        # Intercept Space to emit signal for custom toggling logic
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            self.space_pressed.emit()
            event.accept()
            return
            
        super().keyPressEvent(event)


class ProgressDelegate(QStyledItemDelegate):
    """
    Custom delegate to draw a continuous progress bar background across the entire row.
    Ignores column boundaries for the filling effect.
    """

    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self.tree_widget = tree_widget
        self.progress_data = {}
        self.skipped_files = set()
        # Default colors (will be updated by theme manager)
        self.progress_color = QColor(33, 150, 243, 50) 
        self.skipped_color = QColor(244, 67, 54, 80)

    def set_progress(self, filename: str, progress: int):
        """Set progress for a file"""
        self.progress_data[filename] = max(0, min(100, progress))

    def mark_skipped(self, filename: str):
        """Mark a file as skipped"""
        self.skipped_files.add(filename)

    def clear_all(self):
        """Clear all progress data (reset visuals)"""
        self.progress_data.clear()
        self.skipped_files.clear()

    def set_theme_color(self, hex_color: str):
        """Update the progress fill color based on theme"""
        c = QColor(hex_color)
        c.setAlpha(60) # Transparency for text readability
        self.progress_color = c

    def paint(self, painter, option, index):
        """Custom paint to draw row-wide progress"""
        item = self.tree_widget.itemFromIndex(index)
        if item:
            filename = item.text(1)
            
            is_skipped = filename in self.skipped_files
            progress = self.progress_data.get(filename, 0)

            if is_skipped or (progress > 0):
                painter.save()
                
                # Calculate the geometry of the ENTIRE row visible area
                total_width = 0
                for i in range(self.tree_widget.columnCount()):
                    if not self.tree_widget.isColumnHidden(i):
                        total_width += self.tree_widget.columnWidth(i)
                
                # Determine fill width
                if is_skipped:
                    fill_width = total_width
                    fill_color = self.skipped_color
                else:
                    fill_width = int(total_width * (progress / 100.0))
                    fill_color = self.progress_color

                # Progress rect (starts at x=0 of the row content)
                # option.rect.y() is the top Y of the row
                progress_rect = QRect(0, option.rect.y(), fill_width, option.rect.height())
                
                # Clip to the current cell (this makes the continuous effect work per cell paint)
                painter.setClipRect(option.rect)
                painter.fillRect(progress_rect, QBrush(fill_color))
                
                painter.restore()

        super().paint(painter, option, index)