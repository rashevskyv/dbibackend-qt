"""
Sphaira-style storage capacity bars widget.
Displays dual progress bars for microSD and NAND storage with dynamic install fill.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath

from .utility_functions import format_size


class StorageBarRow(QWidget):
    """Single storage bar row in Sphaira style: [Label] [Bar with used+install fill] [Free value]."""

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        self.label_text = label_text
        self.free_bytes = 0
        self.total_bytes = 0
        self.highlight_bytes = 0  # Total size of package being installed
        self.focus_bytes = 0      # Written bytes of package being installed
        self.setFixedHeight(16)

    def set_storage(self, free_bytes: int, total_bytes: int):
        self.free_bytes = free_bytes
        self.total_bytes = total_bytes
        self.update()

    def set_install_progress(self, focus_bytes: int, highlight_bytes: int):
        self.focus_bytes = min(focus_bytes, highlight_bytes)
        self.highlight_bytes = highlight_bytes
        self.update()

    def clear_install_progress(self):
        self.focus_bytes = 0
        self.highlight_bytes = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # 1. Left Label: "NAND" or "microSD"
        label_w = 54
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        is_dark = self.palette().text().color().lightness() > 128
        label_col = QColor("#9e9e9e") if is_dark else QColor("#555555")
        val_col = QColor("#cccccc") if is_dark else QColor("#333333")
        track_col = QColor(60, 60, 60, 200) if is_dark else QColor(210, 210, 210, 220)

        painter.setPen(label_col)
        painter.drawText(0, 0, label_w, h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label_text)

        # 2. Right Value: e.g. "12.4 GB free"
        val_w = 80
        val_x = w - val_w
        if self.total_bytes > 0:
            if self.highlight_bytes > 0 and self.focus_bytes > 0:
                val_text = f"+{format_size(self.focus_bytes)}"
            else:
                val_text = f"{format_size(self.free_bytes)} free"
        else:
            val_text = "--"

        painter.setPen(val_col)
        font_val = painter.font()
        font_val.setBold(False)
        painter.setFont(font_val)
        painter.drawText(val_x, 0, val_w, h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val_text)

        # 3. Bar: between label and value
        bar_x = label_w + 6
        bar_w = max(0, val_x - bar_x - 8)
        bar_h = 7
        bar_y = int((h - bar_h) / 2)

        if bar_w <= 0:
            return

        # Track (background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_col)
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)

        if self.total_bytes > 0:
            used_bytes = max(0, self.total_bytes - self.free_bytes)
            used_ratio = min(1.0, used_bytes / self.total_bytes)
            fill_w = int(bar_w * used_ratio)

            # SFIRE fill color thresholds:
            # > 0.90: Red rgb(230, 60, 60)
            # > 0.75: Amber rgb(230, 180, 60)
            # <= 0.75: Green rgb(90, 200, 120)
            if used_ratio > 0.90:
                fill_col = QColor(230, 60, 60)
            elif used_ratio > 0.75:
                fill_col = QColor(230, 180, 60)
            else:
                fill_col = QColor(90, 200, 120)

            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(float(bar_x), float(bar_y), float(bar_w), float(bar_h), 3.0, 3.0)
            painter.setClipPath(clip_path)

            if fill_w > 0:
                painter.setBrush(fill_col)
                painter.drawRect(bar_x, bar_y, fill_w, bar_h)

            # Active installation dynamic fill in Sphaira style:
            # - Written bytes advance used fill (in bright green/fill)
            # - Remaining package bytes are drawn in SFIRE yellow rgb(255, 200, 60)
            if self.highlight_bytes > 0:
                written_ratio = self.focus_bytes / self.total_bytes
                written_w = int(bar_w * written_ratio)
                rem_bytes = max(0, self.highlight_bytes - self.focus_bytes)
                rem_ratio = rem_bytes / self.total_bytes
                seg_w = max(2, int(bar_w * rem_ratio)) if rem_bytes > 0 else 0

                if written_w > 0:
                    painter.setBrush(fill_col.lighter(120))
                    painter.drawRect(bar_x + fill_w, bar_y, min(written_w, bar_w - fill_w), bar_h)

                if seg_w > 0:
                    painter.setBrush(QColor(255, 200, 60))
                    painter.drawRect(bar_x + fill_w + written_w, bar_y, min(seg_w, bar_w - fill_w - written_w), bar_h)

            painter.restore()


class SwitchStorageWidget(QWidget):
    """Two stacked storage capacity bars for microSD and NAND matching Sphaira's UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.nand_row = StorageBarRow("NAND", self)
        self.sd_row = StorageBarRow("microSD", self)

        layout.addWidget(self.nand_row)
        layout.addWidget(self.sd_row)

        self.setFixedHeight(34)
        self.setMinimumWidth(200)
        self._update_tooltips()

    def set_storage_info(self, nand_free: int, nand_total: int, sd_free: int, sd_total: int):
        self.nand_row.set_storage(nand_free, nand_total)
        self.sd_row.set_storage(sd_free, sd_total)
        self._update_tooltips()

    def set_install_progress(self, target: str, focus_bytes: int, highlight_bytes: int):
        """target is 'sd' or 'nand'."""
        if target == 'sd':
            self.sd_row.set_install_progress(focus_bytes, highlight_bytes)
            self.nand_row.clear_install_progress()
        elif target == 'nand':
            self.nand_row.set_install_progress(focus_bytes, highlight_bytes)
            self.sd_row.clear_install_progress()
        else:
            self.clear_install_progress()
        self._update_tooltips()

    def clear_install_progress(self):
        self.sd_row.clear_install_progress()
        self.nand_row.clear_install_progress()
        self._update_tooltips()

    def _update_tooltips(self):
        if self.sd_row.total_bytes > 0:
            sd_used = max(0, self.sd_row.total_bytes - self.sd_row.free_bytes)
            sd_pct = int((sd_used / self.sd_row.total_bytes) * 100)
            nand_used = max(0, self.nand_row.total_bytes - self.nand_row.free_bytes)
            nand_pct = int((nand_used / self.nand_row.total_bytes) * 100) if self.nand_row.total_bytes > 0 else 0
            tip = (
                f"microSD: {format_size(self.sd_row.free_bytes)} free of {format_size(self.sd_row.total_bytes)} ({sd_pct}% used)\n"
                f"NAND: {format_size(self.nand_row.free_bytes)} free of {format_size(self.nand_row.total_bytes)} ({nand_pct}% used)"
            )
            if self.sd_row.highlight_bytes > 0:
                tip += f"\nInstalling to microSD: {format_size(self.sd_row.focus_bytes)} / {format_size(self.sd_row.highlight_bytes)}"
            elif self.nand_row.highlight_bytes > 0:
                tip += f"\nInstalling to NAND: {format_size(self.nand_row.focus_bytes)} / {format_size(self.nand_row.highlight_bytes)}"
        else:
            tip = "Waiting for console storage info..."
        self.setToolTip(tip)
