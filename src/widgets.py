"""
Custom Widgets for DBI Backend
"""
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QSplitterHandle, QSplitter,
    QStyledItemDelegate
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
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
                # Expand
                new_sizes = sizes.copy()
                new_sizes[widget_after_index] = 200
                max_index = sizes.index(max(sizes))
                if new_sizes[max_index] > 200:
                    new_sizes[max_index] -= 200
                splitter.setSizes(new_sizes)
            else:
                # Collapse
                new_sizes = sizes.copy()
                if widget_after_index > 0:
                    new_sizes[widget_after_index - 1] += new_sizes[widget_after_index]
                new_sizes[widget_after_index] = 0
                splitter.setSizes(new_sizes)

    def paintEvent(self, event):
        """
        Custom paint to show a subtle grip instead of a thick bar.
        Adapts automatically to Light/Dark theme via palette.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        if self.is_collapsed:
            # Draw blue bar when collapsed to indicate it can be expanded
            painter.fillRect(rect, QColor('#2196F3'))
        else:
            # Draw transparent background (let theme handle it)
            # Draw a subtle "Grip" (3 dots) in the center
            
            # Get text color from current theme (White in dark mode, Black in light)
            # Use semi-transparent alpha for subtlety
            grip_color = self.palette().text().color()
            grip_color.setAlpha(60) 
            
            painter.setBrush(QBrush(grip_color))
            painter.setPen(Qt.PenStyle.NoPen)

            cx = rect.center().x()
            cy = rect.center().y()
            radius = 2.0
            spacing = 8

            if self.orientation() == Qt.Orientation.Vertical:
                # Horizontal dots for vertical splitter
                painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
                painter.drawEllipse(QRectF(cx - radius - spacing, cy - radius, radius * 2, radius * 2))
                painter.drawEllipse(QRectF(cx - radius + spacing, cy - radius, radius * 2, radius * 2))
            else:
                # Vertical dots for horizontal splitter
                painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
                painter.drawEllipse(QRectF(cx - radius, cy - radius - spacing, radius * 2, radius * 2))
                painter.drawEllipse(QRectF(cx - radius, cy - radius + spacing, radius * 2, radius * 2))


class CustomSplitter(QSplitter):
    """Custom splitter that uses custom handles"""
    sizes_changed = pyqtSignal()

    def createHandle(self):
        """Create custom handle"""
        return CustomSplitterHandle(self.orientation(), self)

    def setSizes(self, sizes):
        """Override to emit signal when sizes change"""
        super().setSizes(sizes)
        self.sizes_changed.emit()


class ZoomableTreeWidget(QTreeWidget):
    """QTreeWidget with Ctrl+Wheel zoom support"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_level = 0
        self.base_font_size = 9
        self.min_zoom = -5
        self.max_zoom = 10
        self.sortByColumn(3, Qt.SortOrder.AscendingOrder)
        self.header().setSortIndicatorShown(True)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel events for zooming with Ctrl"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_level = min(self.zoom_level + 1, self.max_zoom)
            else:
                self.zoom_level = max(self.zoom_level - 1, self.min_zoom)

            self.apply_zoom()
            event.accept()
        else:
            super().wheelEvent(event)

    def apply_zoom(self):
        """Apply the current zoom level to the widget"""
        new_size = self.base_font_size + self.zoom_level
        font = self.font()
        font.setPointSize(new_size)
        self.setFont(font)
        self.setStyleSheet(f"QTreeWidget {{ font-size: {new_size}pt; }}")

    def keyPressEvent(self, event):
        """Handle key press events for the tree widget"""
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            selected_items = self.selectedItems()
            if selected_items:
                current_item = selected_items[0]
                current_index = self.indexOfTopLevelItem(current_item)
                
                next_index = current_index + 1
                if next_index < self.topLevelItemCount():
                    next_item = self.topLevelItem(next_index)
                    if next_item:
                        self.clearSelection()
                        next_item.setSelected(True)
                        self.setCurrentItem(next_item)

                event.accept()
                return

        super().keyPressEvent(event)


class ProgressDelegate(QStyledItemDelegate):
    """Custom delegate to draw progress bar background for file items"""

    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self.tree_widget = tree_widget
        self.progress_data = {}
        self.skipped_files = set()

    def set_progress(self, filename: str, progress: int):
        """Set progress for a file"""
        self.progress_data[filename] = max(0, min(100, progress))

    def mark_skipped(self, filename: str):
        """Mark a file as skipped (will be shown in red)"""
        self.skipped_files.add(filename)

    def paint(self, painter, option, index):
        """Custom paint with progress bar background"""
        item = self.tree_widget.itemFromIndex(index)
        if item:
            filename = item.text(1)

            if filename in self.skipped_files:
                painter.save()
                color = QColor(244, 67, 54, 100)
                painter.fillRect(option.rect, QBrush(color))
                painter.restore()
            else:
                progress = self.progress_data.get(filename, 0)
                if progress > 0:
                    painter.save()
                    progress_width = int((option.rect.width() * progress) / 100)
                    progress_rect = option.rect.adjusted(0, 0, progress_width - option.rect.width(), 0)
                    
                    if progress >= 100:
                        color = QColor(80, 200, 80, 100)
                    else:
                        color = QColor(60, 180, 60, 80)

                    painter.fillRect(progress_rect, QBrush(color))
                    painter.restore()

        super().paint(painter, option, index)